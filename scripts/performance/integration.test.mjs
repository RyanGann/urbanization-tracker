import assert from 'node:assert/strict';
import { mkdir, mkdtemp, readFile } from 'node:fs/promises';
import { join } from 'node:path';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';
import { startResourceSampling } from './integration.mjs';

const root = fileURLToPath(new URL('../../', import.meta.url));
await mkdir(join(root, 'tmp'), { recursive: true });

function stubRun(statsOutput, statsCode = 0) {
  return async (_command, args) => {
    if (args.includes('-q')) {
      return { code: 0, output: args.at(-1) === 'api' ? 'api-container\n' : 'db-container\n' };
    }
    if (args[0] === 'stats') return { code: statsCode, output: statsOutput };
    if (args[0] === 'inspect') {
      return { code: 0, output: args.some((arg) => arg.includes('HostConfig')) ? '{"Memory":1073741824,"NanoCpus":1000000000}' : '{}' };
    }
    if (args[0] === 'exec') return { code: 1, output: '' };
    if (args[0] === 'info') return { code: 0, output: '{"NCPU":2,"MemTotal":2147483648,"ServerVersion":"test"}' };
    if (args[0] === 'ps') return { code: 0, output: 'api\ndb\n' };
    throw new Error(`unexpected stub command: ${args.join(' ')}`);
  };
}

async function waitForSample() {
  await new Promise((resolve) => setTimeout(resolve, 20));
}

test('resource sampling writes evidence before rejecting when every stats sample fails', async () => {
  const artifactDir = await mkdtemp(join(root, 'tmp', 'p01-resource-test-fail-'));
  const stopSampling = await startResourceSampling({
    compose: ['compose', '--project-name', 'p01-test'],
    run: stubRun('docker unavailable\n', 1),
    log: [],
    artifactDir
  });
  await waitForSample();
  await assert.rejects(stopSampling(), /no successful nonempty sample/);
  const evidence = JSON.parse(await readFile(join(artifactDir, 'resources.json'), 'utf8'));
  assert.equal(evidence.successful_stats_samples, 0);
  assert.ok(Array.isArray(evidence.samples));
  assert.equal(evidence.samples[0].ok, false);
});

test('resource sampling succeeds with nonempty API and DB stats rows', async () => {
  const artifactDir = await mkdtemp(join(root, 'tmp', 'p01-resource-test-pass-'));
  const stats = [
    JSON.stringify({ ID: 'api-container', Name: 'api', CPUPerc: '1.00%', MemUsage: '80MiB / 1GiB' }),
    JSON.stringify({ ID: 'db-container', Name: 'db', CPUPerc: '2.00%', MemUsage: '100MiB / 2GiB' })
  ].join('\n') + '\n';
  const stopSampling = await startResourceSampling({
    compose: ['compose', '--project-name', 'p01-test'],
    run: stubRun(stats),
    log: [],
    artifactDir
  });
  await waitForSample();
  await stopSampling();
  const evidence = JSON.parse(await readFile(join(artifactDir, 'resources.json'), 'utf8'));
  assert.equal(evidence.successful_stats_samples, 1);
  assert.deepEqual(evidence.samples[0].measured_services, ['api', 'db']);
});
