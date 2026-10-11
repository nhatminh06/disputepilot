import { expect, test } from '@playwright/test';
import { allowedBackend } from '../lib/upstream';

test('internal backend is allowed only in explicit Compose mode', () => {
  expect(allowedBackend('http://backend:8000', true)).toBe(true);
  expect(allowedBackend('http://backend:8000', false)).toBe(false);
  for (const base of ['http://127.0.0.1:8000', 'http://127.0.0.1:8001']) {
    expect(allowedBackend(base, false)).toBe(true);
    expect(allowedBackend(base, true)).toBe(false);
  }
  for (const base of ['https://attacker.invalid', 'http://backend:8000@attacker.invalid',
    'http://backend:8000/redirect', 'http://backend:8000?target=x', 'http://backend.evil:8000',
    'http://localhost:8000', 'http://127.0.0.1:8002', 'http://backend:8000/']) {
    expect(allowedBackend(base, true)).toBe(false);
    expect(allowedBackend(base, false)).toBe(false);
  }
});

test('clean database shows empty history and never offers approval', async ({ page }) => {
  await page.route('**/api/disputes/PP-TEST/history', route => route.fulfill({ status: 404, json: { error: 'Not found' } }));
  await page.goto('/disputes/PP-TEST');
  await expect(page.getByRole('region', { name: 'Investigation history' })).toContainText('No saved investigations');
  await expect(page.getByRole('button', { name: 'Review message for approval' })).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Run investigation' })).toBeEnabled();
});
