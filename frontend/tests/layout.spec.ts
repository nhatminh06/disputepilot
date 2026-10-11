import { expect, test } from '@playwright/test';
import { run } from './fixtures';

for (const width of [1440, 1280, 390]) {
  test(`case-file layout and saved review at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 1000 });
    const posts: string[] = [];
    page.on('request', request => { if (request.method() === 'POST') posts.push(request.url()); });
    await page.goto('/disputes/PP-TEST');
    await expect(page.getByRole('button', { name: 'Run investigation' })).toBeEnabled();
    await page.screenshot({ path: `/tmp/disputepilot-redesign-initial-${width}.png`, fullPage: true });
    const saved = {
      ...structuredClone(run), created_at: '2026-10-10T10:00:00Z', approved_at: null, executed_at: null,
      action_type: 'SEND_MESSAGE', message: 'Synthetic test message.', eligibility: 'INELIGIBLE',
      audit_events: [{ event_type: 'INVESTIGATED', occurred_at: '2026-10-10T10:00:00Z', actor: 'Merchant' }],
    };
    saved.assessment.agent_trace = [
      { tool: 'get_dispute', outcome: 'AVAILABLE' }, { tool: 'get_order', outcome: 'UNAVAILABLE' },
      { tool: 'get_shipping', outcome: 'UNAVAILABLE' }, { tool: 'search_policy', outcome: 'AVAILABLE' },
    ];
    saved.assessment.recommendation!.attempts = 2;
    await page.route('**/api/disputes/PP-TEST/history', route => route.fulfill({ json: {
      dispute_id: 'PP-TEST', runs: [saved], approved_action: null, paypal_writes_enabled: false,
    } }));
    await page.reload();
    await expect(page.getByRole('heading', { name: 'Needs review', exact: true })).toBeVisible();
    await expect(page.locator('.history-row')).toHaveAttribute('aria-pressed', 'true');
    await expect(page.getByRole('region', { name: 'Audit trail' })).toContainText('INVESTIGATED');
    await expect(page.getByText('Demo mode: PayPal actions disabled', { exact: true })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Review message for approval' })).toHaveCount(0);
    const metrics = page.locator('.technical-details');
    await expect(metrics).not.toHaveAttribute('open');
    await metrics.getByText('Model and usage').click();
    await expect(metrics.locator('dd')).toHaveText(['test-model', '2', '4']);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    const evidence = await page.locator('.evidence-card').boundingBox();
    const recommendation = await page.locator('.ai-card').boundingBox();
    if (width >= 1280) {
      expect(evidence!.width / recommendation!.width).toBeGreaterThan(1.4);
      expect(Math.abs(evidence!.y - recommendation!.y)).toBeLessThan(2);
    } else {
      expect(recommendation!.y).toBeGreaterThan(evidence!.y + evidence!.height);
    }
    await page.evaluate(() => window.scrollTo({ top: 0, behavior: 'instant' }));
    await page.screenshot({ path: `/tmp/disputepilot-redesign-synthetic-${width}.png`, fullPage: true });
    expect(posts).toEqual([]);
  });
}
