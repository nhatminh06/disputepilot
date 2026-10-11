import { expect, test } from '@playwright/test';
import { execFileSync } from 'node:child_process';
import { parseAssessment, parseDispute, parseHistory } from '../lib/contracts';

const path = '/api/disputes/PP-DEMO-001';

test('public GETs work without credentials or a backend and expose only the example', async ({ request }) => {
  for (const operation of ['', '/assessment', '/history']) {
    const response = await request.get(path + operation, { headers: { Host: 'demo.example.com' } });
    expect(response.status()).toBe(200);
    expect(response.headers()['x-disputepilot-demo']).toBe('synthetic-read-only');
    const value = await response.json();
    expect(value.demonstration).toContain('Synthetic example');
    if (!operation) {
      expect(parseDispute(value).seller_transaction_id).toBeNull();
      expect(value.available_actions).toEqual([]);
    } else if (operation === '/assessment') {
      expect(parseAssessment(value).risk).toBe('HIGH');
    } else {
      const history = parseHistory(value);
      expect(history.paypal_writes_enabled).toBe(false);
      expect(history.approved_action).toBeNull();
      expect(history.runs[0].execution_status).toBe('NOT_STARTED');
    }
    expect(JSON.stringify(value)).not.toMatch(/PP-R-UZR|79F26749|46817719|access_token|buyer_email|Authorization|postgresql:\/\//);
  }
});

test('all mutation methods reject even explicitly confirmed approval', async ({ request }) => {
  for (const method of ['POST', 'PUT', 'PATCH', 'DELETE']) {
    for (const operation of ['', '/assessment', '/history', '/investigate', '/approve', '/refund', '/capture', '/send-message']) {
      const response = await request.fetch(path + operation, {
        method, headers: { Origin: 'http://127.0.0.1:3001', 'X-DisputePilot-Request': operation.slice(1) },
        data: { run_id: '00000000-0000-4000-8000-000000000001', action_type: 'SEND_MESSAGE', confirmed: true },
      });
      expect(response.status()).toBe(405);
    }
  }
});

test('unknown examples and operations fail closed', async ({ request }) => {
  for (const url of ['/api/disputes/PP-R-UZR-10190879', path + '/investigate', path + '/approve', path + '/history/extra']) {
    expect((await request.get(url)).status()).toBe(404);
  }
  expect((await request.get('/disputes/PP-UNKNOWN')).status()).toBe(404);
  expect((await request.get(path)).status()).toBe(200);
});

test('public build configuration never loads the repository environment', () => {
  const output = execFileSync(process.execPath, ['--input-type=module', '-e', `
    process.env.DISPUTEPILOT_PUBLIC_DEMO = 'true';
    process.loadEnvFile = () => { throw new Error('Environment file must not be loaded'); };
    const { default: config } = await import('./next.config.ts');
    if (config.output !== undefined) throw new Error('Unexpected deployment output');
    console.log('Public configuration passed');
  `], { encoding: 'utf8' });
  expect(output).toContain('Public configuration passed');
});

for (const width of [1440, 390]) {
  test(`read-only example and visible labels at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 1000 });
    const unexpected: string[] = [];
    page.on('request', request => {
      if (request.method() !== 'GET' || new URL(request.url()).origin !== 'http://127.0.0.1:3001') unexpected.push(request.url());
    });
    await page.goto('/');
    await expect(page).toHaveURL(/\/disputes\/PP-DEMO-001$/);
    await expect(page.getByLabel('Public demo notice')).toContainText('synthetic examples');
    await expect(page.getByRole('heading', { name: 'Needs review', exact: true })).toBeVisible();
    await expect(page.getByText('Scripted example, not a live Gemini response')).toBeVisible();
    await expect(page.getByText(/Illustrative tool trace/)).toBeVisible();
    await expect(page.getByText('Synthetic events and dates')).toBeVisible();
    await expect(page.getByText('Demo mode: PayPal actions disabled', { exact: true })).toBeVisible();
    const scripts = await page.locator('script[src]').evaluateAll(elements => elements.map(element => (element as HTMLScriptElement).src));
    for (const src of scripts) {
      const body = await (await page.request.get(src)).text();
      expect(body).not.toMatch(/DEV_MERCHANT_TOKEN|PAYPAL_CLIENT_SECRET|GEMINI_API_KEY|DATABASE_URL|test-only-merchant-token/);
    }
    await expect(page.getByRole('button', { name: /Run investigation|Prepare a new investigation|Review message for approval|Confirm and send/ })).toHaveCount(0);
    await page.locator('.history-row').click();
    await page.getByRole('link', { name: 'shipping#demo-delivery', exact: true }).click();
    await expect(page.locator('#policy-shipping-demo-delivery')).toBeInViewport();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    if (width === 390) {
      await page.getByRole('button', { name: 'Open navigation' }).click();
      await page.getByRole('button', { name: 'Close navigation' }).click();
    }
    await page.evaluate(() => window.scrollTo({ top: 0, behavior: 'instant' }));
    await page.screenshot({ path: `/tmp/disputepilot-public-demo-${width}.png`, fullPage: true });
    expect(unexpected).toEqual([]);
  });
}
