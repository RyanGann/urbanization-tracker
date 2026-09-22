import { readFile, writeFile } from 'node:fs/promises';
import { join } from 'node:path';
import os from 'node:os';
import { prepareSnapshot } from './snapshot.mjs';

export async function preparePerformance({ options, root, artifactDir, run, log }) {
  const fixturePath = join(artifactDir, 'fixture.json');
  const profile = ['functional', 'catalog-development'].includes(options.scenario) ? 'A' : 'B';
  if (options.snapshotDir) await prepareSnapshot(root, options.snapshotDir, fixturePath);
  else await run(process.execPath, [join(root, 'scripts/performance/generate-fixture.mjs'), '--profile', profile, '--output', fixturePath], { log, timeoutMs: 600_000 });
  const manifest = JSON.parse(await readFile(`${fixturePath}.manifest.json`, 'utf8'));
  const override = join(artifactDir, 'performance.compose.yml');
  // Fixture creation/validation is outside the measured API limit. Apply that
  // limit only after the seed exits; the measured DB is constrained throughout.
  await writeFile(override, 'services:\n  db:\n    cpus: 2\n    mem_limit: 2g\n');
  return { fixturePath, manifest, override };
}

export async function enableMeasurementLimits(performance) {
  await writeFile(performance.override, 'services:\n  db:\n    cpus: 2\n    mem_limit: 2g\n  api:\n    cpus: 1\n    mem_limit: 1g\n');
}

export async function captureDatabase({ compose, run, log, artifactDir }) {
  const queries = {
    database: "SELECT json_build_object('database_bytes', pg_database_size(current_database()), 'postgres_version', version(), 'postgis_version', PostGIS_Version());",
    collections: "SELECT COALESCE(json_agg(row_to_json(t)), '[]') FROM (SELECT collection_name, count(*) AS rows FROM processed_collection_items GROUP BY collection_name ORDER BY collection_name) t;",
    development_plan: "EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) SELECT * FROM processed_collection_items WHERE collection_name = 'development_records' ORDER BY sort_order, id;",
    overlay_plan: "EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) SELECT * FROM processed_collection_items WHERE collection_name = 'environmental_overlays' ORDER BY sort_order, id;"
  };
  const result = { note: 'Legacy JSON collection reads. Plans exclude network transfer, JSON decoding and Python serialization.' };
  for (const [name, sql] of Object.entries(queries)) {
    const output = await run('docker', [...compose, 'exec', '-T', 'db', 'psql', '-U', 'integration', '-d', 'integration', '-Atqc', sql], { log });
    result[name] = JSON.parse(output.output);
  }
  await writeFile(join(artifactDir, 'database.json'), JSON.stringify(result, null, 2) + '\n');
}

export async function startResourceSampling({ compose, run, log, artifactDir }) {
  const ids = {};
  for (const service of ['api', 'db']) {
    ids[service] = (await run('docker', [...compose, 'ps', '-q', service], { log })).output.trim();
    if (!ids[service]) throw new Error(`could not resolve container id for ${service} before resource sampling`);
  }
  const samples = [];
  const matchesContainer = (row, id) => Boolean(id) && [row?.ID, row?.Container].some((value) => typeof value === 'string'
    && value.length > 0 && (value.startsWith(id) || id.startsWith(value)));
  let stopped = false, wake;
  const task = (async () => {
    while (!stopped) {
      const result = await run('docker', ['stats', '--no-stream', '--format', '{{json .}}', ...Object.values(ids)], { allowFailure: true, timeoutMs: 15_000, ignoreInterrupt: true });
      const rows = result.output.trim().split(/\r?\n/).filter(Boolean).map((line) => {
        try { return JSON.parse(line); } catch { return { error: line }; }
      });
      const measuredServices = Object.entries(ids)
        .filter(([, id]) => rows.some((row) => matchesContainer(row, id) && typeof row.MemUsage === 'string' && typeof row.CPUPerc === 'string'))
        .map(([service]) => service);
      samples.push({
        at: new Date().toISOString(),
        code: result.code,
        ok: result.code === 0 && rows.length > 0 && measuredServices.length === Object.keys(ids).length,
        measured_services: measuredServices,
        rows
      });
      await writeFile(join(artifactDir, 'resources.partial.json'), JSON.stringify(samples, null, 2) + '\n');
      if (!stopped) await new Promise((resolve) => { wake = resolve; const timer = setTimeout(resolve, 5000); wake = () => { clearTimeout(timer); resolve(); }; });
    }
  })().catch((error) => samples.push({ error: error.message }));
  return async () => {
    stopped = true; wake?.(); await task;
    const containers = {};
    for (const [service, id] of Object.entries(ids)) {
      const state = await run('docker', ['inspect', '--format', '{{json .State}}', id], { allowFailure: true, ignoreInterrupt: true });
      const config = await run('docker', ['inspect', '--format', '{{json .HostConfig}}', id], { allowFailure: true, ignoreInterrupt: true });
      const peak = await run('docker', ['exec', id, 'cat', '/sys/fs/cgroup/memory.peak'], { allowFailure: true, ignoreInterrupt: true });
      let hostConfig = {}; try { hostConfig = JSON.parse(config.output); } catch {}
      containers[service] = { id, state: state.code === 0 ? JSON.parse(state.output) : null,
        cgroup_memory_peak_bytes: peak.code === 0 && /^\d+\s*$/.test(peak.output) ? Number(peak.output.trim()) : null,
        memory_limit_bytes: hostConfig.Memory ?? null, memory_swap_limit_bytes: hostConfig.MemorySwap ?? null, nano_cpus: hostConfig.NanoCpus ?? null };
    }
    const docker = await run('docker', ['info', '--format', '{{json .}}'], { allowFailure: true, ignoreInterrupt: true });
    let dockerInfo = {}; try { dockerInfo = JSON.parse(docker.output); } catch {}
    const background = await run('docker', ['ps', '--format', '{{json .Names}}'], { allowFailure: true, ignoreInterrupt: true });
    await writeFile(join(artifactDir, 'resources.json'), JSON.stringify({
      host: { platform: os.platform(), release: os.release(), cpu: os.cpus()[0]?.model, logical_cpus: os.cpus().length, ram_bytes: os.totalmem() },
      docker: { cpus: dockerInfo.NCPU ?? null, ram_bytes: dockerInfo.MemTotal ?? null, version: dockerInfo.ServerVersion ?? null },
      running_container_names: background.output.trim().split(/\r?\n/), containers, samples,
      successful_stats_samples: samples.filter((sample) => sample.ok).length,
      note: 'Docker stats are sampled, not exact peaks. cgroup memory.peak is a container-lifetime peak including warmup. Unavailable peaks stay null.'
    }, null, 2) + '\n');
    if (!samples.some((sample) => sample.ok)) {
      throw new Error('docker stats produced no successful nonempty sample for measured api and db containers');
    }
  };
}
