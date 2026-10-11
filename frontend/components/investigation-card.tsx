import { ArrowRight, Check, CircleHelp, LoaderCircle, LockKeyhole, Sparkles, TriangleAlert } from 'lucide-react';
import type { Run } from '@/lib/contracts';
import { factLabel, readable } from '@/lib/display';

export default function InvestigationCard({ run, busy, error, disabled, onInvestigate }: {
  run: Run | null; busy: boolean; error: string | null; disabled: boolean; onInvestigate: () => void;
}) {
  const recommendation = run?.assessment.recommendation;
  const response = recommendation?.response;
  return <section className="card ai-card" id="investigation" aria-labelledby="ai-title" aria-busy={busy}>
    <div className="card-heading"><div className="heading-with-icon"><Sparkles size={18} /><h2 id="ai-title">AI Investigation</h2></div><span className="badge badge-blue">Advisory</span></div>
    {response && recommendation ? <div className="recommendation" aria-live="polite">
      <div className="eyebrow">Recommendation</div>
      <div className="recommendation-title"><h3>{readable(response.recommendation)}</h3><span className={`badge badge-${response.recommendation === 'NEEDS_REVIEW' ? 'missing' : 'neutral'}`}>{response.recommendation}</span></div>
      {recommendation.fallback && <div className="inline-warning" role="status"><TriangleAlert size={17} /><p>Safe fallback: {readable(recommendation.api_status)}. This is an application fallback, not a validated model explanation.</p></div>}
      <p className="explanation">{response.summary}</p>
      <p className="small muted">{recommendation.fallback ? 'Application fallback' : 'AI-generated explanation'} · {recommendation.model}</p>
      <div className="recommendation-risk"><span>Deterministic risk</span><strong>{run.assessment.risk}</strong></div>
      <h4>Supporting evidence</h4>
      {response.supporting_fact_ids.length ? <div className="citation-list">{response.supporting_fact_ids.map(id => <a key={id} href={`#fact-${id}`}><Check size={13} />{factLabel(id)}</a>)}</div> : <p className="small muted">No verified supporting facts cited.</p>}
      <h4>Missing information</h4>
      {response.missing_information.length ? <ul className="missing-list">{response.missing_information.map(id => <li key={id}><CircleHelp size={14} />{factLabel(id)}</li>)}</ul> : <p className="small muted">No missing information reported by the evidence engine.</p>}
      {response.policy_refs.length > 0 && <><h4>Policy citations</h4><div className="citation-list">{response.policy_refs.map(ref => <a key={ref} href={`#policy-${ref.replace('#', '-')}`}>{ref}</a>)}</div></>}
    </div> : <div className="ai-empty">
      <div className="ai-emblem"><Sparkles size={25} strokeWidth={1.5} /></div>
      <h3>Investigate the evidence.</h3>
      <p>Bring together verified evidence and relevant demo policies for a structured recommendation.</p>
      <div className="ai-inputs"><span><Check size={14} />Deterministic evidence</span><span><Check size={14} />Traceable policy sources</span></div>
      <button className="button primary" onClick={onInvestigate} disabled={disabled || busy || !!error}>
        {busy ? <LoaderCircle size={17} className="spin" /> : <Sparkles size={17} />}
        {busy ? 'Investigating…' : 'Investigate with AI'}{!busy && <ArrowRight size={16} />}
      </button>
      <p className="ai-button-note">{busy ? 'Waiting for the backend investigation result.' : 'Runs only when you choose. No PayPal actions.'}</p>
    </div>}
    {error && <div className="investigation-error" role="alert"><TriangleAlert size={18} /><div><strong>Investigation unavailable</strong><p>{error}</p></div></div>}
    <div className="ai-safety"><LockKeyhole size={16} /><p><strong>You stay in control.</strong> Recommendations never approve or execute an action. Merchant approval is a separate, protected step.</p></div>
  </section>;
}
