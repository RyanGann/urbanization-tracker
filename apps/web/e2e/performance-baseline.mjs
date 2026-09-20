import { mkdir, writeFile } from "node:fs/promises";
import { dirname } from "node:path";
import { chromium } from "playwright";

const profile = process.env.P01_PERFORMANCE_PROFILE ?? "desktop";
const baseUrl = process.env.LIVE_WEB_BASE_URL ?? "http://web";
const apiUrl = process.env.P01_API_INTERNAL_URL ?? "http://api:8000";
const outputPath = process.env.P01_OUTPUT ?? "/artifacts/performance/browser.json";
const scenario = process.env.P01_PERFORMANCE_SCENARIO ?? "functional";
const coldCount = Number(process.env.P01_COLD_CONTEXTS ?? 10);
const interactionCount = Number(process.env.P01_INTERACTION_CYCLES ?? 20);
const apiRequestCount = Number(process.env.P01_API_REQUESTS ?? 100);

const profileSettings = profile === "mobile"
  ? { viewport: { width: 390, height: 844 }, mobile: true }
  : { viewport: { width: 1440, height: 900 }, mobile: false };

function percentile(values, fraction) {
  const sorted = [...values].sort((left, right) => left - right);
  if (!sorted.length) return null;
  const index = Math.min(sorted.length - 1, Math.ceil(sorted.length * fraction) - 1);
  return sorted[index];
}

function summarize(values) {
  return {
    count: values.length,
    samples_ms: values,
    median_ms: percentile(values, 0.5),
    approx_p95_ms: percentile(values, 0.95)
  };
}

async function apiSamples(path, count, concurrency) {
  const samples = [];
  let cursor = 0;
  async function worker() {
    while (true) {
      const index = cursor++;
      if (index >= count) return;
      const started = performance.now();
      try {
        const response = await fetch(`${apiUrl}${path}`, { signal: AbortSignal.timeout(120_000) });
        const encodedHeader = Number(response.headers.get("content-length"));
        const body = await response.arrayBuffer();
        samples[index] = {
          ok: response.ok,
          status: response.status,
          encoded_bytes: Number.isFinite(encodedHeader) ? encodedHeader : null,
          decoded_bytes: body.byteLength,
          duration_ms: Number((performance.now() - started).toFixed(2))
        };
      } catch (error) {
        samples[index] = {
          ok: false,
          status: null,
          encoded_bytes: null,
          decoded_bytes: null,
          duration_ms: null,
          error: error instanceof Error ? error.message : String(error)
        };
      }
    }
  }
  await Promise.all(Array.from({ length: Math.min(concurrency, count) }, worker));
  const successful = samples.filter((sample) => sample?.ok && sample.duration_ms !== null);
  return {
    endpoint: path,
    concurrency,
    requested: count,
    completed: samples.filter(Boolean).length,
    failures: samples.filter((sample) => !sample?.ok).length,
    durations: summarize(successful.map((sample) => sample.duration_ms)),
    encoded_bytes: successful.map((sample) => sample.encoded_bytes),
    decoded_bytes: successful.map((sample) => sample.decoded_bytes),
    raw: samples
  };
}

async function setupNetwork(page, context) {
  const cdp = await context.newCDPSession(page);
  await cdp.send("Network.enable");
  await cdp.send("Performance.enable");
  await cdp.send("Emulation.setCPUThrottlingRate", { rate: profileSettings.mobile ? 4 : 1 });
  if (profileSettings.mobile) {
    await cdp.send("Network.emulateNetworkConditions", {
      offline: false,
      latency: 100,
      downloadThroughput: Math.floor((10 * 1024 * 1024) / 8),
      uploadThroughput: Math.floor((1 * 1024 * 1024) / 8)
    });
  }
  const requests = new Map();
  const responseInfo = new Map();
  const onResponse = (event) => {
    responseInfo.set(event.requestId, {
      url: event.response.url,
      status: event.response.status,
      mime_type: event.response.mimeType,
      encoded_bytes: 0,
      decoded_bytes: 0
    });
  };
  const onData = (event) => {
    const response = responseInfo.get(event.requestId);
    if (!response) return;
    response.encoded_bytes += event.encodedDataLength ?? 0;
    response.decoded_bytes += event.dataLength ?? 0;
  };
  cdp.on("Network.responseReceived", onResponse);
  cdp.on("Network.dataReceived", onData);
  return {
    responseInfo,
    stop: async () => {
      cdp.off("Network.responseReceived", onResponse);
      cdp.off("Network.dataReceived", onData);
      await cdp.detach();
    }
  };
}

async function waitForMark(page, name, timeout = 30_000) {
  try {
    await page.waitForFunction(
      (markName) => performance.getEntriesByName(markName, "mark").length > 0,
      `p01:${name}`,
      { timeout }
    );
    return await page.evaluate((markName) => performance.getEntriesByName(markName, "mark").at(-1)?.startTime ?? null, `p01:${name}`);
  } catch {
    return null;
  }
}

async function physicalSelect(page) {
  await page.locator("button.record-row").first().click();
  await page.waitForTimeout(700);
  const canvas = page.locator(".maplibregl-canvas");
  const box = await canvas.boundingBox();
  if (!box) throw new Error("P01 functional precheck: map canvas has no bounding box");
  for (let attempt = 0; attempt < 5; attempt += 1) {
    await canvas.click({ position: { x: box.width / 2, y: box.height / 2 }, force: true });
    if (await page.locator(".maplibregl-popup").count()) return;
    await page.waitForTimeout(200);
  }
  throw new Error("P01 functional precheck: physical canvas click did not open a popup");
}

async function browserLoad(browser, index) {
  const context = await browser.newContext({
    viewport: profileSettings.viewport,
    isMobile: profileSettings.mobile,
    deviceScaleFactor: profileSettings.mobile ? 1 : 1
  });
  const page = await context.newPage();
  await page.addInitScript(() => {
    window.__p01LongTasks = [];
    new PerformanceObserver((list) => {
      window.__p01LongTasks.push(...list.getEntries().map((entry) => ({ startTime: entry.startTime, duration: entry.duration })));
    }).observe({ type: "longtask", buffered: true });
  });
  const network = await setupNetwork(page, context);
  const started = performance.now();
  let error = null;
  try {
    await page.goto(`${baseUrl}/`, { waitUntil: "domcontentloaded", timeout: 120_000 });
    await page.locator("button.record-row").first().waitFor({ timeout: 120_000 });
    const listReady = await waitForMark(page, "list-ready", 120_000);
    const recordsReceived = await waitForMark(page, "records-received", 120_000);
    const featureRendered = await waitForMark(page, "feature-rendered", 120_000);
    const overlayRendered = await waitForMark(page, "overlay-rendered", 120_000);
    await physicalSelect(page);
    const popupTitle = await page.locator(".maplibregl-popup").innerText();
    for (let cycle = 0; cycle < interactionCount; cycle += 1) {
      await page.mouse.wheel(cycle % 2 ? 0 : 20, cycle % 2 ? 20 : 0);
      await page.locator("button.record-row").nth(cycle % Math.min(10, await page.locator("button.record-row").count())).click();
      await page.waitForTimeout(35);
    }
    const marks = await page.evaluate(() => performance.getEntriesByType("mark").map((entry) => ({ name: entry.name, startTime: entry.startTime })));
    const longTasks = await page.evaluate(() => window.__p01LongTasks ?? []);
    await page.screenshot({ path: `/artifacts/performance/${profile}-functional-${index}.png`, fullPage: true });
    return {
      index,
      ok: true,
      duration_ms: Number((performance.now() - started).toFixed(2)),
      readiness_ms: { records_received: recordsReceived, list_ready: listReady, feature_rendered: featureRendered, overlay_rendered: overlayRendered },
      popup_title: popupTitle,
      marks,
      long_tasks: longTasks,
      network: [...network.responseInfo.values()]
    };
  } catch (caught) {
    error = caught instanceof Error ? caught.message : String(caught);
    return { index, ok: false, duration_ms: null, error, network: [...network.responseInfo.values()] };
  } finally {
    await network.stop();
    await context.close();
  }
}

const browser = await chromium.launch({ headless: true });
const loads = [];
for (let index = 0; index < coldCount; index += 1) loads.push(await browserLoad(browser, index));
await browser.close();

const api = {};
for (const endpoint of ["/api/development-records", "/api/environmental-overlays"]) {
  for (const concurrency of [1, 5]) {
    api[`${endpoint}:${concurrency}`] = await apiSamples(endpoint, apiRequestCount, concurrency);
  }
}

const report = {
  schema_version: 1,
  profile,
  scenario,
  base_url: baseUrl,
  api_url: apiUrl,
  cold_contexts: coldCount,
  interaction_cycles: interactionCount,
  api_request_count: apiRequestCount,
  browser: {
    loads,
    durations: summarize(loads.filter((load) => load.ok).map((load) => load.duration_ms)),
    functional_precheck: loads.every((load) => load.ok && load.popup_title),
    network_definition: "CDP Network.dataReceived encodedDataLength/dataLength; API response bodies are decoded in Node fetch samples."
  },
  api
};
await mkdir(dirname(outputPath), { recursive: true });
await writeFile(outputPath, `${JSON.stringify(report, null, 2)}\n`, "utf8");
console.log(JSON.stringify({ output: outputPath, profile, scenario, functional_precheck: report.browser.functional_precheck }, null, 2));
if (!report.browser.functional_precheck) process.exitCode = 1;
