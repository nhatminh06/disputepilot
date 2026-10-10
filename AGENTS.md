# AGENTS.md

Rules for any coding agent working in this repo. Read fully before making changes.

## Project

DisputePilot: a solo hackathon project (PayPal AI Hackathon). An agent investigates PayPal disputes with read-only tools, deterministic rules build the evidence checklist and risk level, an LLM explains and recommends CONTEST, REFUND, or NEEDS_REVIEW, and a merchant approves before a separate endpoint calls PayPal.

Stack: Python 3.11 + FastAPI, Next.js + TypeScript, PostgreSQL, Docker Compose.

## Scope discipline

- Build only what the current task asks for. Do not scaffold ahead.
- Until told otherwise, work is limited to `spike/`. No backend, frontend, DB, Docker, CI, or agent code.
- No new dependencies without saying why. Prefer the standard library.
- No extra abstractions, base classes, plugin systems, or config layers "for later".
- If a task is unclear, make the smallest reasonable assumption and state it in one line.

## No AI slop

- No filler comments. Do not narrate what the code obviously does. Comment only to explain why something non-obvious is done.
- No boilerplate docstrings that repeat the function name. Add a docstring only when behavior is not clear from the signature.
- No emojis in code, comments, logs, commit messages, or docs.
- No marketing language in code or docs ("robust", "seamless", "powerful", "leverage", "cutting-edge").
- No em dashes in prose. Use periods, commas, or colons.
- No placeholder code: no `TODO: implement`, no stub functions returning fake data, no `pass` bodies left behind.
- No invented facts, endpoints, fields, metrics, or test results. If unverified, say so.
- No dead code, unused imports, or commented-out code.
- No excessive try/except. Handle only errors that can actually happen and say what to do about them.
- Short, plain names. Small functions. Flat structure.
- Output a diff or the changed code. Do not add long explanations after it.

## No AI attribution in the repo

- No `Co-authored-by` trailers, "Generated with", "Written by AI", or tool names in commit messages.
- No AI or tool attribution in code comments, file headers, README, docs, or PR text.
- Commit messages: short, imperative, lowercase, one line. Example: `add dispute detail fetch`.
- Do not mention the assistant, prompts, or generation in any file committed to the repo.

## PayPal rules

- Sandbox only. Abort if `PAYPAL_BASE_URL` does not contain `sandbox`.
- Verify every endpoint path and request body against current docs at developer.paypal.com. Do not rely on memory. If you cannot verify, add a comment saying so and print a warning at runtime.
- Always print HTTP status and response body (truncated) on failure. Never swallow errors.
- Send an idempotency key (`PayPal-Request-Id`) on every create, capture, and refund request.
- Verify webhook signatures before processing any webhook.

## Safety architecture (never violate)

- The agent module only gets read-only tools: `get_dispute`, `get_order`, `get_shipping`, `search_policy`.
- Write functions (refund, submit evidence, accept claim, add tracking) live in a separate module that the agent module never imports.
- Only `POST /disputes/{id}/approve` may call write functions, and only after it checks: the run belongs to the dispute, a human approval is recorded, the action was not already executed, and the action is allowed for that dispute reason.
- The LLM never produces confidence scores. Facts and risk come from deterministic rules. The LLM explains and recommends.
- The LLM may only cite fact IDs the evidence engine produced. Reject the run if it cites anything else.
- Agent limits: max 6 tool calls, max 4 iterations, 20 second timeout. On failure, return NEEDS_REVIEW.

## Secrets

- Never print, log, or commit the client secret or access tokens.
- `.env` stays in `.gitignore`. Keep a `.env.example` with placeholders only.
- Never hardcode credentials, even for sandbox.

## Code style

- Python: type hints on public functions, `ruff` clean, `pytest` for tests.
- TypeScript: strict mode, no `any`.
- Tests cover behavior (rules, validation, approval gate), not trivial getters.
- Every new rule in the evidence engine gets a test.

## Before you finish a task

- Run it. Report the actual output, not what you expect it to be.
- List any assumption made and anything left unverified.
- Do not claim something works unless it was run.