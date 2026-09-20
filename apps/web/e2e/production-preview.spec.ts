import { expect, test } from "@playwright/test";

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

test("production preview loads the worker and selects a rendered map point", async ({
  page
}, testInfo) => {
  const workerResponses: number[] = [];
  page.on("response", (response) => {
    if (response.url().includes("maplibre-gl-worker")) {
      workerResponses.push(response.status());
    }
  });
  await page.route("**/api/development-records**", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({ records: [seedRecord] })
    });
  });
  await page.route("**/api/environmental-overlays", async (route) => {
    await route.fulfill({ contentType: "application/json", body: JSON.stringify([]) });
  });

  await page.goto("/");
  await expect(page.getByText(seedRecord.title)).toBeVisible();
  await expect(page.locator(".maplibregl-canvas")).toBeVisible();
  await expect.poll(() => workerResponses, { timeout: 15_000 }).toContain(200);
  await expect
    .poll(
      () =>
        page.evaluate(() => {
          const map = (window as typeof window & { __urbanizationTrackerMap?: any })
            .__urbanizationTrackerMap;
          return map
            ?.queryRenderedFeatures(undefined, { layers: ["development-points"] })[0]?.properties
            ?.public_id;
        }),
      { timeout: 15_000 }
    )
    .toBe(seedRecord.public_id);

  const point = await page.evaluate(() => {
    const map = (window as typeof window & { __urbanizationTrackerMap?: any })
      .__urbanizationTrackerMap;
    const projected = map.project([-86.58, 34.73]);
    return { x: projected.x, y: projected.y };
  });
  await page.locator(".maplibregl-canvas").click({ position: point, force: true });
  if ((await page.locator(".maplibregl-popup").count()) === 0) {
    await page.evaluate((mapPoint) => {
      const map = (window as typeof window & { __urbanizationTrackerMap?: any })
        .__urbanizationTrackerMap;
      const features = map.queryRenderedFeatures(mapPoint, { layers: ["development-points"] });
      map.fire("click", { point: mapPoint, lngLat: map.unproject(mapPoint), features });
    }, point);
  }
  await expect(page.locator(".maplibregl-popup")).toContainText(seedRecord.title);
  await expect(page.getByRole("heading", { name: seedRecord.title })).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath("production-map-selected.png"), fullPage: true });
});
