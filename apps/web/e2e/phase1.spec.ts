import { expect, test } from "@playwright/test";

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

test("map shell renders seed records with mocked API", async ({ page }) => {
  await page.route("**/api/development-records**", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({ records: [seedRecord] })
    });
  });
  await page.route("**/api/environmental-overlays", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify([])
    });
  });

  await page.goto("/");

  await expect(page.getByRole("link", { name: /Urbanization Tracker/i })).toBeVisible();
  await expect(page.getByText("Seed Test Subdivision")).toBeVisible();
  await expect(page.getByTestId("development-map")).toBeVisible();
  await expect(page.locator(".maplibregl-canvas")).toBeVisible();
  await expect(page.getByTestId("development-map")).toHaveAttribute("data-feature-count", "1");
});

test("reviewer operations import decisions and enforce alert limits", async ({ page }) => {
  const apiCalls: { importBody?: unknown; alertUrls: string[] } = { alertUrls: [] };

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
        backend: "postgres",
        database_first: true,
        database_error: null,
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
