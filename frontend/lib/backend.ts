import 'server-only';
import { parseAssessment, parseDispute, parseRun } from './contracts';

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
  if (!['', 'assessment', 'investigate'].includes(action)) return error(404, 'Operation not available.');
  if (request.method !== (investigate ? 'POST' : 'GET')) return error(405, 'Method not permitted.');
  if (investigate && (!origin || request.headers.get('x-disputepilot-request') !== 'investigate')) {
    return error(403, 'A same-origin investigation request is required.');
  }
  const base = process.env.DISPUTEPILOT_API_URL || 'http://127.0.0.1:8000';
  // No user-controlled target and no redirects carrying the merchant credential.
  if (!/^http:\/\/127\.0\.0\.1:800[01]$/.test(base)) return error(503, 'Local backend configuration is invalid.');
  const token = process.env.DEV_MERCHANT_TOKEN;
  if (!token || token.length < 32) return error(503, 'Development merchant credential is not configured.');
  try {
    const upstream = await fetch(`${base}/api/disputes/${id}${action ? `/${action}` : ''}`, {
      method: investigate ? 'POST' : 'GET', cache: 'no-store', redirect: 'error',
      headers: { Authorization: `Bearer ${token}`, Accept: 'application/json' },
      signal: AbortSignal.timeout(120_000),
    });
    if (!upstream.ok) {
      if ([401, 403].includes(upstream.status)) return error(upstream.status, 'Merchant authentication failed. Check server credentials.');
      if (upstream.status === 404) return error(404, 'This dispute was not found.');
      return error(upstream.status >= 500 ? upstream.status : 502,
        `Backend request failed (HTTP ${upstream.status}). ${investigate ? 'The investigation outcome may be unknown. Do not automatically resubmit.' : 'Please check the backend and PayPal connection.'}`);
    }
    const raw: unknown = await upstream.json();
    const data = investigate ? parseRun(raw) : action === 'assessment' ? parseAssessment(raw) : parseDispute(raw);
    if (data.dispute_id !== id) return error(502, 'Backend returned a different dispute.');
    return Response.json(data, { status: investigate ? 201 : 200, headers });
  } catch {
    return error(502, investigate
      ? 'Investigation outcome unavailable. It may have been persisted. Check the backend before starting another run.'
      : 'Cannot load dispute data. Check the local backend connection and response.');
  }
}
