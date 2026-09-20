import assert from 'node:assert/strict';
import { createServer } from 'node:http';
import { EventEmitter } from 'node:events';
import { gzipSync } from 'node:zlib';
import test from 'node:test';
import { applyCompletedRequestSizes, sampleHttp, summary, trackNetwork } from './metrics.mjs';

test('flush waits for delayed worker sizes before the caller snapshots network evidence', async () => {
  const cdp = new EventEmitter();
  cdp.send = async () => {};
  const page = new EventEmitter();
  const network = await trackNetwork({ newCDPSession: async () => cdp }, page, false);
  const url = 'http://web/assets/maplibre-gl-worker.js';
  cdp.emit('Network.requestWillBeSent', { requestId: 'worker', request: { url } });
  let release;
  const delayed = new Promise((resolve) => { release = resolve; });
  page.emit('requestfinished', {
    url: () => url, response: async () => ({ status: () => 200 }), sizes: () => delayed
  });
  let flushed = false;
  const flushing = network.flush().then(() => { flushed = true; });
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(flushed, false);
  release({ responseBodySize: 500, responseHeadersSize: 20 });
  await flushing;
  assert.equal(network.rows.get('worker').transfer_bytes, 520);
  assert.equal(network.rows.get('worker').complete, true);
});

test('summarizes empty, odd, and even timing samples with a conventional median', () => {
  assert.deepEqual(summary([]), {
    count: 0, samples_ms: [], median_ms: null, approx_p95_ms: null
  });
  assert.equal(summary([9, 1, 5]).median_ms, 5);
  assert.equal(summary([8, 2, 6, 4]).median_ms, 5);
});

test('fills an incomplete worker request from completed Playwright request sizes', async () => {
  const rows = new Map([['cdp-worker', {
    url: 'http://web/assets/maplibre-gl-worker.js', category: 'application_assets',
    decoded_body_bytes: null, encoded_chunk_bytes: null, transfer_bytes: null,
    complete: false, failed: false
  }]]);
  const request = {
    url: () => 'http://web/assets/maplibre-gl-worker.js',
    response: async () => ({ status: () => 200 }),
    sizes: async () => ({ responseBodySize: 509_455, responseHeadersSize: 224 })
  };
  assert.equal(await applyCompletedRequestSizes(rows, request), true);
  assert.equal(rows.size, 1);
  assert.deepEqual(rows.get('cdp-worker'), {
    url: 'http://web/assets/maplibre-gl-worker.js', category: 'application_assets', type: 'Worker', status: 200,
    decoded_body_bytes: null, encoded_chunk_bytes: null, encoded_body_bytes: 509_455, transfer_bytes: 509_679,
    reported_encoded_body_bytes: 509_455, size_unavailable_reason: null,
    response_headers_bytes: 224, transfer_source: 'playwright.request.sizes.responseBodySize+responseHeadersSize', complete: true, failed: false
  });
});

test('does not claim zero worker transfer when Chromium omits its body counter', async () => {
  const row = { url: 'http://web/assets/maplibre-gl-worker.js', complete: false };
  const rows = new Map([['worker', row]]);
  await applyCompletedRequestSizes(rows, {
    url: () => row.url, response: async () => ({ status: () => 200 }),
    sizes: async () => ({ responseBodySize: 0, responseHeadersSize: 256 })
  });
  assert.equal(row.complete, true);
  assert.equal(row.reported_encoded_body_bytes, 0);
  assert.equal(row.encoded_body_bytes, null);
  assert.equal(row.transfer_bytes, null);
  assert.equal(row.size_unavailable_reason, 'worker_body_counter_unavailable');
});

test('leaves an incomplete row untouched when completed request sizes fail', async () => {
  const row = { url: 'http://web/assets/maplibre-gl-worker.js', complete: false, failed: false };
  const rows = new Map([['cdp-worker', row]]);
  const request = {
    url: () => row.url,
    response: async () => ({ status: () => 200 }),
    sizes: async () => { throw new Error('sizes unavailable'); }
  };
  assert.equal(await applyCompletedRequestSizes(rows, request), false);
  assert.equal(rows.get('cdp-worker'), row);
  assert.equal(row.complete, false);
});

test('does not overwrite a request already completed by CDP', async () => {
  const row = { url: 'http://web/assets/maplibre-gl-worker.js', complete: true, failed: false, transfer_bytes: 77 };
  const rows = new Map([['cdp-worker', row]]);
  const request = {
    url: () => row.url,
    response: async () => ({ status: () => 200 }),
    sizes: async () => ({ responseBodySize: 509_455, responseHeadersSize: 224 })
  };
  assert.equal(await applyCompletedRequestSizes(rows, request), false);
  assert.equal(rows.size, 1);
  assert.equal(rows.get('cdp-worker'), row);
});

test('preserves a CDP completion racing request sizes and ignores non-worker requests', async () => {
  const worker = { url: 'http://web/assets/maplibre-gl-worker.js', complete: false, failed: false };
  const rows = new Map([['cdp-worker', worker]]);
  const request = {
    url: () => worker.url,
    response: async () => ({ status: () => 200 }),
    sizes: async () => {
      worker.complete = true;
      worker.transfer_bytes = 88;
      return { responseBodySize: 509_455, responseHeadersSize: 224 };
    }
  };
  assert.equal(await applyCompletedRequestSizes(rows, request), false);
  assert.deepEqual(worker, { url: request.url(), complete: true, failed: false, transfer_bytes: 88 });
  const other = { url: 'http://web/assets/main.js', complete: false, failed: false };
  assert.equal(await applyCompletedRequestSizes(new Map([['cdp-main', other]]), {
    ...request, url: () => other.url
  }), false);
});

test('counts chunked compressed body bytes independently of Content-Length', async () => {
  const body = Buffer.from('actual body '.repeat(2000));
  const compressed = gzipSync(body);
  const server = createServer((request, response) => {
    response.writeHead(200, { 'Content-Encoding': 'gzip', 'Server-Timing': 'db;dur=1' });
    response.write(compressed.subarray(0, 20)); response.end(compressed.subarray(20));
  });
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
  try {
    const result = await sampleHttp(`http://127.0.0.1:${server.address().port}`);
    assert.equal(result.ok, true);
    assert.equal(result.encoded_body_bytes, compressed.length);
    assert.equal(result.decoded_body_bytes, body.length);
    assert.equal(result.server_timing, 'db;dur=1');
    assert.ok(result.duration_ms >= result.ttfb_ms);
  } finally { await new Promise((resolve) => server.close(resolve)); }
});

test('fails bounded hung responses without inventing successful latency', async () => {
  const server = createServer((request, response) => { response.writeHead(200); response.write('partial'); });
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
  try {
    const result = await sampleHttp(`http://127.0.0.1:${server.address().port}`, { timeoutMs: 50 });
    assert.equal(result.ok, false); assert.match(result.error, /exceeded/);
    assert.equal(result.decoded_body_bytes, 7);
  } finally { server.closeAllConnections(); await new Promise((resolve) => server.close(resolve)); }
});
