import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  testMatch: /(?:live-smoke|data-modes\.live)\.spec\.ts/,
  fullyParallel: false,
  outputDir: process.env.PLAYWRIGHT_OUTPUT_DIR ?? "test-results-live",
  reporter: [["list"], ["junit", { outputFile: process.env.PLAYWRIGHT_JUNIT_OUTPUT_NAME }]],
  use: {
    baseURL: process.env.LIVE_WEB_BASE_URL ?? "http://web",
    // The reviewer smoke test holds a bearer token in sessionStorage. Do not retain it in a trace.
    trace: "off"
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }]
});
