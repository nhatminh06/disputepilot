# Offline evaluation

This suite runs 12 synthetic dispute scenarios through the production deterministic
evidence engine and recommendation validator. Mocked recommendation text is labeled
`OFFLINE_MOCKED`. It makes no PayPal, Gemini, approval, database, or write request and
does not require credentials.

From the repository root:

```sh
.venv/bin/python -m evaluation.run_evaluation
```

The command writes `evaluation/results.json` and `evaluation/REPORT.md`, prints one
line per scenario, and exits nonzero if any deterministic expectation, grounding
assertion, fallback probe, or agent safety check fails. Use `--check` to run without
rewriting reports.

The expectations are declared in `evaluation/scenarios.py`, independently of the
engine output. `NAD-01` and `AUTH-01` expect MEDIUM risk because the current rules
have verified payment but incomplete reason-specific evidence. LOW risk never
authorizes an action. Agent call-limit, iteration-limit, and deadline behavior is
also covered by the backend test suite.

This is a safety and grounding evaluation over synthetic fixtures. It does not
measure live Gemini accuracy, PayPal availability, or real merchant outcomes.
