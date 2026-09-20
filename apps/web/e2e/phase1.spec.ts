import { expect, test, type Page } from "@playwright/test";

const seedRecord = {
  public_id: "hsv-test-record",
  title: "Seed Test Subdivision",
  description: "Playwright seed record",
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
  geometry_source: "Seed geometry",
  geometry_confidence: "high",
  geometry: {
    type: "Point",
    coordinates: [-86.58, 34.73]
  },
  centroid: [-86.58, 34.73],
  area_sq_m: null,
  address: null,
  parcel_ids: [],
  source_fields: {},
  proximity_flags: []
};

const polygonRecord = {
  ...seedRecord,
  public_id: "hsv-test-polygon",
  title: "Seed Test Polygon",
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

test("map shell renders seed records with mocked API", async ({ page }) => {
  await page.route("**/api/development-records**", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({ records: [seedRecord, polygonRecord] })
    });
  });
  await page.route("**/api/map/layers", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        data_mode: "demo",
        catalog_revision: "test",
        layers: [{
          id: "ready-fixture-layer",
          title: "Ready fixture layer",
          delivery_status: "ready",
          default_visible: true,
          attribution: "Fixture attribution"
        }]
      })
    });
  });

  await page.goto("/");

  await expect(page.getByRole("link", { name: /Urbanization Tracker/i })).toBeVisible();
  await expect(page.getByText("Seed Test Subdivision")).toBeVisible({ timeout: 15_000 });
  await expect(page.getByTestId("development-map")).toBeVisible();
  await expect(page.locator(".maplibregl-canvas")).toBeVisible();
  await expect(page.getByTestId("development-map")).toHaveAttribute("data-feature-count", "2");
  const environmentalControl = page.getByRole("checkbox", { name: "Ready fixture layer" });
  await expect(environmentalControl).toBeDisabled();
  await expect(environmentalControl).not.toBeChecked();
  await expect(page.getByText("Environmental map rendering is being prepared for this layer.")).toBeVisible();

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
  const renderedFeature = await page.evaluate(() => {
    const testWindow = window as typeof window & {
      __urbanizationTrackerMap?: any;
      __urbanizationTrackerMapLibre?: any;
      __urbanizationTrackerFixtureAttribution?: any;
    };
    const map = testWindow.__urbanizationTrackerMap;
    const maplibregl = testWindow.__urbanizationTrackerMapLibre;
    const fixtureAttribution = new maplibregl.AttributionControl({
      compact: false,
      customAttribution:
        '<details open onload="window.__unsafeAttributionExecuted = true" ontoggle="window.__unsafeAttributionExecuted = true"><summary>Example source</summary><a href="https://example.test/source">Example source</a></details>'
    });
    map.addControl(fixtureAttribution, "bottom-right");
    testWindow.__urbanizationTrackerFixtureAttribution = fixtureAttribution;
    const feature = map.queryRenderedFeatures(undefined, { layers: ["development-points"] })[0];
    return {
      featureId: feature?.properties?.public_id,
      attributionHtml: fixtureAttribution._container?.innerHTML ?? "",
      unsafeExecuted: testWindow.__unsafeAttributionExecuted,
      attributionCount: document.querySelectorAll(".maplibregl-ctrl-attrib").length
    };
  });
  expect(renderedFeature.featureId).toBe(seedRecord.public_id);
  expect(renderedFeature.attributionHtml).toContain("Example source");
  expect(renderedFeature.attributionHtml).not.toMatch(/onload|ontoggle/);
  expect(renderedFeature.unsafeExecuted).toBeUndefined();
  expect(renderedFeature.attributionCount).toBe(2);
  await page.getByRole("button", { name: /Seed Test Subdivision/ }).click();
  await page.waitForTimeout(1_250);
  await clickCanvasCenter(page);
  await expect(page.getByRole("heading", { name: seedRecord.title })).toBeVisible();
  await expect(page.locator(".maplibregl-popup")).toContainText(seedRecord.title);
  await page.evaluate(() => {
    const testWindow = window as typeof window & {
      __urbanizationTrackerMap?: any;
      __urbanizationTrackerFixtureAttribution?: any;
    };
    testWindow.__urbanizationTrackerMap?.removeControl(
      testWindow.__urbanizationTrackerFixtureAttribution
    );
    delete testWindow.__urbanizationTrackerFixtureAttribution;
  });

  await page.getByRole("link", { name: "Participate", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Participate" })).toBeVisible();
  await page.getByRole("link", { name: "Map", exact: true }).click();
  await expect(page.getByTestId("development-map")).toBeVisible();
  await expect(page.locator(".maplibregl-canvas")).toHaveCount(1);
  await expect(page.locator(".maplibregl-ctrl-attrib")).toHaveCount(1);
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
  const remountedFeature = await page.evaluate(() => {
    const testWindow = window as typeof window & { __urbanizationTrackerMap?: any };
    const map = testWindow.__urbanizationTrackerMap;
    const feature = map.queryRenderedFeatures(undefined, { layers: ["development-points"] })[0];
    return {
      featureId: feature?.properties?.public_id
    };
  });
  expect(remountedFeature.featureId).toBe(seedRecord.public_id);
  await page.getByRole("button", { name: /Seed Test Subdivision/ }).click();
  await page.waitForTimeout(1_250);
  await clickCanvasCenter(page);
  await expect(page.locator(".maplibregl-popup")).toContainText(seedRecord.title);

  await page.locator(".maplibregl-popup-close-button").click();
  await page.getByRole("button", { name: /Seed Test Polygon/ }).click();
  await page.waitForTimeout(1_250);
  await clickCanvasCenter(page);
  await expect(page.locator(".maplibregl-popup")).toContainText(polygonRecord.title);
});

test("direct participate and record routes load their page bundles", async ({ page }) => {
  await page.route("**/api/change-log", async (route) => {
    await route.fulfill({ contentType: "application/json", body: JSON.stringify([]) });
  });
  await page.route("**/api/development-records/**", async (route) => {
    const body = route.request().url().endsWith("/versions") ? [] : seedRecord;
    await route.fulfill({ contentType: "application/json", body: JSON.stringify(body) });
  });

  await page.goto("/participate");
  await expect(page.getByRole("heading", { name: "Participate" })).toBeVisible();

  await page.goto(`/records/${seedRecord.public_id}`);
  await expect(page.getByRole("heading", { name: seedRecord.title })).toBeVisible();
});

test("reviewer operations import decisions and enforce alert limits", async ({ page }) => {
  const apiCalls: { importBody?: unknown; alertUrls: string[] } = { alertUrls: [] };
  const requestedUrls: string[] = [];
  page.on("request", (request) => requestedUrls.push(request.url()));

  await page.route("**/api/source-health", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({ status: "ok", records: {}, sources: [] })
    });
  });
  await page.route("**/api/source-documents", async (route) => {
    await route.fulfill({ contentType: "application/json", body: JSON.stringify([]) });
  });
  await page.route("**/api/connector-health", async (route) => {
    await route.fulfill({ contentType: "application/json", body: JSON.stringify([]) });
  });
  await page.route("**/api/jurisdictions", async (route) => {
    await route.fulfill({ contentType: "application/json", body: JSON.stringify([]) });
  });
  await page.route("**/api/reviewer/staged-records", async (route) => {
    await route.fulfill({ contentType: "application/json", body: JSON.stringify([]) });
  });
  await page.route("**/api/reviewer/duplicate-candidates", async (route) => {
    await route.fulfill({ contentType: "application/json", body: JSON.stringify([]) });
  });
  await page.route("**/api/reviewer/public-submissions", async (route) => {
    await route.fulfill({ contentType: "application/json", body: JSON.stringify([]) });
  });
  await page.route("**/api/reviewer/watch-areas", async (route) => {
    await route.fulfill({ contentType: "application/json", body: JSON.stringify([]) });
  });
  await page.route("**/api/reviewer/alerts", async (route) => {
    await route.fulfill({ contentType: "application/json", body: JSON.stringify([]) });
  });
  await page.route("**/api/reviewer/processed-store", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        backend: "postgres",
        database_first: true,
        database_error: null,
        collections: [
          {
            name: "development_records",
            database_count: 4,
            artifact_count: 0,
            requires_migration: false
          }
        ],
        raw_artifacts: [{ name: "raw_records", artifact_count: 3 }]
      })
    });
  });
  await page.route("**/api/reviewer/phase3-store", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        backend: "artifact",
        database_first: false,
        database_error: "Database status check failed.",
        raw_artifact_root: "raw",
        collections: [
          {
            name: "public_submissions",
            database_count: 2,
            artifact_count: 0,
            memory_count: 0,
            artifact_path: "processed/phase3_public_submissions.json",
            artifact_error: null,
            requires_migration: false
          }
        ]
      })
    });
  });
  await page.route("**/api/reviewer/decisions/import", async (route) => {
    apiCalls.importBody = route.request().postDataJSON();
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({ applied: 1, missing: ["stale-id"] })
    });
  });
  await page.route("**/api/reviewer/alerts/send**", async (route) => {
    apiCalls.alertUrls.push(route.request().url());
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        configured: false,
        attempted: 1,
        sent: 0,
        suppressed: 0,
        failed: 1,
        errors: ["SMTP settings are missing"]
      })
    });
  });

  await page.goto("/review");
  await expect(page.getByRole("heading", { name: "Operations" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Processed Store" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Phase 3 Store" })).toBeVisible();
  await expect(page.getByText("4 database · 0 artifact")).toBeVisible();
  await expect(page.getByText("2 database · 0 artifact · 0 memory")).toBeVisible();
  await expect(page.getByText("Raw audit artifacts: 3")).toBeVisible();
  const phase3StorePanel = page.locator(".store-status-panel").filter({
    hasText: "Phase 3 Store"
  });
  await expect(phase3StorePanel.getByText("degraded", { exact: true })).toBeVisible();
  await expect(phase3StorePanel.getByText("failing", { exact: true })).toHaveCount(0);
  expect(
    requestedUrls.some(
      (url) =>
        url.includes("/src/pages/MapPage.tsx") ||
        url.includes("/src/components/DevelopmentMap.tsx") ||
        url.includes("maplibre-gl")
    )
  ).toBe(false);

  await page.getByLabel("Import decisions").setInputFiles({
    name: "handoff.json",
    mimeType: "application/json",
    buffer: Buffer.from(
      JSON.stringify({
        decisions: [
          {
            staged_id: "staged-1",
            review_status: "needs_info",
            review_notes: "Please verify geometry",
            title: "Exported title",
            source_url: "https://example.test/source",
            exported_at: "2026-06-19T00:00:00Z"
          }
        ]
      })
    )
  });

  await expect(page.getByText("Imported 1 decisions; missing IDs: stale-id.")).toBeVisible();
  expect(apiCalls.importBody).toEqual({
    decisions: [
      {
        staged_id: "staged-1",
        review_status: "needs_info",
        notes: "Please verify geometry"
      }
    ]
  });

  await page.getByLabel("Limit").fill("999");
  await page.getByRole("button", { name: "Send alerts" }).click();
  await expect(page.getByText("Alert limit must be between 1 and 500.")).toBeVisible();
  expect(apiCalls.alertUrls).toEqual([]);

  await page.getByLabel("Limit").fill("10");
  await page.getByRole("button", { name: "Send alerts" }).click();
  await expect(
    page.getByText("Delivery is not configured. Errors: SMTP settings are missing")
  ).toBeVisible();
  expect(apiCalls.alertUrls).toHaveLength(1);
  expect(new URL(apiCalls.alertUrls[0]).searchParams.get("limit")).toBe("10");
});
