import { expect, test } from "@playwright/test";

test("P03 import progress retains the development map", async ({ page }, testInfo) => {
  test.skip(process.env.P03_IMPORTS !== "1", "Runs only in the P03 real import scenario");
  await page.goto("/");
  await expect(page.getByText("The update needs attention; existing map data has been retained.", {
    exact: false,
  })).toBeVisible();
  await expect(page.getByRole("checkbox", { name: "P03 environmental fixture" })).toBeDisabled();
  await expect(page.getByRole("checkbox", { name: "Revised environmental fixture" })).toBeDisabled();
  await expect(page.getByText("Revised synthetic source", { exact: true })).toBeVisible();
  await expect(page.getByText(
    "Revised environmental fixture: 2 source records checked, 0 need review. Source data checked; map preparation is pending.",
    { exact: true },
  )).toBeVisible();
  if (process.env.P03_SNAPSHOT === "1") {
    await expect(page.getByText(
      "Effective FEMA 1% Annual Chance Floodplain: 1883 source records checked, 5 need review. The update needs attention; this layer is unavailable.",
      { exact: true },
    )).toBeVisible();
  }
  await expect(page.getByText("new-layer-private-key", { exact: false })).toHaveCount(0);
  await expect(page.getByRole("button", {
    name: new RegExp(process.env.INTEGRATION_FIXTURE_TITLE!),
  })).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath("p03-import-progress.png"), fullPage: true });
});
