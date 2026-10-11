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

## Live recommendation benchmark

Preview all 12 sanitized inputs without credentials, model requests, or report writes:

```sh
.venv/bin/python -m evaluation.run_evaluation --live --dry-run
```

Only after separate explicit authorization for live execution:

```sh
.venv/bin/python -m evaluation.run_evaluation --live --confirm-live
```

Both flags and `GEMINI_API_KEY` are required. `GEMINI_MODEL` must be unset or exactly
`gemini-3.1-flash-lite`. The command never switches models or enables billing. It
uses the configured key; billing/free-tier status must be checked in the provider
account. Without `--live`, behavior stays offline. Automated tests mock the SDK.

The benchmark calls production `gemini.recommend` once per scenario with validation
retries disabled. The SDK uses one attempt, including the original request. The
maximum is 12 sequential requests. Quota, authentication, transport, or other API
errors stop the remaining scenarios; validation failures advance to the next case.
There is no automatic resume, retry, or rerun. The recommendation workflow is used,
not the multi-request tool-calling agent.

Live results go only to `evaluation/live_results.json` and
`evaluation/LIVE_REPORT.md`. Existing offline reports stay unchanged. Live reports
are checkpointed before and after every request, with remaining cases marked
SKIPPED. An interrupted request is potentially quota-consuming and requires review.
Existing live reports block another run. Archive them deliberately before any
separately authorized future evaluation. Each report file is replaced atomically;
JSON is authoritative if a crash occurs between the two replacements.

Metrics separate first-response schema checks, first-response citation checks,
production validation, and final application safety. Their numerator and denominator
are explicit. A completed model request means an SDK generation response was
returned, including invalid output; it excludes API errors and timeouts. First-response
rates use those returned responses, with invalid schemas failing the citation check.
Application safety uses cases with a final application result, including fallbacks.
It measures the production validator, unchanged deterministic assessment, and
Python-derived missing facts. Narrative heuristics are scored separately and can
flag a response even when application validation accepts it.
Review compliance uses first responses to review-required cases, never fallback text.
LOW-risk NEEDS_REVIEW is conservative abstention only when validated without fallback.
LOW-risk REFUND is an expectation mismatch and never causes an action.

Token totals sum only reported usage and include coverage counts. Unknown usage is
null, not zero. Latencies include the production call and validation. Model output
is kept separately from fallback output so unsupported text remains reviewable.
Narrative review is a simple pattern heuristic, not a truthfulness score. It can
flag negated claims and miss paraphrases. Review the first-response text manually,
especially SAFE-02. Schema success alone does not establish injection resistance.
An observed instruction-following pattern or unsupported narrative makes the command
exit nonzero even if production validation accepted it. Missing-information lists
remain Python-derived; the original model list is retained for comparison.

Only SAFE-02 supplies a policy excerpt: the existing malicious synthetic fixture.
Other synthetic policy assessments are evidence facts, not retrieved policy excerpts.
The sanitizer removes order-description and authorization prose while retaining fact
statuses and supporting IDs. This may increase conservative abstention.

`requests_started` includes the reservation for an interrupted request and is an
upper bound in that case. `requests_with_known_attempt_count` sums the production
call counter only where a result returned. Provider receipt and token consumption
cannot be determined for ambiguous network outcomes.

## Citation schema version 2

Recommendations now include `adverse_fact_ids`. Historical responses without this
field load with an empty list. Supporting citations remain restricted to deterministic
supporting facts. Adverse citations require a VERIFIED fact with its own singleton
FAIL rule and exclusion from the supporting set. General consistency failures do
not establish adverse facts. UNKNOWN and MISSING facts cannot be cited in either
category. Missing information remains derived by Python.

New evaluation metadata records `citation_schema_version: 2`; citation checks cover
both categories. Existing live reports remain unchanged and describe the earlier
schema. Mocked INR-05 and INR-06 regression checks do not establish improved live
model performance. Run the offline suite with `--check` to preserve stored reports.
