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

test('only the explicit approval route is allowed, not arbitrary financial actions', async ({ request }) => {
  for (const action of ['refund', 'send-message', 'capture', 'assessment/approve']) {
    expect((await request.post(`/api/disputes/PP-TEST/${action}`, { headers: investigateHeaders })).status()).toBe(404);
  }
  expect((await request.get('/api/disputes/PP-TEST/investigate')).status()).toBe(405);
  expect((await request.post('/api/disputes/PP-TEST/assessment', { headers: investigateHeaders })).status()).toBe(405);
});

test('approval requires same origin, explicit confirmation, and exact body', async ({ request }) => {
  const body = { run_id: '00000000-0000-4000-8000-000000000001', action_type: 'SEND_MESSAGE', confirmed: true };
  const invalidHeaders: Record<string, string>[] = [{}, { Origin: origin }, { Origin: 'https://attacker.invalid', 'X-DisputePilot-Request': 'approve' }];
  for (const headers of invalidHeaders) {
    expect((await request.post('/api/disputes/PP-TEST/approve', { headers, data: body })).status()).toBe(403);
  }
  const headers = { Origin: origin, 'X-DisputePilot-Request': 'approve' };
  for (const invalid of [{ ...body, confirmed: false }, { ...body, action_type: 'REFUND' }, { ...body, approved_by: 'forged' }]) {
    expect((await request.post('/api/disputes/PP-TEST/approve', { headers, data: invalid })).status()).toBe(422);
  }
  const response = await request.post('/api/disputes/PP-TEST/approve', { headers, data: body });
  expect(response.status()).toBe(200);
  expect(await response.json()).toEqual({ refresh_required: true });
});

test('sanitizes upstream errors and refuses malformed responses and redirects', async ({ request }) => {
  for (const id of ['PP-FAILURE', 'PP-MALFORMED', 'PP-REDIRECT', 'PP-UNAUTHORIZED']) {
    const response = await request.get(`/api/disputes/${id}`);
    expect(response.ok()).toBe(false);
    expect(await response.text()).not.toContain('test-only-merchant-token');
  }
});
