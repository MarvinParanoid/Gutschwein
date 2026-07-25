import { existsSync } from 'node:fs'

import { defineConfig } from '@playwright/test'

const PORT = 8099
const BASE_URL = `http://127.0.0.1:${PORT}`

// Tests run against the built bundle served by FastAPI — the same artefact that
// ships — rather than against the Vite dev server.
const python = existsSync('../backend/.venv/bin/python') ? '.venv/bin/python' : 'python'

export default defineConfig({
  testDir: './e2e',
  timeout: 30_000,
  expect: { timeout: 7_000 },
  // One backend, one database: parallel workers would fight over the same data.
  workers: 1,
  fullyParallel: false,
  forbidOnly: Boolean(process.env.CI),
  reporter: process.env.CI ? [['github'], ['list']] : [['list']],

  use: {
    baseURL: BASE_URL,
    // The production bundle has no dev login of its own. The backend honours this
    // header only when DEV_MODE is on, which is exactly the case here.
    extraHTTPHeaders: { 'X-Dev-User': '1000' },
    viewport: { width: 420, height: 900 },
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },

  webServer: {
    // The wipe lives in the command, not in globalSetup: Playwright starts the
    // web server first, so a setup hook would delete the database out from
    // under a running app.
    command: `sh -c 'rm -rf ./.e2e-data && ${python} -m uvicorn app.main:app --port ${PORT}'`,
    cwd: '../backend',
    url: `${BASE_URL}/healthz`,
    reuseExistingServer: false,
    timeout: 60_000,
    stdout: 'pipe',
    stderr: 'pipe',
    env: {
      DEV_MODE: 'true',
      RUN_BOT: 'false',
      BOT_TOKEN: '',
      FAMILY_CHAT_ID: '',
      DATA_DIR: './.e2e-data',
      DATABASE_URL: 'sqlite+aiosqlite:///./.e2e-data/e2e.db',
    },
  },
})
