import { createServer } from 'node:http';
import { dispute, assessment, run } from './fixtures.ts';

const token = 'test-only-merchant-token-not-a-secret-12345';
const server = createServer((request, response) => {
  const path = request.url || '';
  response.setHeader('Content-Type', 'application/json');
  if (path === '/health') { response.end('{}'); return; }
  if (request.headers.authorization !== `Bearer ${token}` || path.includes('PP-UNAUTHORIZED')) {
    response.writeHead(401); response.end(JSON.stringify({ detail: token })); return;
  }
  if (path.includes('PP-REDIRECT')) {
    response.writeHead(307, { Location: 'http://127.0.0.1:8001/forbidden' }); response.end(); return;
  }
  if (path.includes('PP-MALFORMED')) { response.end('{"wrong":true}'); return; }
  if (path.includes('PP-FAILURE')) { response.writeHead(502); response.end(JSON.stringify({ detail: token })); return; }
  if (path === '/disputes/PP-TEST/approve' && request.method === 'POST') {
    let body = '';
    request.on('data', chunk => { body += chunk; });
    request.on('end', () => {
      const expected = { run_id: run.run_id, action_type: 'SEND_MESSAGE', confirmed: true };
      const input = JSON.parse(body);
      if (JSON.stringify(input) !== JSON.stringify(expected)) response.writeHead(422);
      response.end(JSON.stringify({ execution_status: 'SUCCEEDED', paypal_result: { access_token: token } }));
    });
    return;
  }
  const match = /^\/api\/disputes\/(PP-TEST)(?:\/(assessment|investigate|history))?$/.exec(path);
  if (!match) { response.writeHead(404); response.end('{}'); return; }
  const action = match[2];
  if (action === 'history') {
    response.end(JSON.stringify({ dispute_id: 'PP-TEST', runs: [], approved_action: null })); return;
  }
  if (request.method !== (action === 'investigate' ? 'POST' : 'GET')) {
    response.writeHead(405); response.end('{}'); return;
  }
  response.writeHead(action === 'investigate' ? 201 : 200);
  response.end(JSON.stringify({ ...(action === 'investigate' ? run : action === 'assessment' ? assessment : dispute),
    access_token: token, private_metadata: 'must-not-reach-browser' }));
});
server.listen(8001, '127.0.0.1');
