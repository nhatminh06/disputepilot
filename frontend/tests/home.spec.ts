import { expect, test } from '@playwright/test';

test('root opens the existing case page without a write', async ({ page }) => {
  const posts: string[] = [];
  page.on('request', request => { if (request.method() === 'POST') posts.push(request.url()); });
  const response = await page.goto('/');
  expect(response?.status()).toBe(200);
  await page.getByLabel('PayPal dispute ID', { exact: true }).fill('PP-TEST');
  await page.getByRole('button', { name: 'Open dispute', exact: true }).click();
  await expect(page).toHaveURL(/\/disputes\/PP-TEST$/);
  await expect(page.getByRole('heading', { name: 'Item not received', exact: true })).toBeVisible();
  expect(posts).toEqual([]);
});

test('invalid identifiers stay on the entry page and mobile layout fits', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/?dispute_id=../../approve');
  await expect(page.getByRole('alert')).toContainText('Enter a valid dispute ID');
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});
