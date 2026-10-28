import os from "node:os";
import path from "node:path";

import { defineConfig, devices } from "@playwright/test";

// Browser tests run against the real API in fixture mode, serving the built frontend (`npm run build` first).
// The server is started from this directory so the repository's .env (and any API keys in it) is never loaded.
const port = Number(process.env.E2E_PORT ?? 8765);

export default defineConfig({
  testDir: "./e2e",
  timeout: 60_000,
  expect: { timeout: 20_000 },
  fullyParallel: false,
  workers: 1,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [["list"], ["html", { open: "never" }]] : "list",
  use: {
    baseURL: `http://127.0.0.1:${port}`,
    trace: "retain-on-failure",
  },
  projects: [
    { name: "desktop", use: { ...devices["Desktop Chrome"] } },
    { name: "mobile", use: { ...devices["Pixel 7"] }, grep: /@mobile/ },
  ],
  webServer: {
    command: `uv run --project .. predixion serve --port ${port}`,
    url: `http://127.0.0.1:${port}/healthz`,
    reuseExistingServer: false,
    timeout: 120_000,
    env: {
      PREDIXION_ENV: "test",
      PREDIXION_MODE: "fixture",
      OPENAI_API_KEY: "",
      TAVILY_API_KEY: "",
      ENABLE_FAULT_INJECTION: "true",
      SERVE_FRONTEND_DIR: path.resolve("dist"),
      PREDIXION_DB_PATH: path.join(os.tmpdir(), `predixion-e2e-${process.pid}.sqlite3`),
    },
  },
});
