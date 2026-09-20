import { expect, test } from "@playwright/test";

const phase = process.env.C01_BROWSER_PHASE;

test(`C01 data modes real API map state: ${phase ?? "not-configured"}`, async ({ page }) => {
  test.skip(!phase, "C01_BROWSER_PHASE is set by the C01 real-stack scenario.");
  const recordsResponse = page.waitForResponse(
    (response) => new URL(response.url()).pathname === "/api/development-records"
  );

  await page.goto("/");
  const response = await recordsResponse;

  if (phase === "unavailable") {
    expect(response.status()).toBe(503);
    await expect(
      page.getByText("Development data is unavailable. Try again after initialization completes.")
    ).toBeVisible();
    await expect(
      page.getByText("Environmental context is unavailable. Try again after initialization completes.")
    ).toBeVisible();
    await expect(page.getByTestId("development-map")).toHaveAttribute("data-feature-count", "0");
    await expect(page.locator(".record-row")).toHaveCount(0);
    return;
  }

  expect(response.status()).toBe(200);
  if (phase === "empty") {
    await expect(page.getByText("No development records are available for these filters.")).toBeVisible();
    await expect(page.getByTestId("development-map")).toHaveAttribute("data-feature-count", "0");
    await expect(page.locator(".record-row")).toHaveCount(0);
    return;
  }

  if (phase === "demo") {
    await expect(page.getByText(/Demo data.*not live planning data/)).toBeVisible();
    await expect(page.locator(".record-row")).not.toHaveCount(0);

    await page.goto("/records/hsv-westmoore-landing-ph1");
    await expect(page.getByText(/Demo data.*not live planning data/)).toBeVisible();
    return;
  }

  throw new Error(`Unsupported C01 browser phase: ${phase}`);
});
