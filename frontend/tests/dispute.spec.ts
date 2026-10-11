import { expect, test } from '@playwright/test';
import { assessment, dispute, run } from './fixtures';

test('renders real response fields, deterministic risk, provenance and unfavorable facts', async ({ page }) => {
  await page.goto('/disputes/PP-TEST');
  await expect(page.getByRole('heading', { name: 'Item not received', exact: true })).toBeVisible();
  await expect(page.getByText('Waiting for buyer response', { exact: true })).toBeVisible();
  await expect(page.getByText('10.00', { exact: false }).first()).toBeVisible();
  await expect(page.getByText('High contesting risk')).toBeVisible();
  await expect(page.getByText('paypal:test-capture')).toBeVisible();
  await expect(page.getByText('UNKNOWN', { exact: true })).toBeVisible();
  await expect(page.getByText('MISSING', { exact: true })).toBeVisible();
  await expect(page.locator('.fact-adverse')).toHaveCount(2);
  await expect(page.getByText('Does not support contesting', { exact: true })).toHaveCount(2);
  await expect(page.getByText('Verified value: No')).toBeVisible();
  await expect(page.getByText('Oct 30, 2026, 4:33 AM UTC')).toBeVisible();
});

test('initial state does not invoke Gemini or fabricate policy citations', async ({ page }) => {
  const posts: string[] = [];
  page.on('request', request => { if (request.method() === 'POST') posts.push(request.url()); });
  await page.goto('/disputes/PP-TEST');
  await expect(page.getByRole('button', { name: 'Investigate with AI' })).toBeEnabled();
  await expect(page.getByText('0 retrieved')).toBeVisible();
  await expect(page.getByText('No run in this session')).toBeVisible();
  expect(posts).toEqual([]);
});

test('investigates once, shows recommendation, exact excerpts and persisted states', async ({ page }) => {
  await page.goto('/disputes/PP-TEST');
  await page.getByRole('button', { name: 'Investigate with AI' }).click();
  await expect(page.getByRole('heading', { name: 'Needs review', exact: true })).toBeVisible();
  await expect(page.getByText(run.assessment.recommendation!.response.summary)).toBeVisible();
  await expect(page.locator('blockquote')).toHaveText(run.assessment.retrieved_policies[0].excerpt);
  await expect(page.getByText('Synthetic demo policy', { exact: true })).toBeVisible();
  await expect(page.getByRole('link', { name: 'shipping#delivery' })).toHaveAttribute('href', '#policy-shipping-delivery');
  await expect(page.getByText(run.run_id)).toBeVisible();
  await expect(page.getByText('PENDING', { exact: true })).toBeVisible();
  await expect(page.getByText('NOT_STARTED', { exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: /Investigate with AI/ })).toHaveCount(0);
  await expect(page.getByRole('button', { name: /approve|refund|send message/i })).toHaveCount(0);
});

test('blocks duplicate submissions while an investigation is pending', async ({ page }) => {
  let calls = 0;
  let release: () => void = () => { throw new Error('Not initialized'); };
  const pending = new Promise<void>(resolve => { release = resolve; });
  await page.route('**/api/disputes/PP-TEST/investigate', async route => {
    calls++; await pending; await route.fulfill({ json: run, status: 201 });
  });
  await page.goto('/disputes/PP-TEST');
  await page.getByRole('button', { name: 'Investigate with AI' }).click();
  await expect(page.getByRole('button', { name: 'Investigating…' })).toBeDisabled();
  await page.getByRole('button', { name: 'Investigating…' }).evaluate(button => {
    button.dispatchEvent(new MouseEvent('click', { bubbles: true }));
  });
  expect(calls).toBe(1); release();
  await expect(page.getByText(run.run_id)).toBeVisible();
});

test('shows Gemini fallback and no-policy state without fabricating an explanation', async ({ page }) => {
  const fallback = structuredClone(run);
  fallback.assessment.retrieved_policies = [];
  fallback.assessment.recommendation!.fallback = true;
  fallback.assessment.recommendation!.api_status = 'API_ERROR';
  fallback.assessment.recommendation!.response.policy_refs = [];
  await page.route('**/api/disputes/PP-TEST/investigate', route => route.fulfill({ json: fallback, status: 201 }));
  await page.goto('/disputes/PP-TEST');
  await page.getByRole('button', { name: 'Investigate with AI' }).click();
  await expect(page.getByText(/Safe fallback: Api error/)).toBeVisible();
  await expect(page.getByText('No relevant policies retrieved')).toBeVisible();
});

test('read failures and unauthorized states are explicit', async ({ page }) => {
  await page.goto('/disputes/PP-UNAUTHORIZED');
  await expect(page.getByRole('main').getByRole('alert')).toContainText('Merchant authentication failed');
  await expect(page.getByRole('button', { name: 'Retry read-only lookup' })).toBeEnabled();
});

test('an ambiguous investigation error cannot be automatically resubmitted', async ({ page }) => {
  let calls = 0;
  await page.route('**/api/disputes/PP-TEST/investigate', route => {
    calls++; return route.fulfill({ status: 502, json: { error: 'Outcome unknown. Check the backend.' } });
  });
  await page.goto('/disputes/PP-TEST');
  await page.getByRole('button', { name: 'Investigate with AI' }).click();
  await expect(page.getByRole('main').getByRole('alert')).toContainText('Outcome unknown');
  await expect(page.getByRole('button', { name: 'Investigate with AI' })).toBeDisabled();
  expect(calls).toBe(1);
});

test('network errors and empty evidence have honest states', async ({ page }) => {
  await page.route('**/api/disputes/PP-TEST/assessment', route => route.abort());
  await page.goto('/disputes/PP-TEST');
  await expect(page.getByRole('main').getByRole('alert')).toBeVisible();
  await page.unroute('**/api/disputes/PP-TEST/assessment');
  await page.route('**/api/disputes/PP-TEST/assessment', route => route.fulfill({ json: { ...assessment, facts: [], rules: [] } }));
  await page.getByRole('button', { name: 'Retry read-only lookup' }).click();
  await expect(page.getByText('No evidence facts were returned.')).toBeVisible();
});

test('mobile stacks panels and supports accessible navigation without overflow', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/disputes/PP-TEST');
  await expect(page.getByRole('button', { name: 'Investigate with AI' })).toBeVisible();
  const evidence = await page.locator('.evidence-card').boundingBox();
  const ai = await page.locator('.ai-card').boundingBox();
  expect(ai!.y).toBeGreaterThan(evidence!.y + evidence!.height);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.getByRole('button', { name: 'Open navigation' }).click();
  await expect(page.getByRole('link', { name: 'Disputes', exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Close navigation' }).click();
  await expect(page.getByRole('link', { name: 'Disputes', exact: true })).toBeHidden();
});

test('desktop uses two columns and keyboard focus is visible', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto('/disputes/PP-TEST');
  await expect(page.getByRole('button', { name: 'Investigate with AI' })).toBeVisible();
  const evidence = await page.locator('.evidence-card').boundingBox();
  const ai = await page.locator('.ai-card').boundingBox();
  expect(Math.abs(evidence!.y - ai!.y)).toBeLessThan(2);
  expect(ai!.x).toBeGreaterThan(evidence!.x + evidence!.width);
  await page.getByRole('button', { name: 'Investigate with AI' }).focus();
  expect(await page.getByRole('button', { name: 'Investigate with AI' }).evaluate(el => getComputedStyle(el).outlineStyle)).toBe('solid');
});

test('browser sends no merchant credential and renders no private backend fields', async ({ page }) => {
  const authorization: string[] = [];
  page.on('request', request => { if (request.headers().authorization) authorization.push(request.headers().authorization); });
  await page.goto('/disputes/PP-TEST');
  await page.getByRole('button', { name: 'Investigate with AI' }).click();
  await expect(page.getByText(run.run_id)).toBeVisible();
  expect(authorization).toEqual([]);
  const content = await page.content();
  expect(content).not.toContain('test-only-merchant-token');
  expect(content).not.toContain('must-not-reach-browser');
  expect(await page.evaluate(() => localStorage.length)).toBe(0);
});

test('renders unavailable optional fields instead of guessing values', async ({ page }) => {
  await page.route('**/api/disputes/PP-TEST', route => route.fulfill({ json: { ...dispute, response_deadline: null, amount: null, currency: null } }));
  await page.goto('/disputes/PP-TEST');
  await expect(page.getByText('Not provided', { exact: true })).toBeVisible();
  await expect(page.getByText('Not available', { exact: true })).toBeVisible();
});
