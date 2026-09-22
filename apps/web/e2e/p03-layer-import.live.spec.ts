import { expect, test } from "@playwright/test";

test("P03 import progress retains the development map", async ({ page }, testInfo) => {
  test.skip(process.env.P03_IMPORTS !== "1", "Runs only in the P03 real import scenario");
  await page.goto("/");
  await expect(page.getByText("The update needs attention; existing map data has been retained.", {
    exact: false,
  })).toBeVisible();
  await expect(page.getByRole("checkbox", { name: "P03 environmental fixture" })).toBeDisabled();
  await expect(page.getByRole("checkbox", { name: "New environmental fixture" })).toBeDisabled();
  await expect(page.getByText("The update needs attention; this layer is unavailable.", {
    exact: false,
  })).toBeVisible();
  await expect(page.getByText("new-layer-private-key", { exact: false })).toHaveCount(0);
  await expect(page.getByRole("button", {
    name: new RegExp(process.env.INTEGRATION_FIXTURE_TITLE!),
  })).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath("p03-import-progress.png"), fullPage: true });
});
