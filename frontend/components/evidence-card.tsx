import { AlertTriangle, Check, CircleHelp, ListChecks, Minus, ShieldAlert } from 'lucide-react';
import type { Assessment } from '@/lib/contracts';
import { adverseFactIds } from '@/lib/contracts';
import { factLabel, readable } from '@/lib/display';

export default function EvidenceCard({ assessment }: { assessment: Assessment }) {
  const verified = assessment.facts.filter(f => f.status === 'VERIFIED').length;
  const adverseIds = adverseFactIds(assessment);
  return <section className="card evidence-card" id="evidence" aria-labelledby="evidence-title">
    <div className="card-heading"><div className="heading-with-icon"><ListChecks size={18} /><h2 id="evidence-title">Evidence checklist</h2></div>
      <span className="small muted">{verified} of {assessment.facts.length} verified</span></div>
    <div className={`risk-strip risk-${assessment.risk.toLowerCase()}`}>
      <ShieldAlert size={20} /><div><strong>{readable(assessment.risk)} contesting risk</strong>
        <p>Computed by deterministic rules, not by AI.</p></div><span className="badge">{assessment.risk}</span>
    </div>
    <div className="evidence-table-head"><span>Evidence & provenance</span><span>Status</span></div>
    <ul className="facts">
      {assessment.facts.map(fact => {
        const adverse = adverseIds.includes(fact.fact_id);
        const supporting = fact.status === 'VERIFIED' && assessment.supporting_fact_ids.includes(fact.fact_id);
        const tone = adverse ? 'adverse' : supporting ? 'favorable' : fact.status === 'MISSING' ? 'missing' : 'neutral';
        const Icon = adverse ? AlertTriangle : supporting ? Check : fact.status === 'MISSING' ? Minus : CircleHelp;
        return <li key={fact.fact_id} className={`fact fact-${tone}`} id={`fact-${fact.fact_id}`}>
          <span className="fact-icon"><Icon size={16} /></span>
          <div className="fact-content"><h3>{factLabel(fact.fact_id)}</h3>
            <p className="provenance">{fact.source === 'not_checked' ? 'Source not checked' : fact.source}</p>
            {fact.value !== null && <p className="fact-value">Verified value: {typeof fact.value === 'boolean' ? (fact.value ? 'Yes' : 'No') : fact.value}</p>}
            {adverse && <p className="adverse-label">Does not support contesting</p>}
          </div><span className={`badge badge-${tone}`}>{fact.status}</span>
        </li>;
      })}
    </ul>
    {assessment.facts.length === 0 && <p className="empty-inline">No evidence facts were returned.</p>}
    <div className="card-footnote"><CircleHelp size={15} /><p>Verified means source-backed, not necessarily favorable. Missing tracking is not proof of non-delivery.</p></div>
    <details className="rules"><summary>View deterministic rules <span>{assessment.rules.length}</span></summary>
      <ul>{assessment.rules.map(rule => <li key={rule.rule_id}><span className="mono small">{rule.outcome}</span><p>{rule.explanation}</p></li>)}</ul>
    </details>
  </section>;
}
