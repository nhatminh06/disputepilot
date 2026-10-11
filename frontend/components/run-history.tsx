'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { History as HistoryIcon, LockKeyhole } from 'lucide-react';
import { parseHistory, type History, type SavedRun } from '@/lib/contracts';
import ApprovalDialog from './approval-dialog';
import AuditTimeline, { timestamp } from './audit-timeline';

const eligibilityText = {
  ELIGIBLE: 'Locally eligible for approval consideration. PayPal permission has not been checked; the backend revalidates it before execution.',
  ALREADY_SENT: 'Message already sent for this dispute',
  ALREADY_APPROVED: 'A message is already approved for this dispute. Another approval is blocked, including after a failed execution.',
  REQUIRES_RECONCILIATION: 'Requires reconciliation. Verify the PayPal result before attempting another action. Do not resend.',
  INELIGIBLE: 'This run is not eligible for approval in its current stored state.',
};

async function readHistory(id: string, signal?: AbortSignal): Promise<History> {
  const response = await fetch(`/api/disputes/${id}/history`, { cache: 'no-store', signal });
  // Unknown and non-owned records both return 404 without disclosing ownership.
  if (response.status === 404) return { dispute_id: id, runs: [], approved_action: null, paypal_writes_enabled: false };
  if (!response.ok) throw new Error(`History unavailable (HTTP ${response.status}). Approval is disabled.`);
  const data = parseHistory(await response.json());
  if (data.dispute_id !== id) throw new Error('History returned a different dispute.');
  return data;
}

export default function RunHistory({ id, newRunId, onSelect, onNew }: {
  id: string; newRunId: string | null; onSelect: (run: SavedRun) => void; onNew: () => void;
}) {
  const [history, setHistory] = useState<History | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [dialog, setDialog] = useState(false);
  const [sending, setSending] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [attempted, setAttempted] = useState(false);
  const inFlight = useRef(false);
  const selectCallback = useRef(onSelect);
  useEffect(() => { selectCallback.current = onSelect; }, [onSelect]);
  const load = useCallback((preferred: string | null, signal?: AbortSignal) => {
    return readHistory(id, signal).then(data => {
      if (signal?.aborted) return;
      setError(null);
      setHistory(data);
      const current = data.runs.find(run => run.run_id === preferred) ?? data.runs[0];
      setSelected(current?.run_id ?? null);
      if (current) selectCallback.current(current);
    }).catch((failure: unknown) => {
      if (!signal?.aborted) setError(failure instanceof Error ? failure.message : 'History unavailable. Approval is disabled.');
    }).finally(() => { if (!signal?.aborted) setLoading(false); });
  }, [id]);
  useEffect(() => {
    const controller = new AbortController();
    void load(newRunId, controller.signal);
    return () => controller.abort();
  }, [load, newRunId]);
  const run = history?.runs.find(item => item.run_id === selected) ?? null;
  const eligible = history?.paypal_writes_enabled === true && !!run && run.eligibility === 'ELIGIBLE' && !history?.approved_action &&
    run.action_type === 'SEND_MESSAGE' && run.approval_state === 'PENDING' && run.execution_status === 'NOT_STARTED' &&
    !error && !loading && !sending && !attempted;

  async function approve() {
    if (!eligible || !run || inFlight.current) return;
    inFlight.current = true; setAttempted(true);
    setSending(true); setDialog(false); setNotice('Submitting once. Do not repeat this action.');
    try {
      const response = await fetch(`/api/disputes/${id}/approve`, {
        method: 'POST', headers: { 'Content-Type': 'application/json', 'X-DisputePilot-Request': 'approve' },
        body: JSON.stringify({ run_id: run.run_id, action_type: 'SEND_MESSAGE', confirmed: true }),
        signal: AbortSignal.timeout(125_000),
      });
      const messages: Record<number, string> = {
        401: 'Merchant authentication required.', 403: 'Approval access denied.', 404: 'Stored run not found.',
        409: 'Approval conflict. The action may already be reserved or no longer permitted.', 422: 'Invalid approval confirmation or action.',
      };
      setNotice(response.ok ? 'Request returned. Check the persisted execution state below.' :
        `${messages[response.status] ?? 'Execution outcome may be unknown.'} Do not retry. Verify the PayPal result if reconciliation is required.`);
    } catch {
      setNotice('Execution outcome unknown. The message may have been sent. Do not retry; verify the PayPal result and stored history.');
    } finally {
      setLoading(true);
      await load(run.run_id);
      inFlight.current = false; setSending(false);
    }
  }

  return <>
    <section className="card history-section" aria-labelledby="history-title"><div className="card-heading"><div className="heading-with-icon"><HistoryIcon size={18} /><h2 id="history-title">Investigation history</h2></div><button className="button secondary" disabled={loading || sending} onClick={() => { setLoading(true); void load(selected); }}>Refresh history</button></div>
      <p className="empty-inline">Up to 25 newest saved investigations. Selecting a run reads its saved evidence and recommendation, without calling Gemini.</p>
      {error && <p className="history-warning" role="alert">{error}</p>}
      {loading && <p className="empty-inline" role="status">Loading stored history…</p>}
      {history?.approved_action && <p className="history-warning">{history.approved_action.execution_status === 'SUCCEEDED' ? 'Message already sent for this dispute' : history.approved_action.execution_status === 'REQUIRES_RECONCILIATION' ? eligibilityText.REQUIRES_RECONCILIATION : eligibilityText.ALREADY_APPROVED}<br />Reserved run: {history.approved_action.run_id}<br />{timestamp(history.approved_action.executed_at ?? history.approved_action.approved_at)}</p>}
      <div className="history-list">{history?.runs.map(item => <button key={item.run_id} className="history-row" aria-pressed={selected === item.run_id} disabled={sending} onClick={() => { setSelected(item.run_id); selectCallback.current(item); setDialog(false); }}>
        <span><strong>{timestamp(item.created_at)}</strong><code>{item.run_id}</code></span><span>{item.assessment.recommendation?.response.recommendation ?? 'No recommendation'}<small>Risk: {item.assessment.risk} · {item.investigation_status}</small></span><span className="history-badges"><span className="badge">{item.approval_state}</span><span className="badge">{item.execution_status}</span></span>
      </button>)}</div>
      {!loading && history?.runs.length === 0 && <p className="empty-inline">No saved investigations.</p>}
      {!!history?.runs.length && <div className="history-controls"><button className="button secondary" disabled={sending} onClick={() => { setSelected(null); onNew(); }}>Prepare a new investigation</button></div>}
    </section>
    <AuditTimeline run={run} />
    <section className="card history-section" aria-labelledby="merchant-title"><div className="card-heading"><div className="heading-with-icon"><LockKeyhole size={18} /><h2 id="merchant-title">Merchant approval</h2></div><span className="badge badge-blue">SEND_MESSAGE only</span></div>
      <div className="approval-content"><p>This sends a real PayPal Sandbox message. It is not a refund, contest submission, evidence submission, or automatic resolution.</p>
        {history && !history.paypal_writes_enabled && <p className="history-warning" role="status">Demo mode: PayPal actions disabled</p>}
        {run ? <><p className="approval-state">{!history?.paypal_writes_enabled && run.eligibility === 'ELIGIBLE' ? 'This pending run cannot be executed in demo mode.' : eligibilityText[run.eligibility]}</p><p>Stored approval: <strong>{run.approval_state}</strong> · Execution: <strong>{run.execution_status}</strong></p>
          {run.execution_status === 'SUCCEEDED' && <p>Successful execution recorded: {timestamp(run.executed_at)}</p>}
          {eligible && <button className="button primary" onClick={() => setDialog(true)}>Review message for approval</button>}
        </> : <p>Select a saved run to review its action and eligibility.</p>}
        {notice && <p role="status" className="history-warning">{notice}</p>}
        {sending && <p role="status">Awaiting execution response and authoritative history. No automatic retry.</p>}
        {error && <p>Approval is blocked until authoritative history is available.</p>}
      </div>
    </section>
    {dialog && eligible && run && <ApprovalDialog key={run.run_id} run={run} onClose={() => setDialog(false)} onConfirm={() => void approve()} />}
  </>;
}
