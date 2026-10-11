import type { Assessment, Dispute, Run } from '../lib/contracts';

export const dispute: Dispute = {
  dispute_id: 'PP-TEST', status: 'WAITING_FOR_BUYER_RESPONSE', lifecycle_stage: 'INQUIRY',
  reason: 'MERCHANDISE_OR_SERVICE_NOT_RECEIVED', amount: '10.00', currency: 'USD',
  response_deadline: '2026-10-30T04:33:35.822Z', seller_transaction_id: 'TEST-CAPTURE',
  requested_evidence_types: ['PROOF_OF_FULFILLMENT'], available_actions: ['send_message'],
};
export const assessment: Assessment = {
  dispute_id: 'PP-TEST', dispute_reason: dispute.reason!, risk: 'HIGH', requires_review: true,
  facts: [
    { fact_id: 'payment_completed', status: 'UNKNOWN', value: null, source: 'paypal:test-capture' },
    { fact_id: 'delivery_confirmed', status: 'MISSING', value: null, source: 'synthetic-shipment' },
    { fact_id: 'shipping_address_matches', status: 'VERIFIED', value: false, source: 'synthetic-comparison' },
    { fact_id: 'prior_refund_exists', status: 'VERIFIED', value: true, source: 'synthetic-refund-record' },
  ],
  supporting_fact_ids: [],
  rules: [
    { rule_id: 'shipping_address_matches', outcome: 'FAIL', fact_ids: ['shipping_address_matches'], explanation: 'Verified address mismatch.' },
    { rule_id: 'prior_refund_exists', outcome: 'FAIL', fact_ids: ['prior_refund_exists'], explanation: 'An existing refund does not support contesting.' },
  ],
  retrieved_policies: [],
};
export const run: Run = {
  run_id: '00000000-0000-4000-8000-000000000001', dispute_id: 'PP-TEST',
  investigation_status: 'NEEDS_REVIEW', approval_state: 'PENDING', execution_status: 'NOT_STARTED',
  assessment: { ...assessment,
    retrieved_policies: [{ policy_id: 'shipping', section_id: 'delivery',
      excerpt: '## Delivery\nSynthetic demo policy: check carrier records.', source_path: 'policies/shipping.md' }],
    recommendation: {
      model: 'test-model', api_status: 'OK', fallback: false,
      response: { recommendation: 'NEEDS_REVIEW', summary: 'The supplied evidence is insufficient to contest.',
        supporting_fact_ids: [], policy_refs: ['shipping#delivery'],
        missing_information: ['payment_completed', 'delivery_confirmed'] },
    },
  },
};
