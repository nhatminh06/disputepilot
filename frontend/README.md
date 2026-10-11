# Dispute detail workspace

Local-only Next.js App Router frontend for the existing FastAPI backend.

## Run

From the repository root, start the configured backend:

```sh
.venv/bin/python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

In another terminal:

```sh
cd frontend
npm ci
npm run dev
```

Open `http://localhost:3000/` and enter the dispute ID, or visit
`http://localhost:3000/disputes/<DISPUTE_ID>` directly. There is no dispute-list page.

The Next.js server loads the repository-root `.env`. Keep `DEV_MERCHANT_TOKEN` there,
never in a `NEXT_PUBLIC_` variable. PostgreSQL and the existing backend credentials
must already be configured for investigations. No frontend credential file is needed.

Both start scripts bind to `127.0.0.1`. Do not expose this development merchant proxy
through a tunnel, reverse proxy, or public deployment. Host/origin checks are not
production authentication.

## Data flow

The browser requests detail and assessment through same-origin route handlers.
Those handlers accept only fixed operations: detail, assessment, investigate, history,
and SEND_MESSAGE approval.
They attach the merchant credential server-side, refuse redirects, and project
validated response fields. Investigation and approval additionally require a matching
Origin and an action-specific custom request header. Only the existing authenticated
approval endpoint may execute the supported message action.

Clicking Investigate creates one backend run. The result replaces the evidence view
with the persisted assessment. Gemini explanations remain advisory; policy excerpts
are rendered as plain text and labeled synthetic demo policies. Fact coloring uses
backend rule outcomes, not an independent frontend risk calculation.

History loads the latest 25 merchant-owned runs and their audit events. Selecting a
saved run does not call Gemini. Local eligibility is preliminary; the approval
endpoint rechecks PayPal state and reserves the action in PostgreSQL. A previously
approved message blocks all newer pending runs for the same dispute.

Approval requires reviewing the exact persisted message and checking confirmation.
After submission, this page session blocks further approvals and refreshes history.
An ambiguous result is never retried automatically. Verify the PayPal result and
reconcile the stored execution before taking further action. Raw PayPal results,
audit payloads, and database idempotency keys are not exposed by history.

## Checks

```sh
npm run typecheck
npm run lint
npm run build
npm test
```

Browser tests use synthetic fixtures and a separate mock backend on port 8001 with
Next.js on port 3001. They never call PayPal or Gemini. Install Chromium with
`npx playwright install chromium` if unavailable, or set
`PLAYWRIGHT_CHROMIUM_EXECUTABLE` to an existing compatible browser executable.

Production preview remains localhost-only:

```sh
npm run build
npm run start
```
