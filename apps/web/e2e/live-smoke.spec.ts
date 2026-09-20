import { expect, test } from "@playwright/test";

function fixtureTitle() {
  const title = process.env.INTEGRATION_FIXTURE_TITLE;
  if (!title) throw new Error("INTEGRATION_FIXTURE_TITLE is required for the live browser smoke test");
  return title;
}

test("production web renders the deterministic record returned by the real API", async ({ page }) => {
  const title = fixtureTitle();
  const recordsResponse = page.waitForResponse(
    (response) =>
      new URL(response.url()).pathname === "/api/development-records" && response.status() === 200
  );

  await page.goto("/");

  const records = await (await recordsResponse).json();
  expect(records.records).toEqual(expect.arrayContaining([expect.objectContaining({ title })]));
  await expect(page.getByRole("button", { name: new RegExp(title) })).toBeVisible({ timeout: 15_000 });
  await expect(page.getByTestId("development-map")).toHaveAttribute("data-feature-count", "1");
});

test("reviewer page receives Postgres processed-store status through authenticated API", async ({ page }) => {
  const token = process.env.INTEGRATION_REVIEWER_TOKEN;
  if (!token) throw new Error("INTEGRATION_REVIEWER_TOKEN is required for the live browser smoke test");
  await page.addInitScript(
    (reviewerToken) => window.sessionStorage.setItem("urbanization-tracker:reviewer-token", reviewerToken),
    token
  );
  const processedStoreResponse = page.waitForResponse(
    (response) => response.url().endsWith("/api/reviewer/processed-store") && response.status() === 200
  );

  await page.goto("/review");

  const status = await (await processedStoreResponse).json();
  expect(status).toMatchObject({ backend: "postgres", database_first: true });
  expect(status.collections).toEqual(
    expect.arrayContaining([expect.objectContaining({ name: "development_records", database_count: 1 })])
  );
  const panel = page.locator("article.store-status-panel").filter({ hasText: "Processed Store" });
  await expect(panel.getByText("Postgres", { exact: true })).toBeVisible({ timeout: 15_000 });
  await expect(panel.getByText(/1 database/).first()).toBeVisible();
});
