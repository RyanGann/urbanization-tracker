import assert from 'node:assert/strict';
import { createServer } from 'node:http';
import { gzipSync } from 'node:zlib';
import test from 'node:test';
import { sampleHttp, summary } from './metrics.mjs';

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
  assert.equal(summary([]).approx_p95_ms, null);
});
