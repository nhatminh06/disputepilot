import { CircleCheck, CircleHelp, TriangleAlert } from 'lucide-react';
import type { Run } from '@/lib/contracts';

const names: Record<string, string> = {
  get_dispute: 'Read PayPal dispute', get_order: 'Check payment evidence',
  get_shipping: 'Check shipping evidence', search_policy: 'Search merchant policies',
};
const explanations: Record<string, string> = {
  AVAILABLE: 'The tool reported information available. This does not change verified evidence or risk.',
  UNAVAILABLE: 'The tool could not provide evidence. This does not establish that a payment, shipment, or delivery is absent.',
  REJECTED: 'The tool request was rejected. No supporting evidence is established by this step.',
  TIMEOUT: 'The step reached its time limit. Its result remains unverified.',
  ERROR: 'The tool reported an error. No supporting evidence is established by this step.',
  RUNNING: 'The returned record has no final outcome for this step.',
  UNKNOWN: 'No recognized outcome was returned. Review is required.',
};

export default function AgentActivity({ run, busy }: { run: Run | null; busy: boolean }) {
  const trace = run?.assessment.agent_trace;
  const recommendation = run?.assessment.recommendation;
  const status = recommendation && ['OK', 'TOOL_LIMIT', 'ITERATION_LIMIT', 'TIMEOUT', 'API_ERROR', 'TRANSPORT_ERROR', 'VALIDATION_FAILED', 'MISSING_CREDENTIALS'].includes(recommendation.api_status) ? recommendation.api_status : 'UNKNOWN';
  const usage = recommendation?.usage;
  const tokens = usage?.length && usage.every(item => item.total_token_count !== undefined)
    ? usage.reduce((sum, item) => sum + item.total_token_count!, 0) : undefined;
  return <section className="card agent-activity" aria-labelledby="activity-title">
    <div className="card-heading"><h2 id="activity-title">Agent activity</h2><span className="small muted">Read-only tools</span></div>
    {recommendation && <details className="technical-details"><summary>Model and usage</summary><dl className="activity-metrics">
      <div><dt>Model</dt><dd>{recommendation.model}</dd></div>
      {recommendation.attempts !== undefined && <div><dt>Model requests</dt><dd>{recommendation.attempts}</dd></div>}
      {trace !== undefined && <div><dt>Recorded tool calls</dt><dd>{trace.length}</dd></div>}
      {tokens !== undefined && <div><dt>Total tokens</dt><dd>{tokens.toLocaleString('en-US')}</dd></div>}
    </dl></details>}
    {recommendation?.fallback && <p className="activity-warning"><TriangleAlert size={16} /><span>Safe fallback returned ({status}). The investigation did not produce a validated model recommendation. Recorded steps below are not proof of a successful investigation.</span></p>}
    {trace?.length ? <ol className="activity-timeline">{trace.map((entry, index) => {
      const Icon = entry.outcome === 'AVAILABLE' ? CircleCheck : entry.outcome === 'UNAVAILABLE' ? CircleHelp : TriangleAlert;
      return <li key={index}>
        <span className="activity-order" aria-label={`Step ${index + 1}`}>{index + 1}</span>
        <div className="activity-step"><div className="activity-step-heading"><h3>{names[entry.tool] ?? 'Unrecognized tool'}</h3><span className={`badge ${entry.outcome === 'AVAILABLE' ? 'badge-blue' : 'badge-neutral'}`}><Icon size={12} />{entry.outcome}</span></div>
          <code>{entry.tool}</code><p>{explanations[entry.outcome] ?? explanations.UNKNOWN}</p>
        </div>
      </li>;
    })}</ol> : <p className="empty-inline">{busy ? 'Investigation in progress. Tool activity will appear when the backend returns its record.' : run ? 'No tool-calling trace was returned. The recommendation flow can run without agent tools; no tool executions are shown.' : 'Run an investigation to see any tool activity returned by the backend.'}</p>}
    <div className="card-footnote"><span>Backend-reported activity only. Tool availability is not proof of fulfillment. Merchant approval remains separate.</span></div>
  </section>;
}
