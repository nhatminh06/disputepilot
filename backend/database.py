import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import psycopg
from dotenv import load_dotenv
from fastapi import HTTPException
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb


def connect() -> psycopg.Connection:
    url = os.getenv('DATABASE_URL')
    if not url:
        raise HTTPException(503, 'DATABASE_URL is not configured.')
    return psycopg.connect(url, row_factory=dict_row, connect_timeout=5)


def initialize() -> None:
    with connect() as conn:
        conn.execute(Path(__file__).with_name('schema.sql').read_text())


def audit(
    conn: psycopg.Connection, run_id: UUID, event: str, actor: str,
    data: dict[str, Any] | None = None,
) -> None:
    conn.execute(
        'INSERT INTO audit_events (run_id, event_type, actor, data) VALUES (%s,%s,%s,%s)',
        (run_id, event, actor, Jsonb(data or {})),
    )


def create_run(
    dispute: dict[str, Any], assessment: dict[str, Any], merchant: str, message: str,
) -> dict[str, Any]:
    run_id = uuid4()
    with connect() as conn:
        row = conn.execute(
            '''INSERT INTO disputes (dispute_id, merchant_id, snapshot)
               VALUES (%s,%s,%s) ON CONFLICT (dispute_id) DO UPDATE
               SET snapshot = EXCLUDED.snapshot, updated_at = now()
               WHERE disputes.merchant_id = EXCLUDED.merchant_id
               RETURNING dispute_id''',
            (dispute['dispute_id'], merchant, Jsonb(dispute)),
        ).fetchone()
        if row is None:
            raise HTTPException(403, 'Dispute belongs to a different merchant.')
        row = conn.execute(
            '''INSERT INTO runs (run_id, dispute_id, assessment, investigation_status,
                                 action_type, message, idempotency_key)
               VALUES (%s,%s,%s,%s,'SEND_MESSAGE',%s,%s) RETURNING *''',
            (run_id, dispute['dispute_id'], Jsonb(assessment),
             'NEEDS_REVIEW' if assessment['requires_review'] else 'READY_FOR_REVIEW',
             message, uuid4()),
        ).fetchone()
        audit(conn, run_id, 'INVESTIGATED', merchant)
    return row


def check_run(run: dict[str, Any] | None, dispute_id: str, merchant: str) -> None:
    if run is None:
        raise HTTPException(404, 'Run not found.')
    if run['dispute_id'] != dispute_id:
        raise HTTPException(409, 'Run does not belong to this dispute.')
    if run['merchant_id'] != merchant:
        raise HTTPException(403, 'Run belongs to a different merchant.')
    if run['approval_state'] != 'PENDING' or run['execution_status'] != 'NOT_STARTED':
        raise HTTPException(409, 'Action already reserved. Do not retry; reconcile it.')


def history(dispute_id: str, merchant: str, supported_message: str) -> dict[str, Any]:
    with connect() as conn:
        # One snapshot keeps eligibility and history consistent during concurrent approval.
        conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
        owner = conn.execute(
            'SELECT dispute_id FROM disputes WHERE dispute_id=%s AND merchant_id=%s',
            (dispute_id, merchant),
        ).fetchone()
        if owner is None:
            raise HTTPException(404, 'No stored dispute for this merchant.')
        approved = conn.execute(
            '''SELECT r.run_id, r.execution_status, r.approved_at, r.executed_at
               FROM runs r JOIN disputes d USING (dispute_id)
               WHERE r.dispute_id=%s AND d.merchant_id=%s
                 AND r.action_type='SEND_MESSAGE' AND r.approval_state='APPROVED' ''',
            (dispute_id, merchant),
        ).fetchone()
        runs = conn.execute(
            '''SELECT r.run_id, r.dispute_id, r.assessment, r.investigation_status,
                      r.action_type, r.message, r.approval_state, r.execution_status,
                      r.created_at, r.approved_at, r.executed_at
               FROM runs r JOIN disputes d USING (dispute_id)
               WHERE r.dispute_id=%s AND d.merchant_id=%s
               ORDER BY r.created_at DESC, r.run_id DESC LIMIT 25''',
            (dispute_id, merchant),
        ).fetchall()
        for run in runs:
            run['audit_events'] = conn.execute(
                '''SELECT event_type, occurred_at,
                          CASE WHEN actor=%s THEN 'Merchant' ELSE 'Recorded actor' END AS actor
                   FROM audit_events WHERE run_id=%s
                   ORDER BY occurred_at, event_id LIMIT 100''',
                (merchant, run['run_id']),
            ).fetchall()
            if approved:
                status = approved['execution_status']
                run['eligibility'] = (
                    'ALREADY_SENT' if status == 'SUCCEEDED' else
                    'REQUIRES_RECONCILIATION' if status == 'REQUIRES_RECONCILIATION'
                    else 'ALREADY_APPROVED'
                )
            elif (run['approval_state'] == 'PENDING'
                  and run['execution_status'] == 'NOT_STARTED'
                  and run['action_type'] == 'SEND_MESSAGE'
                  and run['message'] == supported_message):
                run['eligibility'] = 'ELIGIBLE'
            else:
                run['eligibility'] = 'INELIGIBLE'
    return {'dispute_id': dispute_id, 'runs': runs, 'approved_action': approved}


def get_pending_run(run_id: UUID, dispute_id: str, merchant: str) -> dict[str, Any]:
    with connect() as conn:
        run = conn.execute(
            '''SELECT r.*, d.merchant_id FROM runs r JOIN disputes d USING (dispute_id)
               WHERE run_id = %s''', (run_id,),
        ).fetchone()
        check_run(run, dispute_id, merchant)
    return run


def reserve(
    run_id: UUID, dispute_id: str, merchant: str, snapshot: dict[str, Any],
) -> None:
    with connect() as conn:
        conn.execute('SELECT dispute_id FROM disputes WHERE dispute_id=%s FOR UPDATE',
                     (dispute_id,))
        run = conn.execute(
            '''SELECT r.*, d.merchant_id FROM runs r JOIN disputes d USING (dispute_id)
               WHERE run_id=%s FOR UPDATE OF r''', (run_id,),
        ).fetchone()
        check_run(run, dispute_id, merchant)
        previous = conn.execute(
            "SELECT run_id FROM runs WHERE dispute_id=%s AND approval_state='APPROVED'",
            (dispute_id,),
        ).fetchone()
        if previous:
            raise HTTPException(409, 'A message is already reserved for this dispute.')
        conn.execute('UPDATE disputes SET snapshot=%s, updated_at=now() WHERE dispute_id=%s',
                     (Jsonb(snapshot), dispute_id))
        # Commit the uncertain state before dispatch, including the crash window.
        conn.execute(
            '''UPDATE runs SET approval_state='APPROVED', approved_by=%s,
               approved_at=now(), execution_status='REQUIRES_RECONCILIATION'
               WHERE run_id=%s''', (merchant, run_id),
        )
        audit(conn, run_id, 'APPROVED', merchant,
              {'action_type': run['action_type'], 'message': run['message'],
               'current_dispute': snapshot})
        audit(conn, run_id, 'EXECUTION_RESERVED', merchant,
              {'idempotency_key': str(run['idempotency_key'])})


def finish(run_id: UUID, status: str, result: dict[str, Any], merchant: str) -> None:
    with connect() as conn:
        row = conn.execute(
            '''UPDATE runs SET execution_status=%s, paypal_result=%s,
               executed_at=CASE WHEN %s='SUCCEEDED' THEN now() ELSE NULL END
               WHERE run_id=%s AND execution_status='REQUIRES_RECONCILIATION'
               RETURNING run_id''', (status, Jsonb(result), status, run_id),
        ).fetchone()
        if row is None:
            raise HTTPException(409, 'Execution record is no longer reserved.')
        audit(conn, run_id, status, merchant, result)


def reconcile_message(run_id: UUID, dispute: dict[str, Any], merchant: str) -> None:
    """Record confirmation from a freshly retrieved dispute without dispatching a write."""
    with connect() as conn:
        run = conn.execute(
            '''SELECT r.*, d.merchant_id FROM runs r JOIN disputes d USING (dispute_id)
               WHERE run_id=%s FOR UPDATE OF r''', (run_id,),
        ).fetchone()
        if run is None or run['dispute_id'] != dispute.get('dispute_id'):
            raise HTTPException(409, 'Reconciliation dispute does not match the run.')
        if run['merchant_id'] != merchant or run['approved_by'] != merchant:
            raise HTTPException(403, 'Reconciliation merchant does not match approval.')
        if (run['approval_state'] != 'APPROVED'
                or run['execution_status'] != 'REQUIRES_RECONCILIATION'
                or run['action_type'] != 'SEND_MESSAGE'
                or (run['paypal_result'] or {}).get('http_status') != 200):
            raise HTTPException(409, 'Run is not eligible for HTTP 200 reconciliation.')
        matches = [m for m in dispute.get('messages') or []
                   if m.get('content') == run['message']]
        if len(matches) != 1 or matches[0].get('posted_by') != 'SELLER':
            raise HTTPException(409, 'Exactly one matching seller message is required.')
        try:
            posted_at = datetime.fromisoformat(matches[0].get('time_posted', ''))
        except (TypeError, ValueError) as error:
            raise HTTPException(409, 'Message timestamp is unavailable.') from error
        if (posted_at.tzinfo is None or posted_at < run['approved_at']
                or posted_at > datetime.now(timezone.utc)):
            raise HTTPException(409, 'Message timestamp does not confirm this approval.')
        conn.execute(
            "UPDATE runs SET execution_status='SUCCEEDED', executed_at=%s WHERE run_id=%s",
            (posted_at, run_id),
        )
        audit(conn, run_id, 'SUCCEEDED', merchant, {
            'reconciliation': True,
            'previous_execution_status': run['execution_status'],
            'source': f"GET /v1/customer/disputes/{run['dispute_id']}",
            'matching_message_count': 1,
            'message': {'content': run['message'], 'posted_by': 'SELLER',
                        'time_posted': posted_at.isoformat()},
            'original_paypal_result': run['paypal_result'],
        })


if __name__ == '__main__':
    load_dotenv()
    initialize()
    print('PostgreSQL schema initialized.')
