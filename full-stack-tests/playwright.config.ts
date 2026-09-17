import { defineConfig } from "@playwright/test";

// Specs write to the real stack's SQLite database (synthetic qa-e2e-* rows, removed
// afterwards), so they run one at a time.
export default defineConfig({
  testDir: "./tests",
  workers: 1,
  fullyParallel: false,
  timeout: 60_000,
  expect: { timeout: 15_000 },
  reporter: [["list"]],
  use: {
    baseURL: process.env.DASHBOARD_URL ?? "http://localhost:8501",
    trace: "retain-on-failure",
  },
});
