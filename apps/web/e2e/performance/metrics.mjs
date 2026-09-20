import http from 'node:http';
import https from 'node:https';
import { createBrotliDecompress, createGunzip, createInflate } from 'node:zlib';

export function summary(values) {
  const sorted = values.filter(Number.isFinite).sort((a, b) => a - b);
  const percentile = (p) => sorted.length ? sorted[Math.max(0, Math.ceil(sorted.length * p) - 1)] : null;
  return { count: sorted.length, samples_ms: values, median_ms: percentile(.5), approx_p95_ms: percentile(.95) };
}

// Count actual streamed body bytes, not Content-Length or a decoded fetch buffer.
// Transfer framing/headers are excluded; CDP transfer_bytes is a separate metric.
export function sampleHttp(url, { timeoutMs = 120_000, maxBytes = 256 * 1024 * 1024 } = {}) {
  return new Promise((resolve) => {
    const start = performance.now();
    let response, decoder, settled = false;
    const result = { ok: false, status: null, ttfb_ms: null, duration_ms: null,
      encoded_body_bytes: 0, decoded_body_bytes: 0, content_encoding: null,
      server_timing: null, error: null };
    const finish = (error) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      result.duration_ms = performance.now() - start;
      result.error = error?.message ?? null;
      result.ok = !error && result.status >= 200 && result.status < 300;
      if (error) { request.destroy(); response?.destroy(); decoder?.destroy(); }
      resolve(result);
    };
    const request = (url.startsWith('https:') ? https : http).get(url, {
      headers: { 'Accept-Encoding': 'gzip, deflate, br' }, agent: false
    }, (incoming) => {
      response = incoming;
      result.ttfb_ms = performance.now() - start;
      result.status = incoming.statusCode;
      result.content_encoding = incoming.headers['content-encoding'] ?? 'identity';
      result.server_timing = incoming.headers['server-timing'] ?? null;
      const decoders = { gzip: createGunzip, deflate: createInflate, br: createBrotliDecompress };
      const factory = decoders[result.content_encoding];
      if (!factory && result.content_encoding !== 'identity') {
        finish(new Error(`Unsupported content encoding: ${result.content_encoding}`)); return;
      }
      decoder = factory?.();
      incoming.on('data', (chunk) => {
        result.encoded_body_bytes += chunk.length;
        if (result.encoded_body_bytes > maxBytes) finish(new Error('Encoded response byte limit exceeded'));
      });
      incoming.on('error', finish);
      incoming.on('aborted', () => finish(new Error('Response aborted')));
      const decoded = decoder ? incoming.pipe(decoder) : incoming;
      decoded.on('data', (chunk) => {
        result.decoded_body_bytes += chunk.length;
        if (result.decoded_body_bytes > maxBytes) finish(new Error('Decoded response byte limit exceeded'));
      });
      decoded.on('error', finish);
      decoded.on('end', () => finish());
    });
    request.on('error', finish);
    const timer = setTimeout(() => finish(new Error(`Request exceeded ${timeoutMs}ms`)), timeoutMs);
  });
}

export async function trackNetwork(context, page, mobile) {
  const cdp = await context.newCDPSession(page);
  await cdp.send('Network.enable');
  await cdp.send('Network.setCacheDisabled', { cacheDisabled: true });
  await cdp.send('Performance.enable');
  await cdp.send('Emulation.setCPUThrottlingRate', { rate: mobile ? 4 : 1 });
  if (mobile) await cdp.send('Network.emulateNetworkConditions', {
    offline: false, latency: 100, downloadThroughput: 10_000_000 / 8, uploadThroughput: 1_000_000 / 8
  });
  const rows = new Map();
  cdp.on('Network.requestWillBeSent', ({ requestId, request }) => {
    rows.set(requestId, { url: request.url, category: new URL(request.url).pathname.startsWith('/api/') ? 'application_data' : 'application_assets', complete: false, failed: false });
  });
  cdp.on('Network.responseReceived', ({ requestId, type, response }) => {
    const url = new URL(response.url);
    rows.set(requestId, {
      url: response.url, type, status: response.status,
      category: url.pathname.startsWith('/api/') ? 'application_data' :
        /glyph|sprite|\.pbf|tiles\//.test(url.pathname) ? 'basemap_glyph_sprite' : 'application_assets',
      from_cache: !!(response.fromDiskCache || response.fromServiceWorker || response.fromPrefetchCache),
      decoded_body_bytes: 0, encoded_chunk_bytes: 0, transfer_bytes: null,
      complete: false, failed: false, server_timing: response.headers['server-timing'] ?? response.headers['Server-Timing'] ?? null
    });
  });
  cdp.on('Network.dataReceived', ({ requestId, dataLength, encodedDataLength }) => {
    const row = rows.get(requestId);
    if (row) { row.decoded_body_bytes += dataLength; row.encoded_chunk_bytes += encodedDataLength; }
  });
  cdp.on('Network.loadingFinished', ({ requestId, encodedDataLength }) => {
    const row = rows.get(requestId);
    if (row) { row.complete = true; row.transfer_bytes = encodedDataLength; }
  });
  cdp.on('Network.loadingFailed', ({ requestId, errorText }) => {
    const row = rows.get(requestId) ?? { request_id: requestId };
    Object.assign(row, { failed: true, complete: false, error: errorText }); rows.set(requestId, row);
  });
  return { rows, cdp };
}
