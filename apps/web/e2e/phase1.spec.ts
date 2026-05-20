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
