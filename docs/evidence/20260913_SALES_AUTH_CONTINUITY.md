# Sales Xray authentication continuity

Date: 2026-09-13 (Asia/Kolkata). Source base: `6b130fb`. This bounded follow-up
connects the existing Sales sign-in URL, `/login?next=/sales-xray`, to learner
authentication. Implementation and automated validation are complete; canonical
browser acceptance is pending. This document does not claim deployment.

## Behavior and authority

Only the decoded literal `/sales-xray` is an accepted Sales destination. Query
arrays, double-encoded values, arbitrary paths and external URLs cannot choose
a destination. Builders emit fixed internal routes. The query does not carry
identity, tenant, role, enrollment or provider authority.

Existing course/activity continuation takes precedence over a Sales hint.
Onboarding's settings destination takes precedence over both. Requests without
context keep the existing v1 email shape; course context keeps v2. Sales-only
registration, recovery and verification resend use v3 events/jobs with exactly
`challenge_id`, `kind` and `next`. The worker allows only `/sales-xray` for `next`.
Verification/reset URLs carry that hint in the query and the one-time token in
the fragment. No database migration is introduced.

Password sign-in checks canonical onboarding status before continuing. Google
sign-in signs the exact internal return path `/onboarding?next=/sales-xray`.
Only that exact signed path can preserve Sales context in callback recovery.
An unlinked Google account retains the existing password sign-in fallback and
explicit registration/consent behavior. No email-based identity linking or
Google tenant-selection change is included.

Verification, reset, onboarding, retry and session-recovery links preserve the
bounded destination. Sales-only registration does not request free-course
enrollment. UI continuation labels identify Sales Xray; existing learner and
settings destinations retain their labels.

## Validation and release boundary

The frozen backend delta is three implementation paths (identity password
constants, HTTP auth and worker) plus four test paths: the existing worker suite
and new HTTP Sales email, HTTP Sales return and worker Sales email tests.
The source binding is `sales-auth-backend-source.json` in the recovery packet.
Main's expanded auth/identity/outbox/worker run passed **223 tests** in 8.35s
(`sales-auth-python-final.log`). Scoped Ruff/format and mypy pass for all three
backend source files. The tests exercise actual HTTP forwarding, strict payload
schemas, signed callback recovery, v1/v2 compatibility, v3 dispatcher membership,
receipt reuse and v3-to-v1 telemetry labels.

Main's frontend review identified two helper destination mistakes and an
activity-only plus Sales email-context conflict. The corrected source preserves
course/activity precedence in both links and request payloads; activity-only
email requests retain the legacy no-course shape rather than inventing a course
or selecting Sales. Independent Luna rereview found no remaining correctness or
security blocker. Full frontend validation after the final source freeze passed
**1,722 tests in 97 files** on Node 24.19.0, with a 384 MiB heap and one worker.
Learner types (640 MiB heap), scoped ESLint, Prettier and diff whitespace checks
pass. Receipts are `sales-auth-learner-all-final.log`,
`sales-auth-learner-types-final.log`, `sales-auth-learner-lint-final.log` and
`sales-auth-learner-format-final.log` in the recovery packet. The author's earlier
79-test run used Node 22; the final Node 24 suite supersedes that unsupported
runtime result. The actual staging handoff rendering also checks the fixed
origin and course/activity precedence.

The existing course/activity email cut is independently accepted at `02bdb91`
with evidence in `20260913_PASSWORD_EMAIL_CONTEXT_CONTINUITY.md`. This follow-up
adds separate v3 coverage and retains v1/v2 compatibility checks.

The local Sales-auth probe is in the recovery packet as
`probe-canonical-sales-auth.py` / `verify-canonical-sales-auth.ps1`. It uses
synthetic local identities and canonical API/outbox records with the actual
worker message resolver. The d2de worktree has no Sales workspace, so only the
terminal document request to `/sales-xray` is replaced by a clearly labeled
navigation sentinel. A Next client transition first asserts the terminal URL,
then reloads it for that sentinel. No authentication API response is mocked.
This scope can prove auth/session/return continuity; the real Sales workspace
still requires acceptance in the combined release.

The release owner has extracted the password message resolver into a shared
module-level function for the audited bootstrap command. Integration must apply
the v3 allowlist/link branch to that shared resolver and preserve its bootstrap
behavior. The held bootstrap command intentionally remains exact-v1; this cut
does not broaden it. No v3-unaware worker may consume new v3 events. The existing
installer stops the old worker before the new API starts, allowing durable
events to queue until the compatible worker starts.

No provider delivery, real-call processing, evaluation/scoring, Sales workspace
functionality or production promotion is claimed by this auth-only follow-up.
