import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: './demo-tests', fullyParallel: true, workers: 2,
  use: { baseURL: 'http://127.0.0.1:3001', headless: true,
    launchOptions: { executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE } },
  webServer: {
    command: 'npm run dev -- --port 3001', url: 'http://127.0.0.1:3001', reuseExistingServer: false,
    env: {
      DISPUTEPILOT_PUBLIC_DEMO: 'true', DISPUTEPILOT_API_URL: 'http://127.0.0.1:1',
      DEV_MERCHANT_TOKEN: '', PAYPAL_CLIENT_SECRET: '', GEMINI_API_KEY: '', DATABASE_URL: '',
    },
  },
});
