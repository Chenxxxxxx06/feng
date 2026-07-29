import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: './e2e',
  timeout: 30000,
  retries: 1,
  // The closed-loop specs intentionally reset one labelled competition
  // scenario, so keep browser runs deterministic and free of cross-test races.
  workers: 1,
  use: {
    baseURL: 'http://localhost:5173',
    extraHTTPHeaders: {
      'Content-Type': 'application/json',
    },
  },
  webServer: {
    command: 'npm run dev',
    port: 5173,
    reuseExistingServer: true,
    timeout: 10000,
  },
});
