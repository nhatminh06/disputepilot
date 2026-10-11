'use client';

import { useEffect, useRef, useState } from 'react';
import type { SavedRun } from '@/lib/contracts';

export default function ApprovalDialog({ run, onClose, onConfirm }: {
  run: SavedRun; onClose: () => void; onConfirm: () => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [confirmed, setConfirmed] = useState(false);
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    const element = dialog.current!;
    element.showModal();
    return () => { element.close(); previous?.focus(); };
  }, []);
  return <dialog ref={dialog} className="approval-dialog" aria-labelledby="approval-title" aria-describedby="approval-description" onCancel={event => { event.preventDefault(); onClose(); }}>
    <h2 id="approval-title">Approve PayPal message</h2>
    <p id="approval-description">Review the exact message that will be sent to PayPal Sandbox.</p>
    <dl className="approval-details">
      <div><dt>Dispute ID</dt><dd>{run.dispute_id}</dd></div><div><dt>Selected run ID</dt><dd>{run.run_id}</dd></div>
      <div><dt>Action</dt><dd>{run.action_type}</dd></div><div><dt>Recommendation</dt><dd>{run.assessment.recommendation?.response.recommendation ?? 'Not available'}</dd></div>
      <div><dt>Deterministic risk</dt><dd>{run.assessment.risk}</dd></div><div><dt>Known approval state</dt><dd>{run.approval_state}</dd></div>
    </dl>
    <h3>Exact persisted message</h3><blockquote className="pending-message">{run.message}</blockquote>
    <p className="approval-warning">This action sends a real message to PayPal Sandbox. AI recommendations do not authorize execution.</p>
    <label className="confirmation"><input type="checkbox" checked={confirmed} onChange={event => setConfirmed(event.target.checked)} />I have reviewed the evidence and authorize this PayPal Sandbox message.</label>
    <div className="approval-buttons"><button autoFocus className="button secondary" onClick={onClose}>Cancel</button><button className="button primary" disabled={!confirmed} onClick={() => { if (confirmed) onConfirm(); }}>Confirm and send message</button></div>
  </dialog>;
}
