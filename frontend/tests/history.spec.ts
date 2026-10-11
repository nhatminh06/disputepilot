import { expect, test, type Page } from '@playwright/test';
import { parseHistory, type History, type SavedRun } from '../lib/contracts';
import { run } from './fixtures';

function saved(): SavedRun {
  return { ...structuredClone(run), created_at: '2026-10-10T10:00:00Z', approved_at: null, executed_at: null,
    action_type: 'SEND_MESSAGE', message: 'Synthetic test message. No shipment or delivery confirmation is available.',
    eligibility: 'ELIGIBLE', audit_events: [{ event_type: 'INVESTIGATED', occurred_at: '2026-10-10T10:00:00Z', actor: 'Merchant' }] };
}
function history(item = saved()): History { return { dispute_id: 'PP-TEST', runs: [item], approved_action: null, paypal_writes_enabled: true }; }
async function setup(page: Page, state: History) {
  await page.route('**/api/disputes/PP-TEST/history', route => route.fulfill({ json: state }));
  await page.goto('/disputes/PP-TEST');
  await expect(page.getByRole('button', { name: 'Review message for approval' })).toBeVisible();
}
async function open(page: Page) {
  await page.getByRole('button', { name: 'Review message for approval' }).click();
  return page.getByRole('dialog', { name: 'Approve PayPal message' });
}

test('history and audit persist after reload without a new investigation', async ({ page }) => {
  let posts = 0; page.on('request', r => { if (r.method() === 'POST') posts++; });
  await setup(page, history());
  await page.reload();
  await expect(page.getByRole('region', { name: 'Investigation history' })).toContainText(run.run_id);
  await expect(page.getByRole('region', { name: 'Audit trail' })).toContainText('INVESTIGATED');
  await expect(page.getByRole('region', { name: 'Merchant approval' })).toContainText('PENDING');
  await expect(page.getByRole('region', { name: 'Merchant approval' })).toContainText('NOT_STARTED');
  expect(posts).toBe(0);
});

test('dialog shows exact message and requires unchecked confirmation, Escape restores focus', async ({ page }) => {
  const state = history(); await setup(page, state);
  const dialog = await open(page);
  await expect(dialog.locator('blockquote')).toHaveText(state.runs[0].message);
  await expect(dialog.getByRole('checkbox')).not.toBeChecked();
  await expect(dialog.getByRole('button', { name: 'Confirm and send message' })).toBeDisabled();
  await page.keyboard.press('Escape');
  await expect(dialog).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Review message for approval' })).toBeFocused();
  await open(page);
  await page.getByRole('button', { name: 'Cancel', exact: true }).click();
  await expect(page.getByRole('dialog')).toHaveCount(0);
});

test('single approval sends exact body and success requires refreshed persisted state', async ({ page }) => {
  const state = history(); let calls = 0;
  let release!: () => void;
  const pending = new Promise<void>(resolve => { release = resolve; });
  await page.route('**/api/disputes/PP-TEST/approve', async route => {
    calls++; expect(route.request().postDataJSON()).toEqual({ run_id: run.run_id, action_type: 'SEND_MESSAGE', confirmed: true });
    expect(route.request().headers().authorization).toBeUndefined();
    await pending;
    Object.assign(state.runs[0], { approval_state: 'APPROVED', execution_status: 'SUCCEEDED', eligibility: 'ALREADY_SENT', executed_at: '2026-10-10T10:01:00Z' });
    state.runs[0].audit_events.push({ event_type: 'SUCCEEDED', occurred_at: '2026-10-10T10:01:00Z', actor: 'Merchant' });
    await route.fulfill({ json: { refresh_required: true } });
  });
  await setup(page, state); const dialog = await open(page);
  await dialog.getByRole('checkbox').check();
  await dialog.getByRole('button', { name: 'Confirm and send message' }).click();
  await expect(page.getByRole('button', { name: 'Review message for approval' })).toHaveCount(0);
  await expect(page.getByRole('region', { name: 'Merchant approval' })).not.toContainText('Successful execution recorded');
  release();
  await expect(page.getByRole('region', { name: 'Merchant approval' })).toContainText('Successful execution recorded');
  await expect(page.getByRole('region', { name: 'Audit trail' })).toContainText('SUCCEEDED');
  expect(calls).toBe(1);
});

for (const outcome of ['conflict', 'network', 'reconciliation', 'unavailable-history']) {
  test(`${outcome} never retries approval`, async ({ page }) => {
    const state = history(); let calls = 0;
    await setup(page, state);
    await page.route('**/api/disputes/PP-TEST/approve', async route => {
      calls++;
      if (outcome === 'reconciliation') Object.assign(state.runs[0], { approval_state: 'APPROVED', execution_status: 'REQUIRES_RECONCILIATION', eligibility: 'REQUIRES_RECONCILIATION' });
      if (outcome === 'unavailable-history') await page.route('**/api/disputes/PP-TEST/history', r => r.fulfill({ status: 503, json: {} }));
      if (outcome === 'network') await route.abort();
      else await route.fulfill({ status: outcome === 'conflict' ? 409 : 503, json: {} });
    });
    const dialog = await open(page); await dialog.getByRole('checkbox').check();
    await dialog.getByRole('button', { name: 'Confirm and send message' }).click();
    const panel = page.getByRole('region', { name: 'Merchant approval' });
    await expect(panel).toContainText(outcome === 'conflict' ? 'Approval conflict' : 'outcome');
    await expect(page.getByRole('button', { name: 'Review message for approval' })).toHaveCount(0);
    await page.getByRole('button', { name: 'Refresh history' }).click();
    await expect(page.getByRole('button', { name: 'Review message for approval' })).toHaveCount(0);
    expect(calls).toBe(1);
  });
}

test('historical approved action blocks a newer pending run', async ({ page }) => {
  const state = history(); state.runs[0].eligibility = 'ALREADY_SENT';
  state.approved_action = { run_id: 'older-run', execution_status: 'SUCCEEDED', approved_at: '2026-10-09T10:00:00Z', executed_at: '2026-10-09T10:01:00Z' };
  await page.route('**/api/disputes/PP-TEST/history', r => r.fulfill({ json: state }));
  await page.goto('/disputes/PP-TEST');
  await expect(page.getByRole('region', { name: 'Investigation history' })).toContainText('Message already sent for this dispute');
  await expect(page.getByRole('button', { name: 'Review message for approval' })).toHaveCount(0);
});

test('mobile dialog is contained and traps keyboard focus', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await setup(page, history()); const dialog = await open(page);
  await page.keyboard.press('Tab');
  expect(await page.evaluate(() => !!document.activeElement?.closest('dialog'))).toBe(true);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await dialog.screenshot({ path: '/tmp/disputepilot-approval-dialog-mobile.png' });
});

test('historical run without Gemini output does not invent a recommendation', async ({ page }) => {
  const state = history(); delete state.runs[0].assessment.recommendation;
  await setup(page, state);
  await expect(page.getByRole('region', { name: 'Investigation', exact: true })).toContainText('No recommendation was stored');
  await expect(page.getByRole('button', { name: 'Run investigation' })).toHaveCount(0);
  await page.getByRole('button', { name: 'Prepare a new investigation' }).click();
  await expect(page.getByRole('button', { name: 'Run investigation' })).toBeEnabled();
});

for (const width of [1440, 390]) {
  test(`demo mode prevents pending approval at ${width}px`, async ({ page }) => {
    const state = history(); state.paypal_writes_enabled = false;
    let approvals = 0;
    page.on('request', request => { if (request.url().endsWith('/approve')) approvals++; });
    await page.setViewportSize({ width, height: 900 });
    await page.route('**/api/disputes/PP-TEST/history', route => route.fulfill({ json: state }));
    await page.goto('/disputes/PP-TEST');
    await expect(page.getByText('Demo mode: PayPal actions disabled', { exact: true })).toBeVisible();
    await expect(page.getByRole('region', { name: 'Merchant approval' })).not.toContainText('Locally eligible');
    await expect(page.getByRole('button', { name: 'Review message for approval' })).toHaveCount(0);
    await expect(page.getByRole('button', { name: 'Confirm and send message' })).toHaveCount(0);
    await expect(page.getByRole('region', { name: 'Audit trail' })).toContainText('INVESTIGATED');
    await page.getByRole('button', { name: 'Prepare a new investigation' }).click();
    await expect(page.getByRole('button', { name: 'Run investigation' })).toBeEnabled();
    expect(approvals).toBe(0);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  });
}

test('demo mode preserves historical message success', async ({ page }) => {
  const state = history(); state.paypal_writes_enabled = false;
  state.runs[0].eligibility = 'ALREADY_SENT';
  state.approved_action = { run_id: 'older-run', execution_status: 'SUCCEEDED', approved_at: null, executed_at: '2026-01-02T00:00:00Z' };
  await page.route('**/api/disputes/PP-TEST/history', route => route.fulfill({ json: state }));
  await page.goto('/disputes/PP-TEST');
  await expect(page.getByText('Demo mode: PayPal actions disabled', { exact: true })).toBeVisible();
  await expect(page.getByRole('region', { name: 'Investigation history' })).toContainText('Message already sent');
  await expect(page.getByRole('button', { name: 'Review message for approval' })).toHaveCount(0);
});

test('missing or malformed capability cannot enable execution', () => {
  for (const capability of [undefined, null, 'true', 1, false]) {
    expect(parseHistory({ ...history(), paypal_writes_enabled: capability }).paypal_writes_enabled).toBe(false);
  }
});
