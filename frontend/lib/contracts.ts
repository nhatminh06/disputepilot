export interface Dispute {
  dispute_id: string;
  status: string | null;
  lifecycle_stage: string | null;
  reason: string | null;
  amount: string | null;
  currency: string | null;
  response_deadline: string | null;
  seller_transaction_id: string | null;
  requested_evidence_types: string[];
  available_actions: string[];
}

export interface Fact {
  fact_id: string;
  status: 'VERIFIED' | 'MISSING' | 'UNKNOWN';
  value: string | boolean | null;
  source: string;
}
export interface Rule {
  rule_id: string;
  outcome: 'PASS' | 'FAIL' | 'UNKNOWN';
  fact_ids: string[];
  explanation: string;
}
export interface Policy {
  policy_id: string;
  section_id: string;
  excerpt: string;
  source_path: string;
}
export interface Recommendation {
  attempts?: number;
  usage?: { total_token_count?: number }[];
  model: string;
  api_status: string;
  fallback: boolean;
  response: {
    recommendation: 'CONTEST' | 'REFUND' | 'NEEDS_REVIEW';
    summary: string;
    supporting_fact_ids: string[];
    policy_refs: string[];
    missing_information: string[];
  };
}
export interface Assessment {
  agent_trace?: { tool: string; outcome: string }[];
  dispute_id: string;
  dispute_reason: string;
  risk: 'LOW' | 'MEDIUM' | 'HIGH';
  requires_review: boolean;
  facts: Fact[];
  supporting_fact_ids: string[];
  rules: Rule[];
  retrieved_policies: Policy[];
  recommendation?: Recommendation;
}
export interface Run {
  run_id: string;
  dispute_id: string;
  assessment: Assessment;
  investigation_status: string;
  approval_state: string;
  execution_status: string;
}

function object(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error('Invalid response');
  return value as Record<string, unknown>;
}
function string(value: unknown): string {
  if (typeof value !== 'string') throw new Error('Invalid response');
  return value;
}
function boolean(value: unknown): boolean {
  if (typeof value !== 'boolean') throw new Error('Invalid response');
  return value;
}
function count(value: unknown): number | undefined {
  return typeof value === 'number' && Number.isSafeInteger(value) && value >= 0 ? value : undefined;
}
function traceLabel(value: unknown, allowed: string[]): string {
  return typeof value === 'string' && allowed.includes(value) ? value : 'UNKNOWN';
}
function nullable(value: unknown): string | null { return value == null ? null : string(value); }
function list<T>(value: unknown, parse: (item: unknown) => T): T[] {
  if (!Array.isArray(value)) throw new Error('Invalid response');
  return value.map(parse);
}
function choice<T extends string>(value: unknown, options: readonly T[]): T {
  const text = string(value);
  const match = options.find(option => option === text);
  if (!match) throw new Error('Invalid response');
  return match;
}

export function parseDispute(value: unknown): Dispute {
  const d = object(value);
  return {
    dispute_id: string(d.dispute_id), status: nullable(d.status),
    lifecycle_stage: nullable(d.lifecycle_stage), reason: nullable(d.reason),
    amount: nullable(d.amount), currency: nullable(d.currency),
    response_deadline: nullable(d.response_deadline),
    seller_transaction_id: nullable(d.seller_transaction_id),
    requested_evidence_types: list(d.requested_evidence_types, string),
    available_actions: list(d.available_actions, string),
  };
}

export function parseAssessment(value: unknown): Assessment {
  const a = object(value);
  const assessment: Assessment = {
    dispute_id: string(a.dispute_id), dispute_reason: string(a.dispute_reason),
    risk: choice(a.risk, ['LOW', 'MEDIUM', 'HIGH'] as const),
    requires_review: boolean(a.requires_review),
    facts: list(a.facts, item => {
      const f = object(item);
      return { fact_id: string(f.fact_id),
        status: choice(f.status, ['VERIFIED', 'MISSING', 'UNKNOWN'] as const),
        value: typeof f.value === 'boolean' ? f.value : nullable(f.value),
        source: string(f.source) };
    }),
    supporting_fact_ids: list(a.supporting_fact_ids, string),
    rules: list(a.rules, item => {
      const r = object(item);
      return { rule_id: string(r.rule_id),
        outcome: choice(r.outcome, ['PASS', 'FAIL', 'UNKNOWN'] as const),
        fact_ids: list(r.fact_ids, string), explanation: string(r.explanation) };
    }),
    retrieved_policies: list(a.retrieved_policies ?? [], item => {
      const p = object(item);
      return { policy_id: string(p.policy_id), section_id: string(p.section_id),
        excerpt: string(p.excerpt), source_path: string(p.source_path) };
    }),
  };
  if (Array.isArray(a.agent_trace)) {
    assessment.agent_trace = a.agent_trace.slice(0, 6).map(item => {
      const entry = item && typeof item === 'object' ? item as Record<string, unknown> : {};
      return {
        tool: traceLabel(entry.tool, ['get_dispute', 'get_order', 'get_shipping', 'search_policy']),
        outcome: traceLabel(entry.outcome, ['AVAILABLE', 'UNAVAILABLE', 'REJECTED', 'TIMEOUT', 'RUNNING', 'ERROR']),
      };
    });
  }
  if (a.recommendation != null) {
    const g = object(a.recommendation);
    const r = object(g.response);
    assessment.recommendation = {
      attempts: count(g.attempts),
      usage: Array.isArray(g.usage) ? g.usage.slice(0, 4).map(item => ({
        total_token_count: count(item && typeof item === 'object' ? item.total_token_count : undefined),
      })) : undefined,
      model: string(g.model), api_status: string(g.api_status), fallback: boolean(g.fallback),
      response: {
        recommendation: choice(r.recommendation, ['CONTEST', 'REFUND', 'NEEDS_REVIEW'] as const),
        summary: string(r.summary), supporting_fact_ids: list(r.supporting_fact_ids, string),
        policy_refs: list(r.policy_refs, string), missing_information: list(r.missing_information, string),
      },
    };
    const response = assessment.recommendation.response;
    const refs = assessment.retrieved_policies.map(p => `${p.policy_id}#${p.section_id}`);
    if (response.supporting_fact_ids.some(id => !assessment.supporting_fact_ids.includes(id)) ||
        response.policy_refs.some(ref => !refs.includes(ref))) throw new Error('Invalid citations');
  }
  return assessment;
}

export function parseRun(value: unknown): Run {
  const r = object(value);
  const assessment = parseAssessment(r.assessment);
  if (!assessment.recommendation || assessment.dispute_id !== r.dispute_id) throw new Error('Invalid run');
  return { run_id: string(r.run_id), dispute_id: string(r.dispute_id), assessment,
    investigation_status: string(r.investigation_status),
    approval_state: string(r.approval_state), execution_status: string(r.execution_status) };
}
