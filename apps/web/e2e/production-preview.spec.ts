import { expect, test, type Page } from "@playwright/test";

const seedRecord = {
  public_id: "hsv-production-record",
  title: "Production Preview Subdivision",
  description: "Production preview fixture",
  development_type: "subdivision",
  status: "layout",
  source_status: "Layout",
  source_url: "https://example.test/source",
  source_agency: "City of Huntsville GIS",
  date_discovered: "2026-05-20",
  date_last_checked: "2026-05-20",
  application_date: null,
  approval_date: null,
  permit_issue_date: null,
  review_status: "published",
  confidence_level: "high",
  geometry_source: "Production preview fixture",
  geometry_confidence: "high",
  geometry: { type: "Point", coordinates: [-86.58, 34.73] },
  centroid: [-86.58, 34.73],
  area_sq_m: null,
  address: null,
  parcel_ids: [],
  source_fields: {},
  proximity_flags: []
};

const polygonRecord = {
  ...seedRecord,
  public_id: "hsv-production-polygon",
  title: "Production Preview Polygon",
  geometry: {
    type: "Polygon",
    coordinates: [[
      [-86.53, 34.70],
      [-86.51, 34.70],
      [-86.51, 34.72],
      [-86.53, 34.72],
      [-86.53, 34.70]
    ]]
  }
};
polygonRecord.centroid = [-86.52, 34.71];

async function clickCanvasCenter(page: Page) {
  const canvas = page.locator(".maplibregl-canvas");
  const box = await canvas.boundingBox();
  if (!box) throw new Error("Map canvas has no bounding box");
  for (let attempt = 0; attempt < 5; attempt += 1) {
    await canvas.click({ position: { x: box.width / 2, y: box.height / 2 }, force: true });
    if (await page.locator(".maplibregl-popup").count()) return;
    await page.waitForTimeout(200);
  }
  throw new Error("Map canvas click did not open a popup");
}

test("production preview loads the worker and selects rendered map point and polygon", async ({
  page
}, testInfo) => {
  const workerResponses: number[] = [];
  page.on("response", (response) => {
    if (response.url().includes("maplibre-gl-worker")) workerResponses.push(response.status());
  });
  await page.route("**/api/development-records**", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({ records: [seedRecord, polygonRecord] })
    });
  });
  await page.route("**/api/environmental-overlays", async (route) => {
    await route.fulfill({ contentType: "application/json", body: JSON.stringify([]) });
  });

  await page.goto("/");
  await expect(page.getByText(seedRecord.title)).toBeVisible();
  await expect(page.getByText(polygonRecord.title)).toBeVisible();
  await expect(page.locator(".maplibregl-canvas")).toBeVisible();
  await expect(page.getByTestId("development-map")).toHaveAttribute("data-feature-count", "2");
  await expect.poll(() => workerResponses, { timeout: 15_000 }).toContain(200);
  await expect(page.evaluate(() => (window as typeof window & {
    __urbanizationTrackerMap?: unknown;
  }).__urbanizationTrackerMap)).resolves.toBeUndefined();

  await page.getByRole("button", { name: /Production Preview Subdivision/ }).click();
  await page.waitForTimeout(1_250);
  await clickCanvasCenter(page);
  await expect(page.locator(".maplibregl-popup")).toContainText(seedRecord.title);
  await expect(page.getByRole("heading", { name: seedRecord.title })).toBeVisible();

  await page.locator(".maplibregl-popup-close-button").click();
  await page.getByRole("button", { name: /Production Preview Polygon/ }).click();
  await page.waitForTimeout(1_250);
  await clickCanvasCenter(page);
  await expect(page.locator(".maplibregl-popup")).toContainText(polygonRecord.title);
  await expect(page.getByRole("heading", { name: polygonRecord.title })).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath("production-map-selected.png"), fullPage: true });
});
