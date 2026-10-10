CREATE TABLE IF NOT EXISTS disputes (
    dispute_id text PRIMARY KEY,
    merchant_id text NOT NULL,
    snapshot jsonb NOT NULL,
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS runs (
    run_id uuid PRIMARY KEY,
    dispute_id text NOT NULL REFERENCES disputes(dispute_id),
    assessment jsonb NOT NULL,
    investigation_status text NOT NULL
        CHECK (investigation_status IN ('NEEDS_REVIEW', 'READY_FOR_REVIEW')),
    action_type text NOT NULL CHECK (action_type = 'SEND_MESSAGE'),
    message text NOT NULL,
    approval_state text NOT NULL DEFAULT 'PENDING'
        CHECK (approval_state IN ('PENDING', 'APPROVED')),
    approved_by text,
    approved_at timestamptz,
    executed_at timestamptz,
    idempotency_key uuid NOT NULL UNIQUE,
    execution_status text NOT NULL DEFAULT 'NOT_STARTED'
        CHECK (execution_status IN (
            'NOT_STARTED', 'REQUIRES_RECONCILIATION', 'SUCCEEDED', 'FAILED'
        )),
    paypal_result jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    CHECK (
        (approval_state = 'PENDING' AND approved_by IS NULL
            AND approved_at IS NULL AND execution_status = 'NOT_STARTED')
        OR (approval_state = 'APPROVED' AND approved_by IS NOT NULL
            AND approved_at IS NOT NULL AND execution_status <> 'NOT_STARTED')
    ),
    CHECK ((executed_at IS NOT NULL) = (execution_status = 'SUCCEEDED'))
);

-- This milestone sends the same fixed message only once per dispute.
CREATE UNIQUE INDEX IF NOT EXISTS one_approved_message
    ON runs (dispute_id, action_type) WHERE approval_state = 'APPROVED';

CREATE TABLE IF NOT EXISTS audit_events (
    event_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    run_id uuid NOT NULL REFERENCES runs(run_id),
    event_type text NOT NULL CHECK (event_type IN (
        'INVESTIGATED', 'APPROVED', 'EXECUTION_RESERVED',
        'SUCCEEDED', 'FAILED', 'REQUIRES_RECONCILIATION'
    )),
    actor text NOT NULL,
    occurred_at timestamptz NOT NULL DEFAULT now(),
    data jsonb NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS audit_events_run ON audit_events (run_id);
