import { expect, test } from '@playwright/test';
import { adverseFactIds, parseAssessment } from '../lib/contracts';
import { run } from './fixtures';

test('historical recommendations load with empty adverse citations', () => {
  const parsed = parseAssessment(structuredClone(run.assessment));
  expect(parsed.recommendation!.response.adverse_fact_ids).toEqual([]);
  expect(run.assessment.recommendation!.response.adverse_fact_ids).toBeUndefined();
});

test('verified address mismatch and prior refund are adverse, not supporting', () => {
  const value = structuredClone(run.assessment);
  const ids = ['shipping_address_matches', 'prior_refund_exists'];
  value.recommendation!.response.adverse_fact_ids = ids;
  expect(adverseFactIds(value)).toEqual(ids);
  expect(parseAssessment(value).recommendation!.response.adverse_fact_ids).toEqual(ids);
  expect(value.supporting_fact_ids).toEqual([]);
});

for (const id of ['invented', 'payment_completed', 'delivery_confirmed']) {
  test(`rejects unsupported adverse citation: ${id}`, () => {
    const value = structuredClone(run.assessment);
    value.recommendation!.response.adverse_fact_ids = [id];
    expect(() => parseAssessment(value)).toThrow();
  });
}

test('rejects overlapping citation categories', () => {
  const value = structuredClone(run.assessment);
  value.supporting_fact_ids = ['prior_refund_exists'];
  value.recommendation!.response.supporting_fact_ids = ['prior_refund_exists'];
  value.recommendation!.response.adverse_fact_ids = ['prior_refund_exists'];
  expect(() => parseAssessment(value)).toThrow();
});

for (const width of [1440, 390]) {
  test(`renders adverse citations with caution and unchanged risk at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    const value = structuredClone(run);
    value.assessment.recommendation!.response.adverse_fact_ids = [
      'shipping_address_matches', 'prior_refund_exists',
    ];
    await page.route('**/api/disputes/PP-TEST/investigate', route => route.fulfill({ json: value, status: 201 }));
    await page.goto('/disputes/PP-TEST');
    await page.getByRole('button', { name: 'Run investigation' }).click();
    await expect(page.getByRole('heading', { name: 'Verified evidence requiring attention' })).toBeVisible();
    await expect(page.locator('.citation-list.adverse-label a')).toHaveCount(2);
    await expect(page.locator('.citation-list.adverse-label a').first()).toHaveAttribute('href', '#fact-shipping_address_matches');
    await expect(page.locator('.fact-adverse')).toHaveCount(2);
    await expect(page.getByText('High contesting risk')).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  });
}
