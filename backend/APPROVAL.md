# Local approval checkpoint

Use one development merchant and its corresponding Business Sandbox REST app.
The server-side merchant identity is a local identity, not a verified PayPal
merchant ID. Do not change the PayPal account behind an existing database.

Install `requirements.txt` into the existing virtual environment. `psycopg[binary]`
provides PostgreSQL access without system build tools. `httpx` supports HTTP
endpoint tests through FastAPI's test client.

Configure these environment variables without committing their values:

- `DATABASE_URL`: connection string for a dedicated PostgreSQL database.
- `DEV_MERCHANT_ID`: the local identity recorded in approvals and audit events.
- `DEV_MERCHANT_TOKEN`: a random development bearer credential, at least 32 characters.
- Existing PayPal Sandbox credentials.

Initialize and start locally:

```sh
.venv/bin/python -m backend.database
.venv/bin/python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

Do not expose this development service publicly. Do not put the bearer credential
in URLs. Both new endpoints require `Authorization: Bearer <development credential>`.

## Contract

`POST /api/disputes/{dispute_id}/investigate` has no request body. It retrieves the
current dispute and capture assessment, then returns the persisted run, including
`run_id`, assessment, investigation status, action, and exact message. This endpoint
does not send a PayPal message. `READY_FOR_REVIEW` is not approval.

After reviewing that run, `POST /disputes/{dispute_id}/approve` accepts only:

```json
{
  "run_id": "<UUID from investigation>",
  "action_type": "SEND_MESSAGE",
  "confirmed": true
}
```

The request cannot set `approved_by` or change the message. HIGH risk and
NEEDS_REVIEW do not prevent an explicit merchant override. The endpoint rechecks
the current reason, INQUIRY stage, WAITING_FOR_SELLER_RESPONSE status, and trusted
POST HATEOAS link before committing the approval and execution reservation.

Supported reasons are the three reasons already supported by the evidence engine.
The fixed message is:

> We are reviewing your dispute and will follow up with additional information.

Successful execution returns HTTP 200 with `run_id`, `execution_status`, and
`paypal_result` containing the real upstream HTTP status and sanitized response.
An upstream failure or ambiguous result returns HTTP 502 with the same fields.
Database failures return HTTP 503; duplicates return HTTP 409.

## Persistence and recovery

Only `disputes`, `runs`, and `audit_events` are created. A row lock and unique
partial index enforce one approved fixed message per dispute, even across runs.
The UUID `idempotency_key` is a local audit identifier. PayPal's send-message
documentation does not list `PayPal-Request-Id`, so it is not sent.

The durable reservation is REQUIRES_RECONCILIATION before the HTTP call. If the
process dies, the request times out, or result persistence fails, the reservation
remains and blocks re-execution. No automatic retry, expiry, or release exists.
The reservation audit event records the possible dispatch even when a later
outcome cannot be stored. `executed_at` is set only for confirmed success.

Reconcile uncertain outcomes by inspecting the run/audit records and retrieving
the current PayPal dispute messages read-only. Do not clear a reservation merely
because a response was lost. No reconciliation mutation endpoint is implemented.
Even a definite failure remains blocked for this checkpoint.

There is no distributed transaction with PayPal: its state may change between
the validation GET and the POST. A reservation guarantees at most one dispatch
attempt here, not exactly-once delivery at PayPal.

## Tests

Set `TEST_DATABASE_URL` to a separate disposable PostgreSQL database. Integration
tests create and drop uniquely named schemas, not existing application tables.
Run `.venv/bin/python -m pytest -q`. Without that variable, database tests are
explicitly skipped. PayPal network requests are blocked or mocked in approval tests.

## PayPal references

- [Send-message endpoint and available headers](https://developer.paypal.com/api/customer-disputes/v1/disputes-send-message)
- [JSON message body and stage/status rules](https://developer.paypal.com/platforms/disputes/handle-disputes/use-disputes-api/)
