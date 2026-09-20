import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  testMatch: "production-preview.spec.ts",
  outputDir: "test-results/production-preview",
  fullyParallel: false,
  use: {
    baseURL: "http://127.0.0.1:5176",
    trace: "on",
    ...devices["Desktop Chrome"]
  },
  webServer: {
    command: "npm run preview -- --host 127.0.0.1 --port 5176",
    url: "http://127.0.0.1:5176",
    reuseExistingServer: false,
    timeout: 120_000
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }]
});
