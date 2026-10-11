import 'server-only';
import { parseAssessment, parseDispute, parseHistory, parseRun } from './contracts';
import { allowedBackend } from './upstream';

const headers = { 'Cache-Control': 'no-store', 'Content-Type': 'application/json' };
function error(status: number, message: string): Response {
  return Response.json({ error: message }, { status, headers });
}

export async function proxy(request: Request, id: string, operation: string[] = []): Promise<Response> {
  const host = request.headers.get('host');
  const allowedHosts = ['localhost:3000', '127.0.0.1:3000', 'localhost:3001', '127.0.0.1:3001'];
  if (!host || !allowedHosts.includes(host)) return error(403, 'This workspace is local-only.');
  const origin = request.headers.get('origin');
  if ((origin && origin !== `http://${host}`) || request.headers.get('sec-fetch-site') === 'cross-site') {
    return error(403, 'Cross-origin requests are not permitted.');
  }
  if (!/^[A-Z0-9-]{1,255}$/.test(id)) return error(400, 'Invalid dispute ID.');
  const action = operation.join('/');
  const investigate = action === 'investigate';
  const approve = action === 'approve';
  const post = investigate || approve;
  if (!['', 'assessment', 'investigate', 'history', 'approve'].includes(action)) return error(404, 'Operation not available.');
  if (request.method !== (post ? 'POST' : 'GET')) return error(405, 'Method not permitted.');
  if (post && (!origin || request.headers.get('x-disputepilot-request') !== action)) {
    return error(403, 'A same-origin action request is required.');
  }
  let body: string | undefined;
  if (approve) {
    const text = await request.text();
    if (text.length > 1024) return error(422, 'Invalid approval request.');
    try {
      const input: unknown = JSON.parse(text);
      if (!input || typeof input !== 'object' || Array.isArray(input)) throw new Error('Invalid request');
      const r = input as Record<string, unknown>;
      if (Object.keys(r).sort().join(',') !== 'action_type,confirmed,run_id' ||
          r.action_type !== 'SEND_MESSAGE' || r.confirmed !== true || typeof r.run_id !== 'string' ||
          !/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(r.run_id)) throw new Error('Invalid request');
      body = JSON.stringify(r);
    } catch { return error(422, 'Explicit confirmation of a SEND_MESSAGE run is required.'); }
  }
  const base = process.env.DISPUTEPILOT_API_URL || 'http://127.0.0.1:8000';
  // No user-controlled target and no redirects carrying the merchant credential.
  if (!allowedBackend(base, process.env.DISPUTEPILOT_COMPOSE === 'true')) return error(503, 'Local backend configuration is invalid.');
  const token = process.env.DEV_MERCHANT_TOKEN;
  if (!token || token.length < 32) return error(503, 'Development merchant credential is not configured.');
  try {
    const path = approve ? `/disputes/${id}/approve` : `/api/disputes/${id}${action ? `/${action}` : ''}`;
    const upstream = await fetch(`${base}${path}`, {
      method: post ? 'POST' : 'GET', body, cache: 'no-store', redirect: 'error',
      headers: { Authorization: `Bearer ${token}`, Accept: 'application/json', ...(approve ? { 'Content-Type': 'application/json' } : {}) },
      signal: AbortSignal.timeout(120_000),
    });
    if (!upstream.ok) {
      if (approve) {
        const messages: Record<number, string> = {
          401: 'Merchant authentication is required.', 403: 'This merchant cannot approve this action.',
          404: 'The stored run was not found.', 409: 'Approval conflict. The action may already be reserved or no longer permitted.',
          422: 'Approval confirmation or action is invalid.',
        };
        return error(upstream.status, `${messages[upstream.status] ?? 'Execution outcome may be unknown.'} Refresh history. Do not resubmit automatically.`);
      }
      if ([401, 403].includes(upstream.status)) return error(upstream.status, 'Merchant authentication failed. Check server credentials.');
      if (upstream.status === 404) return error(404, 'This dispute was not found.');
      return error(upstream.status >= 500 ? upstream.status : 502,
        `Backend request failed (HTTP ${upstream.status}). ${investigate ? 'The investigation outcome may be unknown. Do not automatically resubmit.' : 'Please check the backend and PayPal connection.'}`);
    }
    // Execution is confirmed through a fresh history read, not an upstream response body.
    if (approve) return Response.json({ refresh_required: true }, { headers });
    const raw: unknown = await upstream.json();
    const data = investigate ? parseRun(raw) : action === 'history' ? parseHistory(raw) : action === 'assessment' ? parseAssessment(raw) : parseDispute(raw);
    if (data.dispute_id !== id) return error(502, 'Backend returned a different dispute.');
    return Response.json(data, { status: investigate ? 201 : 200, headers });
  } catch {
    if (approve) return error(502, 'Execution outcome unknown. Refresh history and verify the PayPal result before any further action. Do not retry.');
    return error(502, investigate
      ? 'Investigation outcome unavailable. It may have been persisted. Check the backend before starting another run.'
      : 'Cannot load dispute data. Check the local backend connection and response.');
  }
}
