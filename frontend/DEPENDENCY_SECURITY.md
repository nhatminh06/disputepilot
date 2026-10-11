# Frontend dependency security review

Audit date: 2026-10-11

## Results

The reproducible `npm ci` install contains five high-severity audit entries and no
critical entries. `npm audit --omit=dev` reports zero production vulnerabilities.
All five entries describe one development-only dependency chain:

`eslint-config-next@16.4.0` -> `@next/eslint-plugin-next@16.4.0` ->
`fast-glob@3.3.1` -> `micromatch@4.0.8` -> `braces@3.0.3`

| Package | Relationship | npm affected range | Advisory or cause | Patched version |
| --- | --- | --- | --- | --- |
| `braces@3.0.3` | Transitive development dependency | `<=3.0.3` | [GHSA-vfj7-8cjw-p6xm](https://github.com/advisories/GHSA-vfj7-8cjw-p6xm), CVE-2026-93687 | None published |
| `micromatch@4.0.8` | Transitive development dependency | `>=0.2.0` in npm audit | Inherits the `braces` advisory | None through the current chain |
| `fast-glob@3.3.1` | Transitive development dependency | All versions in npm audit | Inherits through `micromatch` | None through the current chain |
| `@next/eslint-plugin-next@16.4.0` | Transitive development dependency | `>=14.3.0-canary.0` in npm audit | Inherits through `fast-glob` | None compatible with the current Next.js line |
| `eslint-config-next@16.4.0` | Direct development dependency | `>=14.3.0-canary.0` in npm audit | Inherits through the plugin | No compatible remediation reported |

The root issue is uncontrolled recursion when `braces` parses deeply nested brace
patterns. DisputePilot reaches this chain through `npm run lint`, using repository
files and lint configuration rather than browser or API input. A malicious repository
change could still terminate the lint process, so this remains a development and CI
availability risk.

The Docker build stage installs development dependencies. The image build runs
`npm run build`, not `npm run lint`; the affected lint packages are present in that
temporary stage but are not invoked by the documented build command. Inspection of
the final standalone runtime image confirmed that `braces`, `micromatch`,
`fast-glob`, `eslint`, and `eslint-config-next` are absent. `next` is present. The
advisory is therefore not shipped in the request-serving image.

## Remediation decision

No package was updated. The latest published `braces` version is still 3.0.3, and
the advisory lists no patched version. `npm audit fix --dry-run` proposed replacing
`eslint-config-next@16.4.0` with 14.2.35 and marked the change as semver-major. That
would mismatch `next@16.4.0`, so it was rejected. Upgrading `fast-glob` alone does
not remove its `micromatch` and `braces` dependency. No override or audit suppression
was added.

Recheck the advisory before release and update the Next.js lint chain when an
upstream compatible fix is published. Treat lint input and repository changes as
trusted until then.

## Verification

- Initial audit: five high, zero critical; all in the development lint chain.
- Production audit: zero vulnerabilities with `npm audit --omit=dev`.
- Runtime inspection: affected packages absent from the final standalone image.
- `npm ci`, TypeScript, ESLint, and 55 Playwright tests completed successfully.
- The pinned Node 24 Docker production build completed successfully. Host
  `npm run build` under Node 26.10.0 compiled the application, then Next.js 16.4.0
  failed while parsing TypeScript's captured `--showConfig` output. Direct
  TypeScript checks passed. The Docker build is the reproducible release build;
  the host Node 26 tooling mismatch remains documented rather than changing the
  dependency graph during this audit.
- Desktop and mobile runtime smoke checks returned HTTP 200, loaded seven local
  assets, made no external or write requests, and had no horizontal overflow.
- The Compose frontend remained loopback-only and PayPal writes remained disabled.
