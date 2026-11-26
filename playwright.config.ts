import { join } from "node:path";

import { defineConfig, devices } from "@playwright/test";

import { runDirectory } from "./e2e/run-dir";

const FRONTEND_HOST = "127.0.0.1";
const FRONTEND_PORT = 5173;
const API_HOST = "127.0.0.1";
const API_PORT = 4318;
const FRONTEND_URL = `http://${FRONTEND_HOST}:${FRONTEND_PORT}`;
const API_URL = `http://${API_HOST}:${API_PORT}`;

/** Seeded database that the backend serves during the run; it is deleted afterwards. */
const DB_PATH = join(runDirectory(), "trace-lens.db");

/**
 * A system Chromium can be used instead of the one Playwright manages. It is set only through
 * the environment, so no browser path is stored in the repository.
 */
const chromiumPath = process.env.PW_CHROMIUM;

export default defineConfig({
  testDir: "./e2e",
  testMatch: "**/*.spec.ts",
  globalTeardown: "./e2e/global-teardown.ts",
  timeout: 60_000,
  forbidOnly: process.env.CI !== undefined,
  use: {
    baseURL: FRONTEND_URL,
    launchOptions: chromiumPath === undefined ? {} : { executablePath: chromiumPath },
  },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],
  webServer: [
    {
      // Seed the temporary database, then serve it. Both steps run in one shell command so that
      // the backend starts only after the demo traces are stored.
      command: `uv run --directory backend python -m tracelens.demo --db "$DB_PATH" --traces 200 --seed 7 && uv run --directory backend python -m tracelens`,
      url: `${API_URL}/api/healthz`,
      env: { DB_PATH, HOST: API_HOST, PORT: String(API_PORT) },
      reuseExistingServer: false,
      timeout: 180_000,
    },
    {
      command: "npm run dev --workspace web",
      url: FRONTEND_URL,
      reuseExistingServer: false,
      timeout: 120_000,
    },
  ],
});
