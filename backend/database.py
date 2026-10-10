import os
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


if __name__ == '__main__':
    load_dotenv()
    initialize()
    print('PostgreSQL schema initialized.')
