import { Clock3 } from 'lucide-react';
import type { SavedRun } from '@/lib/contracts';

export function timestamp(value: string | null): string {
  if (!value || !Number.isFinite(Date.parse(value))) return 'Not available';
  return new Date(value).toLocaleString('en-US', { timeZone: 'UTC' }) + ' UTC';
}
const explanations: Record<string, string> = {
  INVESTIGATED: 'An investigation assessment was persisted.',
  APPROVED: 'Merchant approval was recorded.',
  EXECUTION_RESERVED: 'The action was reserved before dispatch to prevent duplicates.',
  SUCCEEDED: 'A successful execution was recorded, including reconciliation when applicable.',
  FAILED: 'An execution failure was recorded. Approval remains reserved.',
  REQUIRES_RECONCILIATION: 'The outcome was uncertain. Verify PayPal before any further action.',
};
export default function AuditTimeline({ run, publicDemo = false }: { run: SavedRun | null; publicDemo?: boolean }) {
  return <section className="card history-section" aria-labelledby="audit-title"><div className="card-heading"><h2 id="audit-title">Audit trail</h2><span className="small muted">{publicDemo ? 'Synthetic events and dates' : 'Persisted events'}</span></div>
    {run?.audit_events.length ? <ol className="activity-timeline">{run.audit_events.map((event, index) => <li key={index}>
      <span className="activity-order"><Clock3 size={14} /></span><div className="activity-step"><h3>{event.event_type}</h3><p>{timestamp(event.occurred_at)} · {event.actor}</p><p>{explanations[event.event_type] ?? 'Unrecognized stored event.'}</p></div>
    </li>)}</ol> : <p className="empty-inline">{run ? 'No audit events were returned for this run.' : 'Select a saved investigation to inspect its audit trail.'}</p>}
  </section>;
}
