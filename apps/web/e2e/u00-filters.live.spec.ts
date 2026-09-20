import { expect, test } from "@playwright/test";

const statuses = ["Layout", "Preliminary", "Final", "Issued permit", "Completed", "Proposed"];

test("U00 filters keep real list, map query, and selection state aligned", async ({ page }) => {
  test.skip(process.env.U00_FILTERS !== "1", "U00 scenario is opt-in");

  const recordsResponse = page.waitForResponse(
    (response) =>
      new URL(response.url()).pathname === "/api/development-records" && response.status() === 200
  );

  await page.goto("/");
  const records = await (await recordsResponse).json();
  expect(new Set(records.records.map((record: { public_id: string }) => record.public_id))).toEqual(
    new Set([
      "u00-completed-development",
      "u00-proposed-submission",
      "u00-published-submission"
    ])
  );

  await expect(page.getByRole("button", { name: /U00 Completed Development/ })).toBeVisible();
  await expect(page.getByRole("button", { name: /U00 Proposed Public Submission/ })).toBeVisible();
  await expect(page.getByRole("button", { name: /U00 Published Public Submission/ })).toBeVisible();

  await page.getByRole("checkbox", { name: "Near waterway", exact: true }).check();
  await expect(page.getByRole("button", { name: /U00 Proposed Public Submission/ })).toBeVisible();
  await expect(page.getByRole("button", { name: /U00 Published Public Submission/ })).toHaveCount(0);
  await page.getByRole("button", { name: "Clear flag restriction" }).click();
  await expect(page.getByRole("button", { name: /U00 Proposed Public Submission/ })).toBeVisible();
  await expect(page.getByRole("button", { name: /U00 Published Public Submission/ })).toBeVisible();

  for (const type of ["Subdivisions", "Building permits", "Public submissions"]) {
    await page.getByRole("checkbox", { name: type, exact: true }).uncheck();
  }
  await expect(page.getByRole("status")).toContainText(
    "No development records are available for these filters."
  );
  await page.getByRole("button", { name: "Reset filters" }).click();
  await expect(page.getByRole("button", { name: /U00 Completed Development/ })).toBeVisible();
  await expect(page.getByRole("button", { name: /U00 Proposed Public Submission/ })).toBeVisible();
  await expect(page.getByRole("button", { name: /U00 Published Public Submission/ })).toBeVisible();

  await page.getByRole("button", { name: /U00 Proposed Public Submission/ }).click();
  await expect(page.getByRole("heading", { name: "U00 Proposed Public Submission" })).toBeVisible();

  for (const status of statuses.filter((status) => status !== "Completed")) {
    await page.getByRole("checkbox", { name: status, exact: true }).uncheck();
  }
  await expect(page.getByRole("button", { name: /U00 Completed Development/ })).toBeVisible();
  await expect(page.getByRole("button", { name: /U00 Proposed Public Submission/ })).toHaveCount(0);
  await expect(page.getByRole("heading", { name: "Select a record" })).toBeVisible();

  await page.getByRole("button", { name: "Reset filters" }).click();
  await expect(page.getByRole("button", { name: /U00 Proposed Public Submission/ })).toBeVisible();

  await page.getByRole("checkbox", { name: "Subdivisions", exact: true }).uncheck();
  await page.getByRole("checkbox", { name: "Building permits", exact: true }).uncheck();
  await expect(page.getByRole("button", { name: /U00 Completed Development/ })).toHaveCount(0);
  await expect(page.getByRole("button", { name: /U00 Proposed Public Submission/ })).toBeVisible();
  await expect(page.getByRole("button", { name: /U00 Published Public Submission/ })).toBeVisible();

  await page.getByRole("button", { name: "Reset filters" }).click();
  for (const status of statuses) {
    await page.getByRole("checkbox", { name: status, exact: true }).uncheck();
  }
  await expect(page.getByRole("status")).toContainText(
    "No development records are available for these filters."
  );
});
