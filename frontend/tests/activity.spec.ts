import { expect, test, type Page } from '@playwright/test';
import { parseRun, type Run } from '../lib/contracts';
import { run } from './fixtures';

function agentRun(): Run {
  const result = structuredClone(run);
  result.assessment.agent_trace = [
    { tool: 'get_dispute', outcome: 'AVAILABLE' },
    { tool: 'get_order', outcome: 'UNAVAILABLE' },
    { tool: 'get_shipping', outcome: 'UNAVAILABLE' },
    { tool: 'search_policy', outcome: 'AVAILABLE' },
  ];
  result.assessment.recommendation!.attempts = 2;
  result.assessment.recommendation!.usage = [{ total_token_count: 895 }, { total_token_count: 1461 }];
  return result;
}
async function show(page: Page, result: Run) {
  await page.route('**/api/disputes/PP-TEST/investigate', route => route.fulfill({ status: 201, json: result }));
  await page.goto('/disputes/PP-TEST');
  await page.getByRole('button', { name: 'Run investigation' }).click();
  await expect(page.getByText(result.run_id)).toBeVisible();
  return page.getByRole('region', { name: 'Agent activity' });
}

test('four actual tools retain execution order, outcomes and available metadata', async ({ page }) => {
  const panel = await show(page, agentRun());
  await expect(panel.locator('li h3')).toHaveText(['Read PayPal dispute', 'Check payment evidence', 'Check shipping evidence', 'Search merchant policies']);
  await expect(panel.locator('li code')).toHaveText(['get_dispute', 'get_order', 'get_shipping', 'search_policy']);
  await expect(panel.locator('.activity-order')).toHaveText(['1', '2', '3', '4']);
  await expect(panel.getByText('AVAILABLE', { exact: true })).toHaveCount(2);
  await expect(panel.getByText('UNAVAILABLE', { exact: true })).toHaveCount(2);
  await expect(panel.getByText(/does not establish that a payment/)).toHaveCount(2);
  await expect(panel.locator('dd')).toHaveText(['test-model', '2', '4', '2,356']);
  await expect(panel).not.toContainText('9.456');
});

for (const status of ['API_ERROR', 'TOOL_LIMIT', 'ITERATION_LIMIT', 'TIMEOUT']) {
  test(`agent ${status} retains partial trace and reports fallback`, async ({ page }) => {
    const result = agentRun();
    result.assessment.recommendation!.api_status = status;
    result.assessment.recommendation!.fallback = true;
    result.assessment.agent_trace = [{ tool: 'get_dispute', outcome: 'REJECTED' }];
    const panel = await show(page, result);
    await expect(panel).toContainText(`Safe fallback returned (${status})`);
    await expect(panel).toContainText('The tool request was rejected');
  });
}

test('missing trace preserves agent-disabled recommendation without invented calls', async ({ page }) => {
  const panel = await show(page, run);
  await expect(panel).toContainText('No tool-calling trace was returned');
  await expect(panel.locator('li')).toHaveCount(0);
  await expect(panel).not.toContainText('Recorded tool calls');
  await expect(page.getByRole('heading', { name: 'Needs review', exact: true })).toBeVisible();
});
test('empty trace reports zero calls without invented steps', async ({ page }) => {
  const result = agentRun(); result.assessment.agent_trace = [];
  const panel = await show(page, result);
  await expect(panel.locator('li')).toHaveCount(0);
  await expect(panel.locator('dd')).toHaveText(['test-model', '2', '0', '2,356']);
});
test('duplicate tool names remain separate ordered steps', async ({ page }) => {
  const result = agentRun();
  result.assessment.agent_trace = [{ tool: 'search_policy', outcome: 'UNAVAILABLE' }, { tool: 'search_policy', outcome: 'AVAILABLE' }];
  const panel = await show(page, result);
  await expect(panel.locator('li code')).toHaveText(['search_policy', 'search_policy']);
  await expect(panel.locator('li .badge')).toHaveText(['UNAVAILABLE', 'AVAILABLE']);
});
test('untrusted trace is allowlisted and arbitrary output is discarded', async ({ page }) => {
  const result = agentRun();
  result.assessment.agent_trace = [{ tool: '<img src=x onerror=alert(1)>', outcome: 'buyer@example.com' }];
  const projected = parseRun({ ...result, assessment: { ...result.assessment, agent_trace: [{ ...result.assessment.agent_trace[0], output: 'private-output' }] } });
  expect(projected.assessment.agent_trace).toEqual([{ tool: 'UNKNOWN', outcome: 'UNKNOWN' }]);
  const panel = await show(page, result);
  await expect(panel).toContainText('Unrecognized tool');
  await expect(panel.locator('img, script')).toHaveCount(0);
  await expect(panel).not.toContainText('buyer@example.com');
  await expect(panel).not.toContainText('private-output');
});
for (const width of [1440, 390]) {
  test(`activity layout at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 1000 });
    const panel = await show(page, agentRun());
    await panel.scrollIntoViewIfNeeded();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await expect(panel.locator('li')).toHaveCount(4);
    await page.screenshot({ path: `/tmp/disputepilot-agent-activity-${width}.png`, fullPage: true });
  });
}
