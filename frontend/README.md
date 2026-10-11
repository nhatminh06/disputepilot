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

Open `http://localhost:3000/disputes/<DISPUTE_ID>`. There is no dispute-list page.

The Next.js server loads the repository-root `.env`. Keep `DEV_MERCHANT_TOKEN` there,
never in a `NEXT_PUBLIC_` variable. PostgreSQL and the existing backend credentials
must already be configured for investigations. No frontend credential file is needed.

Both start scripts bind to `127.0.0.1`. Do not expose this development merchant proxy
through a tunnel, reverse proxy, or public deployment. Host/origin checks are not
production authentication.

## Data flow

The browser requests detail and assessment through same-origin route handlers.
Those handlers accept only three fixed operations: detail, assessment, and investigate.
They attach the merchant credential server-side, refuse redirects, and project
validated response fields. Investigation additionally requires a matching Origin
and a custom request header. No approval or payment action is proxied.

Clicking Investigate creates one backend run. The result replaces the evidence view
with the persisted assessment. Gemini explanations remain advisory; policy excerpts
are rendered as plain text and labeled synthetic demo policies. Fact coloring uses
backend rule outcomes, not an independent frontend risk calculation.

The page does not fetch previous runs or audit events because suitable read endpoints
do not exist. Reloading loses the displayed run, not its database record. After an
ambiguous failure, check backend records before starting another run. No automatic
investigation retry is performed.

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
