import { expect, test } from "@playwright/test";

test("C05 read-only provenance and stale reviewer recovery against the real API", async ({ page, request }, testInfo) => {
  const token = process.env.INTEGRATION_REVIEWER_TOKEN;
  if (!token) throw new Error("C05 requires the isolated reviewer token");
  const headers = { Authorization: `Bearer ${token}` };
  const apiBase = process.env.P01_API_INTERNAL_URL ?? "http://api:8000";
  await page.addInitScript((value) => {
    window.sessionStorage.setItem("urbanization-tracker:reviewer-token", value);
  }, token);
  await page.goto("/review");
  const audit = page.locator("article.review-card").filter({
    has: page.getByRole("heading", { name: "C05 ArcGIS audit", exact: true })
  });
  await expect(audit.getByText(/Origin: processed/)).toBeVisible();
  await expect(audit.getByText(/Automatically ingested ArcGIS audit entry/)).toBeVisible();
  for (const name of ["Approve", "Reject", "Needs info"]) {
    await expect(audit.getByRole("button", { name, exact: true })).toBeDisabled();
  }

  const card = page.locator("article.review-card").filter({ hasText: "C05 browser conflict" });
  await expect(card.getByRole("heading", { name: "C05 browser conflict" })).toBeVisible();
  await expect(card.getByRole("button", { name: "Approve", exact: true })).toBeDisabled();
  await card.getByRole("textbox", { name: "Reviewer notes" }).fill("My preserved browser draft");
  const rows = await (await request.get(`${apiBase}/api/reviewer/staged-records`, { headers })).json();
  const row = rows.find((item: { title: string }) => item.title === "C05 browser conflict");
  const path = `/api/reviewer/staged-records/${row.id}`;
  const other = await request.post(`${apiBase}${path}/needs-info`, {
    headers, data: { expected_revision: 1, notes: "Other reviewer saved this note" }
  });
  expect(other.status()).toBe(200);

  let browserDecisions = 0;
  page.on("request", (outgoing) => {
    if (outgoing.method() === "POST" && outgoing.url().endsWith(`${path}/reject`)) browserDecisions += 1;
  });
  await card.getByRole("button", { name: "Reject", exact: true }).click();
  await expect(card.getByRole("heading", { name: "Review changed" })).toBeVisible();
  await expect(card.getByText(/is now revision 2 \(needs_info\)/)).toBeVisible();
  await expect(card.getByText("Current saved notes: Other reviewer saved this note")).toBeVisible();
  await expect(card.getByRole("textbox", { name: "Reviewer notes" })).toHaveValue("My preserved browser draft");
  await expect(card.getByRole("button", { name: "Reject", exact: true })).toBeDisabled();
  expect(browserDecisions).toBe(1);
  await card.screenshot({ path: testInfo.outputPath("c05-conflict.png") });
  const acknowledge = card.getByRole("button", { name: "I reviewed the current decision" });
  await acknowledge.focus();
  await page.keyboard.press("Enter");
  await card.getByRole("button", { name: "Reject", exact: true }).click();
  await expect(card.getByText(/Revision 3/).first()).toBeVisible();
  expect(browserDecisions).toBe(2);
  await page.reload();
  const savedReview = card.locator("section").filter({
    has: page.getByRole("heading", { name: "Saved review", exact: true })
  });
  await expect(savedReview.getByText("My preserved browser draft", { exact: true })).toBeVisible();
  await expect(card.getByRole("button", { name: "Reject", exact: true })).toBeDisabled();
  await card.getByText("Review history (2)", { exact: true }).click();
  await expect(card.getByText(/Revision 2.*Other reviewer saved this note/)).toBeVisible();
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(card.getByRole("heading", { name: "C05 browser conflict" })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await card.screenshot({ path: testInfo.outputPath("c05-narrow.png") });
});

test("C05 background queue refresh keeps the draft's original revision until acknowledgement", async ({ page, request }, testInfo) => {
  const token = process.env.INTEGRATION_REVIEWER_TOKEN;
  if (!token) throw new Error("C05 requires the isolated reviewer token");
  const headers = { Authorization: `Bearer ${token}` };
  const apiBase = process.env.P01_API_INTERNAL_URL ?? "http://api:8000";
  for (const title of ["C05 background draft", "C05 refresh trigger"]) {
    const created = await request.post(`${apiBase}/api/public-submissions`, {
      data: { title, notes: "Synthetic C05 refresh fixture", geometry: null }
    });
    expect(created.status()).toBe(200);
  }
  await page.addInitScript((value) => {
    window.sessionStorage.setItem("urbanization-tracker:reviewer-token", value);
  }, token);
  await page.goto("/review");
  const card = page.locator("article.review-card").filter({
    has: page.getByRole("heading", { name: "C05 background draft", exact: true })
  });
  const trigger = page.locator("article.review-card").filter({
    has: page.getByRole("heading", { name: "C05 refresh trigger", exact: true })
  });
  await card.getByRole("textbox", { name: "Reviewer notes" }).fill("Draft from revision one");
  const rows = await (await request.get(`${apiBase}/api/reviewer/staged-records`, { headers })).json();
  const row = rows.find((item: { title: string }) => item.title === "C05 background draft");
  const path = `/api/reviewer/staged-records/${row.id}`;
  const other = await request.post(`${apiBase}${path}/needs-info`, {
    headers, data: { expected_revision: row.revision, notes: "Saved before background refresh" }
  });
  expect(other.status()).toBe(200);
  let decisions = 0;
  page.on("request", (outgoing) => {
    if (outgoing.method() === "POST" && outgoing.url().endsWith(`${path}/reject`)) decisions += 1;
  });
  // A successful action on a different card invalidates/refetches the actual queue.
  await trigger.getByRole("button", { name: "Needs info", exact: true }).click();
  await expect(card.getByRole("heading", { name: "Review changed" })).toBeVisible();
  await expect(card.getByText(/is now revision 2 \(needs_info\)/)).toBeVisible();
  await expect(card.getByRole("textbox", { name: "Reviewer notes" })).toHaveValue("Draft from revision one");
  await expect(card.getByRole("button", { name: "Reject", exact: true })).toBeDisabled();
  await expect(card.getByRole("button", { name: "Needs info", exact: true })).toBeDisabled();
  expect(decisions).toBe(0);
  await card.screenshot({ path: testInfo.outputPath("c05-background-refresh.png") });
  await card.getByRole("button", { name: "I reviewed the current decision" }).click();
  await card.getByRole("button", { name: "Reject", exact: true }).click();
  await expect(card.getByText(/Revision 3/).first()).toBeVisible();
  expect(decisions).toBe(1);
  const saved = await (await request.get(`${apiBase}${path}`, { headers })).json();
  expect(saved.review_history.map((event: { notes: string }) => event.notes)).toEqual([
    "Saved before background refresh", "Draft from revision one"
  ]);
});
