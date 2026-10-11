import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: './tests', testMatch: '**/*.spec.ts', fullyParallel: true, workers: 2,
  use: { baseURL: 'http://127.0.0.1:3001', headless: true,
    launchOptions: { executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE } },
  webServer: [
    { command: 'node --experimental-strip-types tests/mock-backend.ts', url: 'http://127.0.0.1:8001/health', reuseExistingServer: false },
    { command: 'npm run dev -- --port 3001', url: 'http://127.0.0.1:3001/disputes/PP-TEST', reuseExistingServer: false,
      env: { DEV_MERCHANT_TOKEN: 'test-only-merchant-token-not-a-secret-12345', DISPUTEPILOT_API_URL: 'http://127.0.0.1:8001' } },
  ],
});
