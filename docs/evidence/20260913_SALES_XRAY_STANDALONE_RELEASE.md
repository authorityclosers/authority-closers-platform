# Sales Xray standalone release candidate

The standalone client now has an existing-account AC login and explicit workspace
selection. It uses the current AC API/session/tenancy boundaries. The server admits
only the source-owned staging and production Sales Xray origins; Google transaction
state binds the exact host and authentication surface. Registration/linking stay
on the existing account surfaces. The LMS client remains separate.

The new companion workflow packages the web image independently of the four-image
core manifest. Source-owned edge routes send API requests to the existing API and
pages to the bounded companion container. The artifact verifier checks the source,
trusted metadata hash, archive, OCI manifest/config identity and runtime contract
without shell-sourcing downloaded metadata. Operator steps and rollback boundaries
are in `infra/sales-xray-web/README.md`.

## Executed local validation

Receipts are retained outside Git in
`D:/Projects/authority-closers-release-transfer/2026-09-13-sales-xray/receipts`.

| Check                                                                  | Result                           | Receipt                                  |
| ---------------------------------------------------------------------- | -------------------------------- | ---------------------------------------- |
| Identity, host, origin, OAuth state and settings                       | 273 passed                       | `0032-standalone-identity.xml`           |
| Offline image artifact verifier                                        | 8 passed                         | `0032-web-artifact-verifier.xml`         |
| All standalone frontend suites                                         | 41 passed                        | `0032-standalone-ui.xml`                 |
| Actual Chromium upload and saved/durable report regressions            | 2 passed, 102.65 seconds         | `0032-callstudio-standalone-wrapper.xml` |
| Actual Chromium password/workspace/logout journey                      | 1 passed, 21.37 seconds          | `0032-standalone-browser-02.xml`         |
| Production Next build for local static preview                         | Passed, `/`, `/login`, `/health` | `0032-standalone-build.log`              |
| Strict Python types for changed settings/auth/API files                | Passed                           | `0032-standalone-auth-mypy.log`          |
| Workflow Bash/Python syntax, pinned actions, compose/resource contract | Passed                           | `0032-web-static.json`                   |

These four test groups total 325 passing tests for this candidate; they are not a
count of distinct tests across every prior Sales Xray receipt. Frontend typecheck,
Ruff, Prettier and diff whitespace checks also passed.

The browser runs use the actual built frontend, real loopback TCP, AC HTTP routes,
cookie authentication and disposable PostgreSQL schemas. Test accounts, recordings
and report content are synthetic. No API route is replaced by a mock. The durable
provider broker in the report fixture is synthetic; no external inference occurs.

The login journey proves an anonymous home without a private history request,
password login, two server-provided workspace choices, explicit successful
selection, access to the assigned private history, denial of a foreign tenant,
host-only HttpOnly/Lax cookie and logout followed by anonymous denial. Its evidence
directory contains screenshots and `standalone-auth-browser.json`. Loopback uses an
insecure cookie intentionally; the deployment unit tests separately assert Secure
host-only cookies. Real deployed TLS and Google sign-in still need release testing.

The first login receipt (`0032-standalone-browser-01`) is preserved as a failure:
Chromium recorded navigation cancellations despite successful login/logout statuses
and proven session effects. The corrected test preserves every request event and
accepts only Next's `HEAD /` navigation probe and the exact login/logout response
cancellations after their success statuses and state checks pass. All other failed
requests still fail. The passing receipt has no external requests, JavaScript
errors or unexpected request failures.

## Release-owner infrastructure proof

Release Recovery reported a read-only successful validation using pinned
`caddy@sha256:5f5c8640aae01df9654968d946d8f1a56c497f1dd5c5cda4cf95ab7c14d58648`
with networking disabled and the existing foundation context. The tested route
file hashes match this candidate:

- Staging: `924a9565756118ced2b8f2bd7f9b448892bc958a11da45472f2c8a59633737d9`.
- Production: `d5acbb47365e8678ed8a3343be36ce26220e907cedec050cd6288082620bb5a0`.
- Existing foundation: `d3f81d721ffacffe856124189c8390e4934fe2d578dd2b11fed6b3d0aaf439d6`.

Their actual VPS snapshot at 2026-09-13 06:09:40 UTC reported four CPUs,
13,284 MiB available RAM, 143 GB available root disk, and load 0.20/0.35/0.37.
The two additional 384 MiB / 0.5 CPU frontend caps fit that snapshot. This is a
capacity observation, not a sustained processing load test. Neither this validation
nor the snapshot changed the active edge.

## Publication status at source freeze

This is a locally tested release candidate. Its new image workflow has not run
here (no local Docker daemon), and this evidence does not assert Sales Xray is
staged or production-published. Release Recovery owns exact-SHA integration, CI,
verified image loading, source-owned edge activation, DNS/tunnel callbacks, hosted
service activation, real staging/production browser tests, canary and rollback.
The prior private recording approval is expired; this patch does not renew it or
grant provider permission. Numeric coaching publication remains held for the
preserved 95 actual / 100 declared source-weight discrepancy.

## Subsequent integration regressions

Commit `c7c19ff95ff0eb9b0cac0b4d5972ac095c91bb55` adds the optional exact Sales Xray
origin to the release installer's strict profile contract and clears ambient
overrides before Compose. Six new Bash-backed tests and all 18 existing profile
tests passed. Receipts: `0032-installer-sales-xray-profile-new-6.xml` and
`0032-installer-sales-xray-profile-existing-18-pathfixed.xml`. Earlier Windows
receipts retain a missing-`grep` harness failure; running with the installed Git
Bash utilities proves the CRLF rejection without changing that gate.

Full CI run `34741929166` tested source `f0e00a6c5b36525d54c19807aae6458812344888`,
whose report test fixture retained a helper that patched `CONTROL_ACCOUNT` to a
different email from its verified admin fixture. The corrected `4904d70` fixture
uses the actual admission rule and removes that helper. Its report, HTTP and
browser dependent files must be integrated together so no removed helper remains
imported. This correction changes test setup, not production authorization.

Fresh PostgreSQL checks on the corrected source passed:

- All six report-store cases: `0032-report-control-ci-regression.xml`, 14.89 seconds.
- Cookie-authenticated history/transcript/private playback:
  `0032-report-control-http-ci-regression.xml`, one passed, 14.27 seconds.
- A new verified-admin case with a different email:
  `0032-report-control-admin-denial.xml`, one passed, 11.24 seconds. It preserves
  the admin role and capability, changes only the exact control identity, proves
  admission denial and verifies that zero report drafts were inserted. No provider
  policy is monkeypatched. This replaces the obsolete fixture-specific seam
  assumption with a direct negative authorization regression.

The two actual browser regressions in the earlier table cover the other dependent
flow. These receipts support the corrected candidate; the integrated release still
requires its own passing CI and deployed acceptance.
