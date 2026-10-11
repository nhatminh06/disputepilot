'use client';

import { useEffect, useRef, useState } from 'react';
import { ArrowUpRight, Check, ChevronRight, Copy, FlaskConical, FolderOpen, LockKeyhole, Menu, RefreshCw, ShieldCheck, TriangleAlert, X } from 'lucide-react';
import { parseAssessment, parseDispute, parseRun, type Assessment, type Dispute, type Run } from '@/lib/contracts';
import { deadline, readable, reasonLabel } from '@/lib/display';
import EvidenceCard from './evidence-card';
import InvestigationCard from './investigation-card';
import PoliciesCard from './policies-card';
import AgentActivity from './agent-activity';

async function getData(path: string, signal: AbortSignal, investigate = false): Promise<unknown> {
  const response = await fetch(path, {
    method: investigate ? 'POST' : 'GET', signal, cache: 'no-store',
    headers: investigate ? { 'X-DisputePilot-Request': 'investigate' } : undefined,
  });
  const body: unknown = await response.json();
  if (!response.ok) {
    const message = body && typeof body === 'object' && 'error' in body && typeof body.error === 'string' ? body.error : `Request failed (HTTP ${response.status}).`;
    throw new Error(message);
  }
  return body;
}

export default function DisputePage({ id }: { id: string }) {
  const [dispute, setDispute] = useState<Dispute | null>(null);
  const [assessment, setAssessment] = useState<Assessment | null>(null);
  const [run, setRun] = useState<Run | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [investigationError, setInvestigationError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [menu, setMenu] = useState(false);
  const [copied, setCopied] = useState(false);
  const [refresh, setRefresh] = useState(0);
  const submitting = useRef(false);

  useEffect(() => {
    const controller = new AbortController();
    Promise.all([
      getData(`/api/disputes/${id}`, controller.signal).then(parseDispute),
      getData(`/api/disputes/${id}/assessment`, controller.signal).then(parseAssessment),
    ]).then(([detail, evidence]) => {
      if (controller.signal.aborted) return;
      if (detail.dispute_id !== id || evidence.dispute_id !== id) throw new Error('Received a different dispute.');
      setDispute(detail); setAssessment(evidence); setError(null);
    }).catch((failure: unknown) => {
      if (!controller.signal.aborted) setError(failure instanceof Error ? failure.message : 'Could not load dispute data.');
    }).finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [id, refresh]);

  async function investigate() {
    if (submitting.current || run || investigationError) return;
    submitting.current = true; setBusy(true);
    try {
      const result = parseRun(await getData(`/api/disputes/${id}/investigate`, AbortSignal.timeout(125_000), true));
      if (result.dispute_id !== id) throw new Error('Received a different dispute.');
      setRun(result); setAssessment(result.assessment);
    } catch (failure: unknown) {
      setInvestigationError(`${failure instanceof Error ? failure.message : 'Investigation outcome unknown.'} No automatic retry. Check the backend record before starting another run.`);
    } finally { setBusy(false); }
  }

  function reload() {
    setLoading(true); setError(null); setRefresh(n => n + 1);
  }

  async function copyId() {
    try { await navigator.clipboard.writeText(id); setCopied(true); }
    catch { setCopied(false); }
  }

  return <div className="app-shell">
    <a href="#main" className="skip-link">Skip to case details</a>
    <aside className={`sidebar ${menu ? 'sidebar-open' : ''}`} aria-label="Workspace navigation">
      <div className="brand"><span className="brand-mark"><ShieldCheck size={22} /></span><span>DisputePilot</span><button className="icon-button mobile-close" aria-label="Close navigation" onClick={() => setMenu(false)}><X size={19} /></button></div>
      <div className="workspace-label">MERCHANT WORKSPACE</div>
      <nav><a className="nav-current" href="#main" aria-current="page" onClick={() => setMenu(false)}><FolderOpen size={18} /><span>Disputes</span><ChevronRight size={15} /></a></nav>
      <div className="sidebar-context"><span className="sidebar-context-label">EVIDENCE BEFORE ACTION</span><p>Investigate with clarity.<br />Respond with control.</p><div className="sidebar-divider" /><span><LockKeyhole size={13} />Human approval required</span></div>
      <div className="sidebar-bottom"><div className="sandbox-label"><FlaskConical size={16} /><span>Sandbox environment</span><i /></div><p>Local development workspace</p></div>
    </aside>
    {menu && <button className="nav-backdrop" aria-label="Dismiss navigation" onClick={() => setMenu(false)} />}
    <div className="workspace">
      <header className="topbar"><div className="breadcrumb"><button className="icon-button mobile-menu" aria-label="Open navigation" aria-expanded={menu} onClick={() => setMenu(true)}><Menu size={20} /></button><span>Disputes</span><ChevronRight size={14} /><span className="breadcrumb-id">{id}</span></div><div className="topbar-environment"><span className="environment-dot" />Sandbox<span className="topbar-separator" /><LockKeyhole size={14} /><span>Local only</span></div></header>
      <main id="main" className="content">
        <div className="page-heading"><div><div className="eyebrow">Dispute workspace</div><h1>{dispute ? reasonLabel(dispute.reason) : 'Dispute details'}</h1><div className="case-id"><span>PayPal case</span><code>{id}</code><button className="icon-button copy-button" onClick={copyId} aria-label={copied ? 'Dispute ID copied' : 'Copy dispute ID'}>{copied ? <Check size={14} /> : <Copy size={14} />}</button></div></div><button className="button secondary refresh-button" disabled={loading || busy || !!run} onClick={reload}><RefreshCw size={15} className={loading ? 'spin' : ''} />Refresh data</button></div>
        {loading ? <div className="loading-state" role="status" aria-label="Loading dispute"><div className="skeleton skeleton-summary" /><div className="two-columns"><div className="skeleton skeleton-panel" /><div className="skeleton skeleton-panel" /></div><span className="sr-only">Loading dispute and evidence from PayPal Sandbox.</span></div> : error ? <section className="card error-state" role="alert"><TriangleAlert size={28} /><h2>Unable to load this dispute</h2><p>{error}</p><button className="button secondary" onClick={reload}>Retry read-only lookup</button></section> : dispute && assessment ? <>
          <section className="case-summary card" aria-label="PayPal case summary">
            <div className="summary-field amount-field"><span className="field-label">Disputed amount</span><div className="amount">{dispute.amount ?? 'Not available'}<span>{dispute.currency ?? ''}</span></div></div>
            <div className="summary-field"><span className="field-label">PayPal status</span><span className="status-label" title={dispute.status || undefined}><span className="status-dot" />{readable(dispute.status)}</span><span className="field-note">Reported by PayPal</span></div>
            <div className="summary-field"><span className="field-label">Lifecycle stage</span><strong>{readable(dispute.lifecycle_stage)}</strong><span className="field-note">Separate from computed risk</span></div>
            <div className="summary-field deadline-field"><span className="field-label">Seller response deadline</span><strong>{deadline(dispute.response_deadline)}</strong><span className="field-note">{dispute.response_deadline ? 'As provided by PayPal' : 'No deadline returned'}</span></div>
          </section>
          <nav className="section-nav" aria-label="Case sections"><a href="#evidence" className="section-active">Case overview</a><a href="#policies">Policy references<ArrowUpRight size={12} /></a><a href="#run-details">Investigation details<ArrowUpRight size={12} /></a></nav>
          <div className="two-columns"><EvidenceCard assessment={assessment} /><InvestigationCard run={run} busy={busy} error={investigationError} disabled={loading} onInvestigate={investigate} /></div>
          <PoliciesCard policies={assessment.retrieved_policies} investigated={!!run} />
          <AgentActivity run={run} busy={busy} />
          <section className="card investigation-details" id="run-details" aria-labelledby="details-title"><div className="card-heading"><h2 id="details-title">Investigation details</h2><span className="small muted">{run ? 'Persisted backend record' : 'No run in this session'}</span></div>
            {run ? <dl className="run-details"><div><dt>Run ID</dt><dd className="mono">{run.run_id}</dd></div><div><dt>Investigation status</dt><dd>{readable(run.investigation_status)}</dd></div><div><dt>Recommendation</dt><dd>{run.assessment.recommendation?.response.recommendation}</dd></div><div><dt>Approval</dt><dd>{run.approval_state}</dd></div><div><dt>Execution</dt><dd>{run.execution_status}</dd></div></dl> : <p className="empty-inline">Run an investigation to create a persisted assessment and recommendation. Previous runs are not loaded on this page.</p>}
          </section>
          <footer className="page-footer"><ShieldCheck size={14} /><span>Evidence informs. People decide.</span><span className="footer-end">PayPal Sandbox · No payment actions on this page</span></footer>
        </> : <p className="empty-inline">No dispute data returned.</p>}
      </main>
    </div>
  </div>;
}
