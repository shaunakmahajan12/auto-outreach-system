import { defineConfig } from '@playwright/test';
export default defineConfig({
  testDir: './e2e',
  workers: 1,
  fullyParallel: false,
  timeout: 30000,
  use: { baseURL: 'http://127.0.0.1:8765', trace: 'off', screenshot: 'off', video: 'off' },
  webServer: [
    {
      command: '../.venv/bin/python ../scripts/e2e_server.py',
      url: 'http://127.0.0.1:8765/health',
      reuseExistingServer: false,
      timeout: 30000,
    },
    {
      command: '../.venv/bin/python ../scripts/e2e_remote_server.py',
      url: 'https://127.0.0.1:8766/health',
      ignoreHTTPSErrors: true,
      reuseExistingServer: false,
      timeout: 30000,
    },
  ],
});
