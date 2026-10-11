import { test, expect } from '@playwright/test';

const origin = 'http://127.0.0.1:3001';
const investigateHeaders = { Origin: origin, 'X-DisputePilot-Request': 'investigate' };

test('proxy authenticates server-side and strips unneeded backend fields', async ({ request }) => {
  const response = await request.post('/api/disputes/PP-TEST/investigate', {
    headers: { ...investigateHeaders, Authorization: 'Bearer untrusted-browser-token' },
    data: { approved_by: 'forged-identity' },
  });
  expect(response.status()).toBe(201);
  expect(response.headers()['cache-control']).toBe('no-store');
  const body = await response.text();
  expect(body).not.toMatch(/test-only-merchant-token|access_token|private_metadata|forged-identity/);
});

test('rejects cross-origin, missing-origin, and missing custom-header investigations', async ({ request }) => {
  const cases: Record<string, string>[] = [
    { Origin: 'https://attacker.invalid', 'X-DisputePilot-Request': 'investigate' },
    { 'X-DisputePilot-Request': 'investigate' }, { Origin: origin },
  ];
  for (const headers of cases) {
    expect((await request.post('/api/disputes/PP-TEST/investigate', { headers })).status()).toBe(403);
  }
});

test('rejects untrusted host and cross-site reads', async ({ request }) => {
  expect((await request.get('/api/disputes/PP-TEST', { headers: { Host: 'attacker.invalid:3001' } })).status()).toBe(403);
  expect((await request.get('/api/disputes/PP-TEST', { headers: { 'Sec-Fetch-Site': 'cross-site' } })).status()).toBe(403);
});

test('there are no proxied approval or financial action routes', async ({ request }) => {
  for (const action of ['approve', 'refund', 'send-message', 'capture', 'assessment/approve']) {
    expect((await request.post(`/api/disputes/PP-TEST/${action}`, { headers: investigateHeaders })).status()).toBe(404);
  }
  expect((await request.get('/api/disputes/PP-TEST/investigate')).status()).toBe(405);
  expect((await request.post('/api/disputes/PP-TEST/assessment', { headers: investigateHeaders })).status()).toBe(405);
});

test('sanitizes upstream errors and refuses malformed responses and redirects', async ({ request }) => {
  for (const id of ['PP-FAILURE', 'PP-MALFORMED', 'PP-REDIRECT', 'PP-UNAUTHORIZED']) {
    const response = await request.get(`/api/disputes/${id}`);
    expect(response.ok()).toBe(false);
    expect(await response.text()).not.toContain('test-only-merchant-token');
  }
});
