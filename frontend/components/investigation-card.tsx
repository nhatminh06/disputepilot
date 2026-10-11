import { ArrowRight, Check, CircleHelp, LoaderCircle, TriangleAlert } from 'lucide-react';
import type { Run } from '@/lib/contracts';
import { factLabel, readable } from '@/lib/display';

export default function InvestigationCard({ run, busy, error, disabled, onInvestigate }: {
  run: Run | null; busy: boolean; error: string | null; disabled: boolean; onInvestigate: () => void;
}) {
  const recommendation = run?.assessment.recommendation;
  const response = recommendation?.response;
  return <section className="card ai-card" id="investigation" aria-labelledby="ai-title" aria-busy={busy}>
    <div className="card-heading"><h2 id="ai-title">Investigation</h2><span className="small muted">Advisory</span></div>
    {response && recommendation ? <div className="recommendation" aria-live="polite">
      <div className="eyebrow">Recommendation</div>
      <div className="recommendation-title"><h3>{readable(response.recommendation)}</h3></div>
      {recommendation.fallback && <div className="inline-warning" role="status"><TriangleAlert size={17} /><p>Safe fallback: {readable(recommendation.api_status)}. This is an application fallback, not a validated model explanation.</p></div>}
      <p className="explanation">{response.summary}</p>
      <p className="small muted">{recommendation.fallback ? 'Application fallback' : 'AI-generated explanation'} · {recommendation.model}</p>
      <h4>Supporting evidence</h4>
      {response.supporting_fact_ids.length ? <div className="citation-list">{response.supporting_fact_ids.map(id => <a key={id} href={`#fact-${id}`}><Check size={13} />{factLabel(id)}</a>)}</div> : <p className="small muted">No verified supporting facts cited.</p>}
      <h4>Verified evidence requiring attention</h4>
      {response.adverse_fact_ids?.length ? <div className="citation-list adverse-label">{response.adverse_fact_ids.map(id => <a key={id} href={`#fact-${id}`}><TriangleAlert size={13} />{factLabel(id)}</a>)}</div> : <p className="small muted">No verified adverse facts cited.</p>}
      <h4>Missing information</h4>
      {response.missing_information.length ? <ul className="missing-list">{response.missing_information.map(id => <li key={id}><CircleHelp size={14} />{factLabel(id)}</li>)}</ul> : <p className="small muted">No missing information reported by the evidence engine.</p>}
      {response.policy_refs.length > 0 && <><h4>Policy citations</h4><div className="citation-list">{response.policy_refs.map(ref => <a key={ref} href={`#policy-${ref.replace('#', '-')}`}>{ref}</a>)}</div></>}
    </div> : run ? <p className="empty-inline">No recommendation was stored for this investigation. Select another saved run or prepare a new investigation below.</p> : <div className="ai-empty">
      <p>Review the available evidence and merchant policies to generate a recommendation.</p>
      <button className="button primary" onClick={onInvestigate} disabled={disabled || busy || !!error}>
        {busy && <LoaderCircle size={17} className="spin" />}
        {busy ? 'Investigating…' : 'Run investigation'}{!busy && <ArrowRight size={16} />}
      </button>
      <p className="ai-button-note">{busy ? 'Waiting for the backend investigation result.' : 'Gemini explains. Deterministic rules control the evidence. No PayPal actions are executed.'}</p>
    </div>}
    {error && <div className="investigation-error" role="alert"><TriangleAlert size={18} /><div><strong>Investigation unavailable</strong><p>{error}</p></div></div>}
    <div className="ai-safety"><p><strong>Approval required.</strong> Recommendations never approve or execute an action.</p></div>
  </section>;
}
