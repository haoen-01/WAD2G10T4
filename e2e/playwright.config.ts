import { tmpdir } from 'node:os';
import path from 'node:path';

import { defineConfig, devices } from '@playwright/test';

// This config lives in e2e/; the API runs from server/ and the web app from client/ beside it.
const e2eDirectory = __dirname;
const repoRoot = path.join(e2eDirectory, '..');
const apiDirectory = path.join(repoRoot, 'server');
const webDirectory = path.join(repoRoot, 'client');
// Ports are overridable so the suite can run beside a developer's own `pnpm dev` (which holds
// 3000 and 8000 and which `reuseExistingServer: false` refuses to share). Defaults are unchanged;
// the spec reads the same variables so the API it drives is the one started here.
const apiPort = process.env.E2E_API_PORT ?? '8000';
const webPort = process.env.E2E_WEB_PORT ?? '3000';
const apiUrl = `http://127.0.0.1:${apiPort}`;
const webUrl = `http://127.0.0.1:${webPort}`;
const databasePath = path.join(tmpdir(), `silverloop-e2e-${process.pid}.db`);
// Care+ is for Singapore, and the API names "today" in Singapore time (`APP_TIMEZONE`). Run the
// browser and the test code (dates the specs work out, such as `isoDay`) on the same clock, so the
// suite does not fail between midnight and 08:00 in Singapore, when a UTC machine is a day behind.
const TIMEZONE = 'Asia/Singapore';
process.env.TZ = TIMEZONE;

export default defineConfig({
  testDir: './tests',
  fullyParallel: false,
  workers: 1,
  retries: process.env.CI ? 1 : 0,
  timeout: 30_000,
  expect: { timeout: 7_500 },
  // One folder per web port, so concurrent runs on different ports do not wipe each other's traces.
  outputDir: path.join(e2eDirectory, 'test-results', webPort),
  reporter: process.env.CI
    ? [
        ['list'],
        ['html', { open: 'never', outputFolder: path.join(e2eDirectory, 'playwright-report') }],
      ]
    : 'list',
  use: {
    baseURL: webUrl,
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
    ...devices['Desktop Chrome'],
    timezoneId: TIMEZONE,
  },
  webServer: [
    {
      command: `uv run uvicorn silverloop.main:app --host 127.0.0.1 --port ${apiPort}`,
      cwd: apiDirectory,
      url: `${apiUrl}/health`,
      reuseExistingServer: false,
      timeout: 60_000,
      env: {
        ...process.env,
        APP_ENV: 'test',
        CAREPLUS_RUNTIME_PROFILE: 'offline',
        SILVERLOOP_RUNTIME_PROFILE: 'offline',
        ADAPTER_MODE: 'fixture',
        DATABASE_URL: `sqlite+pysqlite:///${databasePath}`,
        LLM_ENABLED: 'false',
        AUTH_ENABLED: 'false',
        // The API's default CORS allow-list names port 3000 only; on an alternate web port the
        // browser would be refused every request and every API-backed spec would time out.
        CORS_ORIGINS: `${webUrl},http://localhost:${webPort}`,
        UV_CACHE_DIR: path.join(repoRoot, '.uv-cache'),
      },
    },
    {
      command: `pnpm exec vite --host 127.0.0.1 --port ${webPort} --strictPort`,
      cwd: webDirectory,
      url: webUrl,
      reuseExistingServer: false,
      timeout: 60_000,
      env: {
        ...process.env,
        // `vite.config.ts` reads this to give each web port its own dependency cache.
        E2E_WEB_PORT: webPort,
        VITE_API_BASE_URL: apiUrl,
        VITE_AUTH_ENABLED: 'false',
        // The walk map starts on its offline sketch, so no test fetches outside map pictures.
        VITE_WALK_MAP: 'sketch',
      },
    },
  ],
});
