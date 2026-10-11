# DisputePilot

Local-only PayPal Sandbox dispute workspace. Deterministic rules supply evidence
and risk; Gemini recommendations are advisory. Only explicit merchant approval can
reach the separate SEND_MESSAGE execution function.

## Prerequisites

- Docker Engine and Docker Compose with health-check dependency support.
- Port 3000 available on the host. Stop a native Next.js process before starting
  Compose; do not run both on that port.
- PayPal Sandbox business REST credentials and a development merchant identity.
- A Gemini API key only if you want to request an investigation with Gemini.

The images use digest-pinned Python 3.11, Node 24 LTS, and PostgreSQL 17 bases.
Backend runtime dependencies are pinned in `backend/requirements.lock`; the
frontend uses `npm ci` and `frontend/package-lock.json`. Update these deliberately
when upgrading dependencies. No secrets are required to build either image.

## Environment

For a new checkout, copy `.env.example` to `.env` and fill its placeholders locally.
Do not overwrite an existing `.env`. Never paste credentials into logs or commits.

Required for Compose:

- `PAYPAL_CLIENT_ID`, `PAYPAL_CLIENT_SECRET`: Sandbox business REST app credentials.
- `PAYPAL_BASE_URL`: `https://api-m.sandbox.paypal.com`. Non-Sandbox hosts are rejected.
- `DEV_MERCHANT_ID`: the local merchant identity recorded in approval/audit records.
- `DEV_MERCHANT_TOKEN`: a strong random development bearer token of at least 32 characters.
- `COMPOSE_POSTGRES_PASSWORD`: a separate strong password for the Compose database.

Optional investigation configuration:

- `GEMINI_API_KEY`: kept only in the backend container.
- `GEMINI_MODEL`: defaults to `gemini-3.1-flash-lite`.
- `GEMINI_AGENT_ENABLED`: defaults to `false`. Enable only when intentionally testing
  the bounded read-only agent. Opening the UI or running a health check never invokes Gemini.

`DATABASE_URL` and `TEST_DATABASE_URL` remain host-development settings. Compose
ignores them and constructs its connection to the fixed `postgres:5432` service,
using database/user `disputepilot` and `COMPOSE_POSTGRES_PASSWORD`.

Compose interpolates `.env` at runtime; it does not mount or copy the file into
images. The frontend gets only the merchant token, the fixed internal backend URL,
and the explicit Compose-mode flag. No secret uses a `NEXT_PUBLIC_` variable.

## Start and inspect

From the repository root:

```sh
docker compose config --quiet
docker compose up --build -d
docker compose ps
```

Wait until all three services are healthy. Open `http://localhost:3000/`, or:

`http://localhost:3000/disputes/PP-R-UZR-10190879`

Architecture:

```text
Browser -> 127.0.0.1:3000 -> Next.js -> backend:8000 -> postgres:5432
                                      |
                                      +-> PayPal Sandbox / Gemini HTTPS
```

Only the frontend port is published, bound to host loopback. Backend and database
ports are not published. Inside containers the servers listen on the container
interface. Outside Compose, the existing proxy still accepts only its fixed local
development addresses. `http://backend:8000` is allowed only in explicit Compose mode.

PostgreSQL readiness gates backend startup. The backend runs the existing
idempotent `CREATE TABLE IF NOT EXISTS` schema setup before starting Uvicorn.
Frontend startup waits for the backend HTTP health check. Health checks are local
and never perform PayPal actions or Gemini requests.

For a foreground readiness check after the first build:

```sh
docker compose up -d --wait
curl -s -o /dev/null -w 'HTTP %{http_code}\n' http://localhost:3000/
```

Do not print resolved `docker compose config` output or container environment
variables: they contain credentials. Use `config --quiet` instead. Inspect logs
locally and redact identifiers before sharing:

```sh
docker compose logs --tail=50 backend frontend
```

## Stop and persistence

```sh
docker compose down
docker compose up -d --wait
```

The named volume `disputepilot-demo_postgres_data` survives `down`. Schema startup
does not delete or recreate existing records. Removing this volume, including via
the volume-deletion option of `compose down`, destroys its runs and audit history.
Do not remove volumes as a troubleshooting step.

The Compose database is separate from the existing native development database
and its `disputepilot_pgdata` volume. A clean Compose database has no imported
history. The real PayPal dispute/evidence can still load, while history displays
an empty state. No automatic import or investigation is performed.

Important: an empty database does not prove that no PayPal action occurred. The
existing dispute `PP-R-UZR-10190879` already received a message in the development
environment. Do not authorize another message from a fresh database. Historical
approval protection is scoped to the database containing those records. Any
future data migration must preserve approvals and audit records, not reset them.

Changing the password in `.env` does not change an existing PostgreSQL role's
password. Keep the established password or perform an explicit credential rotation;
do not delete the volume to resolve a password mismatch.

## Verification and development

The local frontend development instructions remain in `frontend/README.md`.
Native services use host `.venv` and `DATABASE_URL`; Docker uses its pinned Python
3.11 runtime and independent database. Do not run the native frontend on port 3000
at the same time as Compose.

Checks from the repository root and frontend directory:

```sh
.venv/bin/python -m compileall -q backend tests
.venv/bin/python -m pytest -q
git diff --check
cd frontend
npm run typecheck
npm run lint
npm test
npm run build
```

Set `TEST_DATABASE_URL` to a separate disposable database for PostgreSQL integration
tests. Without it those tests skip. Browser tests use a mock backend on 8001 and a
test frontend on 3001, not the running Compose services. They mock action execution.
An existing Chromium executable can be selected with `PLAYWRIGHT_CHROMIUM_EXECUTABLE`.

## Troubleshooting and security limits

- Port 3000 already in use: stop the native Next.js process, then start Compose.
- Missing environment configuration: fill the named `.env` variable and rerun
  `docker compose config --quiet`. Do not print the credential value.
- Backend unhealthy: inspect local backend logs for configuration/schema errors
  and confirm PostgreSQL is healthy. Health checks do not validate external API credentials.
- API reads fail: verify the Sandbox app and merchant ownership. Do not switch to
  a production PayPal base URL or loosen the proxy's host allowlist.
- Missing history in Docker: the databases are separate. Do not trigger an action
  merely to populate the UI.
- Missing Buildx: the tested Compose version falls back to the classic builder.
  These Dockerfiles do not require BuildKit-only features.
- Dependency audit warnings: existing frontend dependencies report npm advisories.
  Review upgrades separately; do not run a forced breaking upgrade during a demo.

This is not public production authentication. Keep the frontend on loopback; do
not expose it through a public proxy, tunnel, or domain. Proper merchant login,
authorization, database privilege separation, and deployment hardening are required
before public deployment. Docker administrators can inspect container environment
variables, so access to the Docker daemon must also remain trusted.

The approval route still verifies ownership, explicit confirmation, current PayPal
permission, and atomic reservation. The unique approved-message constraint remains
unchanged. Ambiguous writes must be reconciled and are never automatically retried.
