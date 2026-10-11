import 'server-only';
import { parseAssessment, parseDispute, parseHistory, type Assessment, type Dispute, type History } from './contracts';

export const DEMO_ID = 'PP-DEMO-001';
export function publicDemoEnabled(): boolean {
  return process.env.DISPUTEPILOT_PUBLIC_DEMO === 'true';
}

const dispute: Dispute = {
  dispute_id: DEMO_ID, status: 'WAITING_FOR_SELLER_RESPONSE', lifecycle_stage: 'INQUIRY',
  reason: 'MERCHANDISE_OR_SERVICE_NOT_RECEIVED', amount: '10.00', currency: 'USD',
  response_deadline: null, seller_transaction_id: null,
  requested_evidence_types: ['PROOF_OF_FULFILLMENT'], available_actions: [],
};
const missing = ['shipment_record_exists', 'delivery_confirmed', 'shipping_address_matches',
  'merchant_policy_supports_contest', 'prior_refund_exists'];
const assessment: Assessment = {
  dispute_id: DEMO_ID, dispute_reason: dispute.reason!, risk: 'HIGH', requires_review: true,
  facts: [
    { fact_id: 'payment_completed', status: 'VERIFIED', value: true, source: 'Synthetic demo payment record. Not a real transaction.' },
    ...missing.map(fact_id => ({ fact_id, status: 'UNKNOWN' as const, value: null, source: 'Not checked in this synthetic example.' })),
  ],
  supporting_fact_ids: ['payment_completed'],
  rules: [
    { rule_id: 'payment_completed', outcome: 'PASS', fact_ids: ['payment_completed'], explanation: 'The synthetic payment record is marked completed. This does not establish delivery.' },
    ...missing.map(fact_id => ({ rule_id: fact_id, outcome: 'UNKNOWN' as const, fact_ids: [fact_id], explanation: 'No authoritative evidence is supplied for this check in the example.' })),
  ],
  retrieved_policies: [{
    policy_id: 'shipping', section_id: 'demo-delivery', source_path: 'frontend/lib/public-demo.ts',
    excerpt: 'Synthetic demo policy: review carrier confirmation when investigating a missing delivery. A payment record or shipping address alone does not establish delivery. This policy does not describe any actual shipment.',
  }],
  recommendation: {
    model: 'Scripted demonstration. No model request.', api_status: 'OK', fallback: false,
    response: {
      recommendation: 'NEEDS_REVIEW',
      summary: 'This synthetic example has a completed payment record, but shipment, delivery, address matching, policy support, and refund history remain unknown. Payment completion alone is insufficient to contest. Merchant review is required.',
      supporting_fact_ids: ['payment_completed'], adverse_fact_ids: [],
      policy_refs: ['shipping#demo-delivery'], missing_information: missing,
    },
  },
  agent_trace: [
    { tool: 'get_dispute', outcome: 'AVAILABLE' }, { tool: 'get_order', outcome: 'AVAILABLE' },
    { tool: 'get_shipping', outcome: 'UNAVAILABLE' }, { tool: 'search_policy', outcome: 'AVAILABLE' },
  ],
};
const history: History = {
  dispute_id: DEMO_ID, paypal_writes_enabled: false, approved_action: null,
  runs: [{
    run_id: '00000000-0000-4000-8000-000000000001', dispute_id: DEMO_ID, assessment,
    investigation_status: 'NEEDS_REVIEW', approval_state: 'PENDING', execution_status: 'NOT_STARTED',
    created_at: '2026-01-01T12:00:00Z', approved_at: null, executed_at: null,
    action_type: 'SEND_MESSAGE', message: 'Demonstration only. No message can be sent.',
    eligibility: 'INELIGIBLE', audit_events: [
      { event_type: 'INVESTIGATED', occurred_at: '2026-01-01T12:00:00Z', actor: 'Merchant' },
    ],
  }],
};

export function demoResponse(request: Request, id: string, operation: string[] = []): Response {
  const headers = { 'Cache-Control': 'no-store', 'X-DisputePilot-Demo': 'synthetic-read-only' };
  if (request.method !== 'GET') return Response.json({ error: 'Public demo is read-only. Mutations are disabled.' }, { status: 405, headers });
  if (id !== DEMO_ID || operation.length > 1) return Response.json({ error: 'Demo example not found.' }, { status: 404, headers });
  try {
    const action = operation[0] ?? '';
    const data = action === '' ? parseDispute(dispute) : action === 'assessment' ? parseAssessment(assessment) : action === 'history' ? parseHistory(history) : null;
    if (!data) return Response.json({ error: 'Demo operation not available.' }, { status: 404, headers });
    return Response.json({ ...data, demonstration: 'Synthetic example. No live APIs or model execution.' }, { headers });
  } catch {
    return Response.json({ error: 'Demo example unavailable. No upstream lookup will be attempted.' }, { status: 503, headers });
  }
}
