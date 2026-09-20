import { mkdir, readFile, writeFile, rename } from 'node:fs/promises';
import { dirname, join } from 'node:path';
import { chromium } from 'playwright';
import { sampleHttp, summary, trackNetwork } from './performance/metrics.mjs';

const profile = process.env.P01_PERFORMANCE_PROFILE || 'desktop';
if (!['desktop', 'mobile'].includes(profile)) throw new Error('Unsupported performance profile');
const mobile = profile === 'mobile';
const smoke = process.env.P01_SMOKE === 'true';
const baseUrl = process.env.LIVE_WEB_BASE_URL || 'http://web';
const apiUrl = process.env.P01_API_INTERNAL_URL || 'http://api:8000';
const output = process.env.P01_OUTPUT || '/artifacts/performance/browser.json';
const fixture = JSON.parse(await readFile(process.env.P01_FIXTURE_MANIFEST || '/artifacts/fixture.json.manifest.json', 'utf8'));
const expected = fixture.expected;
const record = expected.first_development;
const overlay = fixture.overlay_probes[0];
const counts = { cold: smoke ? 2 : 10, interaction: smoke ? 2 : 20, api: smoke ? 2 : 100 };
const report = {
  schema_version: 1, purpose: smoke ? 'functional_smoke' : 'baseline', profile,
  fixture_sha256: fixture.sha256, fixture_profile: fixture.profile,
  settings: { viewport: mobile ? { width: 390, height: 844 } : { width: 1440, height: 900 },
    cpu_throttle: mobile ? 4 : 1, download_bps: mobile ? 10_000_000 : null,
    upload_bps: mobile ? 1_000_000 : null, latency_ms: mobile ? 100 : 0,
    cache: 'Fresh browser contexts, HTTP cache disabled; database warmed by seeding and API verification', counts },
  definitions: {
    first_useful_ms: 'Navigation start to parsed records + committed list + known rendered selectable feature visible without scrolling',
    context_ready_ms: 'Navigation start to known enabled environmental feature rendered and visible without scrolling',
    api_encoded_body_bytes: 'Actual streamed body bytes before decompression, excluding HTTP headers/framing',
    browser_transfer_bytes: 'CDP loadingFinished encodedDataLength; includes protocol transfer overhead, separate from body metrics',
    catalog: 'Not implemented; current endpoint returns full geometry', tiles: 'Not implemented',
    approx_p95: 'Nearest-rank estimate; cold browser sample count is small',
    fail_fast: 'Two failed cold loads or two failed API requests stop that scenario; unrun samples remain explicit'
  },
  catalog_ready_ms: null, tile_bytes: null, cold: [], interactions: [], api: [], errors: [], complete: false
};
await mkdir(dirname(output), { recursive: true });
let pendingCheckpoint = Promise.resolve();
function checkpoint() {
  report.cold_unrun = counts.cold - report.cold.length;
  report.interactions_unrun = counts.interaction - report.interactions.length;
  for (const scenario of report.api) {
    scenario.completed = scenario.samples.filter(Boolean).length;
    scenario.unrun = scenario.requested - scenario.completed;
  }
  const serialized = `${JSON.stringify(report, null, 2)}\n`;
  pendingCheckpoint = pendingCheckpoint.then(async () => {
    await writeFile(`${output}.pending`, serialized);
    await rename(`${output}.pending`, output);
  });
  return pendingCheckpoint;
}
async function probe(page, coordinate, layers) {
  if (page.__p01Errors?.length) throw new Error(page.__p01Errors.join("; "));
  return page.evaluate(({ coordinate, layers }) => window.__urbanizationPerformance?.probe(coordinate, layers) ?? null, { coordinate, layers });
}
async function until(check, description, timeout = 30_000) {
  const deadline = Date.now() + timeout;
  while (Date.now() < deadline) {
    const value = await check(); if (value) return value;
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  throw new Error(`Timed out: ${description}`);
}
const developmentLayers = ['development-points', 'development-polygons-fill'];
const overlayLayers = [`env-${overlay.overlay_id}-fill`, `env-${overlay.overlay_id}-line`];
async function renderedDevelopment(page, requireVisible = false) {
  return until(async () => {
    const state = await probe(page, record.centroid, developmentLayers);
    return state && !state.moving && (!requireVisible || state.visible) && state.features.some((f) => f.public_id === record.public_id) ? state : null;
  }, 'known development feature rendered', 180_000);
}
async function physicalSelect(page) {
  const state = await renderedDevelopment(page, true);
  await page.mouse.click(state.point.x, state.point.y);
  await page.locator('.maplibregl-popup').filter({ hasText: record.title }).waitFor();
  await page.locator('.selected-record h1').filter({ hasText: record.title }).waitFor();
}
async function mapInView(page) {
  await page.locator('.maplibregl-canvas').scrollIntoViewIfNeeded();
  await renderedDevelopment(page, true);
}
async function newPage(browser) {
  const context = await browser.newContext({ viewport: report.settings.viewport, isMobile: mobile, deviceScaleFactor: 1 });
  const page = await context.newPage();
  page.setDefaultTimeout(30_000);
  await page.addInitScript(() => {
    window.__p01LongTasks = [];
    new PerformanceObserver((list) => window.__p01LongTasks.push(...list.getEntries().map(({ startTime, duration }) => ({ startTime, duration })))).observe({ type: 'longtask', buffered: true });
  });
  const network = await trackNetwork(context, page, mobile);
  const errors = [];
  page.__p01Errors = errors;
  page.on('pageerror', (error) => errors.push(error.message));
  page.on('requestfailed', (request) => errors.push(`${request.url()}: ${request.failure()?.errorText}`));
  page.on('response', (response) => {
    if (new URL(response.url()).pathname.startsWith('/api/') && response.status() >= 400) errors.push(`API ${response.status()}: ${response.url()}`);
  });
  return { context, page, network, errors };
}
async function coldLoad(browser, index) {
  const { context, page, network, errors } = await newPage(browser);
  const result = { index, ok: false, first_useful_ms: null, context_ready_ms: null, scroll_required: null };
  try {
    await page.goto(baseUrl, { waitUntil: 'domcontentloaded', timeout: 180_000 });
    await until(async () => {
      if (errors.length) throw new Error(errors.join('; '));
      return await page.locator('button.record-row').filter({ hasText: record.title }).count() > 0;
    }, 'known record list row', 180_000);
    const dev = await renderedDevelopment(page);
    const env = await until(async () => {
      const state = await probe(page, overlay.coordinate, overlayLayers);
      return state && state.features.some((f) => String(f.id) === String(overlay.feature_id)) ? state : null;
    }, 'known enabled overlay rendered', 180_000);
    const marks = await page.evaluate(() => Object.fromEntries(performance.getEntriesByType('mark').map((mark) => [mark.name, mark.startTime])));
    for (const required of ['p01:records-received', 'p01:list-ready', 'p01:overlays-received', 'p01:map-loaded']) {
      if (!Number.isFinite(marks[required])) throw new Error(`Missing required mark: ${required}`);
    }
    Object.assign(result, {
      marks, feature_rendered_ms: dev.time, overlay_rendered_ms: env.time,
      first_useful_ms: dev.visible ? Math.max(dev.time, marks['p01:list-ready'], marks['p01:records-received']) : null,
      context_ready_ms: env.visible ? env.time : null,
      scroll_required: !dev.visible || !env.visible, initial_development: dev, initial_overlay: env,
      network: [...network.rows.values()], long_tasks: await page.evaluate(() => window.__p01LongTasks),
      metrics: (await network.cdp.send('Performance.getMetrics')).metrics
    });
    // Functional interaction after timing ends. Scrolling cannot masquerade as initial readiness.
    if (index === 0) await page.screenshot({ path: join(dirname(output), `${profile}-initial.png`) });
    await mapInView(page);
    await physicalSelect(page);
    if (index === 0) await page.screenshot({ path: join(dirname(output), `${profile}-selected.png`) });
    if (errors.length) throw new Error(errors.join('; '));
    if (result.network.some((row) => row.category === 'application_data' && (!row.complete || row.failed || row.status >= 400))) throw new Error('Application request failed or remained incomplete');
    result.functional_interaction_pass = true;
    if (result.scroll_required) throw new Error("Initial map context is outside the viewport; scrolling required");
    result.ok = true;
  } catch (error) {
    result.error = error.message;
    result.network ??= [...network.rows.values()];
    await page.screenshot({ path: join(dirname(output), `${profile}-failure-${index}.png`), timeout: 5000 }).catch(() => {});
  } finally { result.page_errors = errors; await context.close(); }
  return result;
}
async function warmInteractions(browser) {
  const { context, page, network, errors } = await newPage(browser);
  try {
    await page.goto(baseUrl, { waitUntil: 'domcontentloaded', timeout: 180_000 });
    await renderedDevelopment(page);
    let previousRequestCount = network.rows.size;
    let previousLongTaskCount = 0;
    for (let index = 0; index < counts.interaction; index++) {
      const sample = { index, ok: false, actions_ms: {} };
      const measure = async (name, action) => { const start = performance.now(); await action(); sample.actions_ms[name] = performance.now() - start; };
      try {
        await measure('selection', async () => {
          await page.locator('button.record-row').filter({ hasText: record.title }).click();
          await mapInView(page); await physicalSelect(page);
        });
        await measure('pan', async () => {
          const before = await probe(page, record.centroid, developmentLayers);
          const box = await page.locator('.maplibregl-canvas').boundingBox();
          const x = box.x + box.width / 2, y = box.y + box.height / 2;
          await page.mouse.move(x, y); await page.mouse.down(); await page.mouse.move(x + 40, y + 25, { steps: 8 }); await page.mouse.up();
          await until(async () => { const state = await probe(page, record.centroid, developmentLayers); return !state.moving && Math.abs(state.center[0] - before.center[0]) > .00001; }, 'pan changes camera');
        });
        await measure('zoom', async () => {
          const before = await probe(page, record.centroid, developmentLayers);
          await page.getByRole('button', { name: 'Zoom in', exact: true }).click();
          await until(async () => { const state = await probe(page, record.centroid, developmentLayers); return !state.moving && state.zoom > before.zoom + .1; }, 'zoom changes camera');
          await page.getByRole('button', { name: 'Zoom out', exact: true }).click();
          await until(async () => !(await probe(page, record.centroid, developmentLayers)).moving, 'zoom settles');
        });
        await measure('filter', async () => {
          const before = await page.locator('button.record-row').count();
          const filter = page.locator('.control-group').first().getByRole('checkbox').first();
          await filter.uncheck();
          await until(async () => await page.locator('button.record-row').count() < before, 'filter updates results');
          await filter.check();
          await until(async () => await page.locator('button.record-row').count() === before, 'filter restores results');
        });
        await measure('overlay_toggle', async () => {
          const toggle = page.getByRole('checkbox', { name: overlay.overlay_name, exact: true });
          await toggle.uncheck();
          await until(async () => (await probe(page, overlay.coordinate, overlayLayers)).visibility.filter((v) => v === 'none').length === overlayLayers.length, 'overlay disabled');
          await toggle.check();
          await until(async () => (await probe(page, overlay.coordinate, overlayLayers)).visibility.filter((v) => v === 'visible').length === overlayLayers.length, 'overlay enabled');
        });
        const longTasks = await page.evaluate(() => window.__p01LongTasks);
        sample.long_tasks = longTasks.slice(previousLongTaskCount);
        previousLongTaskCount = longTasks.length;
        sample.new_request_count = network.rows.size - previousRequestCount;
        previousRequestCount = network.rows.size;
        sample.metrics = (await network.cdp.send('Performance.getMetrics')).metrics;
        sample.page_errors = [...errors];
        if (errors.length) throw new Error(errors.join('; '));
        sample.ok = true;
      } catch (error) { sample.error = error.message; }
      report.interactions.push(sample); await checkpoint();
      if (!sample.ok) break;
    }
  } finally { await context.close(); }
}
async function apiScenario(endpoint, concurrency) {
  const result = { endpoint, concurrency, requested: counts.api, samples: [] };
  report.api.push(result);
  let cursor = 0, failures = 0;
  await Promise.all(Array.from({ length: Math.min(concurrency, counts.api) }, async () => {
    while (cursor < counts.api && failures < 2) {
      const index = cursor++;
      const sample = await sampleHttp(`${apiUrl}${endpoint}`);
      result.samples[index] = sample;
      if (!sample.ok) failures++;
      await checkpoint();
    }
  }));
  result.completed = result.samples.length;
  result.unrun = counts.api - result.completed;
  result.failures = failures;
  result.timings = summary(result.samples.filter((sample) => sample.ok).map((sample) => sample.duration_ms));
  await checkpoint();
}
let browser;
try {
  await checkpoint();
  browser = await chromium.launch({ headless: true });
  report.browser = browser.version();
  for (let index = 0; index < counts.cold; index++) {
    report.cold.push(await coldLoad(browser, index)); await checkpoint();
    if (report.cold.filter((sample) => !sample.ok).length >= 2) break;
  }
  if (report.cold.some((sample) => sample.functional_interaction_pass)) await warmInteractions(browser);
  for (const endpoint of ['/api/development-records', '/api/environmental-overlays']) {
    for (const concurrency of [1, 5]) await apiScenario(endpoint, concurrency);
  }
  report.complete = report.cold.length === counts.cold && report.interactions.length === counts.interaction && report.api.every((scenario) => scenario.unrun === 0);
} catch (error) { report.errors.push(error.message); }
finally {
  await browser?.close();
  report.cold_unrun = counts.cold - report.cold.length;
  report.interactions_unrun = counts.interaction - report.interactions.length;
  report.first_useful = summary(report.cold.filter((sample) => sample.ok).map((sample) => sample.first_useful_ms));
  report.transfer = report.cold.map((sample) => ({
    index: sample.index,
    categories: Object.fromEntries(['application_data', 'application_assets', 'basemap_glyph_sprite'].map((category) => {
      const rows = (sample.network ?? []).filter((row) => row.category === category);
      return [category, { requests: rows.length, completed: rows.filter((row) => row.complete).length,
        failed: rows.filter((row) => row.failed || row.status >= 400).length,
        decoded_body_bytes: rows.reduce((sum, row) => sum + (row.decoded_body_bytes ?? 0), 0),
        transfer_bytes: rows.every((row) => Number.isFinite(row.transfer_bytes)) ? rows.reduce((sum, row) => sum + row.transfer_bytes, 0) : null }];
    }))
  }));
  report.context_ready = summary(report.cold.filter((sample) => sample.ok).map((sample) => sample.context_ready_ms));
  report.functional_pass = report.complete && !report.errors.length && report.cold.every((sample) => sample.ok) && report.interactions.every((sample) => sample.ok) && report.api.every((scenario) => scenario.failures === 0);
  await checkpoint();
  if (!report.functional_pass) process.exitCode = 1;
}
