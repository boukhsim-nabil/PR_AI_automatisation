import { defineConfig } from "@playwright/test";

const apiBaseURL = process.env.API_BASE_URL ?? "http://localhost:8000";

export default defineConfig({
  testDir: "./tests/api",
  fullyParallel: false,
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 1 : 0,
  workers: 1,
  timeout: 30_000,
  expect: { timeout: 5_000 },
  globalSetup: "./tests/api/global-setup.ts",
  reporter: [
    ["list"],
    ["html", { open: "never", outputFolder: "playwright-report-api" }],
  ],
  outputDir: "test-results/api",
  use: {
    baseURL: apiBaseURL,
    // API traces capture Authorization headers; keep them disabled to avoid token leakage.
    trace: "off",
  },
  projects: [{ name: "api" }],
});
