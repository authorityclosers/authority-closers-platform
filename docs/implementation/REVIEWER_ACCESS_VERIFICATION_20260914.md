# Independent reviewer access verification — 2026-09-14

This lane starts from `30cd7a8d1aed95e8ead2ee737c9cfa6574d4d599` on
`codex/reviewer-independent-access-20260914`. The release owner reserves migration
`20260914_0038` and owns integration, hosted delivery, infrastructure and deployment.
No hosted application, production database, mail provider or paid provider was
changed by this lane.

## Requirement and implementation

The same global Person/email may independently have learner, Admin and reviewer
access. Reviewer admission creates no learner enrollment or membership. Learner
navigation and routes expose no review UI; ordinary account sessions cannot read,
play or write through the reviewer API. Admin invites, inspects saved feedback and
revokes access using its own authority. See `REVIEWER_ACCESS_SEPARATION.md` for the
complete session, challenge, grant, source and audit boundaries.

## Reproducible checks

The Python command uses the repository's configured environment and
`PYTHONPATH=packages/python`. PostgreSQL tests require the repository's disposable
loopback test URL; they migrate random schemas and never use production data.

| Check | Result |
| --- | --- |
| Identity, generic auth routes/transactions, review HTTP, worker, provider and model registry tests | 239 passed |
| Security rate-limit suite, including real request/verification bucket exhaustion | 12 passed |
| Combined reviewer PostgreSQL HTTP/service/deactivation and populated migration metadata | 11 passed |
| Expanded HTTP proof for new, learner, and Admin-plus-learner personas, plus uninvited request | 4 passed |
| Full Admin UI suite | 809 passed |
| Provider cap preservation, model edit, new/enlarged cap rejection and final paid provider removal | 9 passed |
| Scoped Python mypy (identity and reviewer HTTP/service/worker) | 14 files passed |
| Admin lint and typecheck | passed |
| Changed Python Ruff lint and formatting | 29 files passed |
| Fresh Admin production build | passed |
| Actual production browser journey with PostgreSQL and durable mail jobs | 1 passed |

The expanded HTTP proof additionally checks mixed-case mailbox input, real durable
invitation and sign-in email jobs, wrong-browser and missing-nonce denial without
consuming the legitimate challenge, cooldown retry, replay, both cookie-swap
directions, generic logout isolation, learner context selection, three feedback
lenses, immutable retries, private source byte ranges, Admin inspection, revocation
and independent reviewer logout. Model registry comparison confirms the populated
migration schema matches the registered SQLAlchemy models.

Commands used include:

```text
pytest tests/unit/identity tests/unit/http/test_auth_routes.py tests/unit/http/test_auth_transactions.py tests/unit/http/test_conversation_reviews.py tests/unit/worker tests/unit/providers/test_providers.py tests/database/test_model_registry.py -q
pytest tests/security/test_rate_limits.py -q
pytest tests/database/test_reviewer_access_http_postgresql.py tests/database/test_conversation_reviews_postgresql.py tests/database/test_reviewer_access_p2_postgresql.py tests/database/test_conversation_postgresql.py::test_populated_migration_head_matches_real_model_registry -q
pnpm --filter @ac/admin-web test
pnpm --filter @ac/admin-web typecheck
pnpm --filter @ac/admin-web lint
pnpm --filter @ac/admin-web build
```

Local machine receipts are retained outside Git under
`D:/AC-authority-closers-release-audit/`, including
`reviewer-unit-final-02.xml`, `reviewer-admin-full-02.xml`,
`reviewer-access-nonce-and-service-pg-01.xml`, and
`reviewer-access-three-personas-pg-03.xml`. Earlier failed receipts are retained;
the final results supersede them.

The final browser receipt is `reviewer-access-browser-production-pg-07.xml`;
screenshots, source hashes and network status evidence are in
`reviewer-browser-production-07/`. A copy of the completed structured receipt is
tracked beside this document as `REVIEWER_ACCESS_BROWSER_PROOF_20260914.json`.
The real browser journey sent an Admin invitation, delivered both transactional
jobs, rejected a copied sign-in token in another browser, opened the protected
assignment through production middleware, exercised dirty-navigation and logout
guards, saved all three lenses, reloaded immutable history, played actual source
audio and read a byte range, displayed all feedback in Admin, revoked access,
confirmed source removal, and signed the reviewer out while Admin remained signed
in. Screenshots at 1440, 390 and 320 pixels were inspected; there was no horizontal
overflow and no browser page error.

The browser proof is `scripts/prove-reviewer-access-browser.py`. It requires a
compiled production Admin app on loopback (default `http://127.0.0.1:3192`), a
disposable PostgreSQL test URL, Playwright Chromium, and local TLS certificate/key
paths in `REVIEWER_UI_TLS_CERT` and `REVIEWER_UI_TLS_KEY`. Set a fresh evidence
directory in `REVIEWER_UI_EVIDENCE_DIR`. The proof owns loopback ports 443 and 8000;
Chromium maps only `admin-staging.authorityclosers.com` to loopback. The isolated
Next process uses `AC_ADMIN_APP_URL=https://admin-staging.authorityclosers.com`,
`AC_INTERNAL_API_URL=http://api.staging.ac.internal.invalid:8000` and matching
`AC_INTERNAL_API_HOST`, with a process-local DNS override mapping that internal
hostname to loopback. No system DNS or hosted service is modified. The test uses
actual durable email jobs and session resolvers with a fake delivery adapter and
synthetic source, with no Playwright route interception. It writes screenshot and
source hashes only after the full journey passes.

## Independent review and repaired failures

Luna xhigh agents performed the identity implementation, UI implementation and
independent security review. The security review found login CSRF in a token-only
magic link. The final challenge requires a hashed browser nonce and rejects a
foreign browser before consuming its token. Re-review found the binding complete.
The review also added active-tenant queue/delivery checks and consistent normalized
recipient comparisons. Generic account and reviewer audience rejection were
independently inspected.

The production Next.js browser proof exposed Node 24 `fetch` dropping the explicit
Admin Host header on the server-side reviewer identity request. The resolver now
uses native HTTP with the validated internal endpoint and canonical Admin Host,
forwards only the reviewer cookie, and enforces a three-second timeout, 16 KiB
response limit, exact success status and identity schema. A real loopback HTTP
test verifies the received Host and cookie; the independent security re-review
found the production call path safe. Production sign-in and protected navigation
passed after the repair.

The browser also caught transcript content overflowing its card at 390 pixels.
The final scoped CSS allows grid children to shrink, wraps the heading, and breaks
long transcript/hash text. The repeated production journey passed at 390 and 320
pixels after the repair. Earlier failed browser receipts are preserved rather than
rewritten.

The real worker proof exposed a missing telemetry allowlist entry for the new
reviewer mail job. The exact new job was added and the durable worker proof passed.
The broader registry test required the new table in its explicit inventory. The
mixed-case test mail helper now compares normalized recipient identity. Generic
logout remains idempotent (204) and demonstrably does not revoke reviewer access.

The local C1 fixture uses the ignored native AudioAtlas executable whose binary
and pinned source hashes were checked before reuse. No source gate was bypassed.

## Provider editor follow-up

The release owner separately authorized fixing the existing provider editor's
unconditional reset of paid policy, approval reference and provider caps. A model
edit now uses the saved current configuration as the baseline, preserves its
policy/reference and same-provider cap, and continues to set auto-purchase false.
New, switched or enlarged caps are reduced to zero. Removing the final paid
provider prompts a configuration correction before sending an invalid request.

This is editor preservation behavior. Backend owner-controlled budget approval,
the initial hosted registry save, quotes, execution and provider purchases remain
outside this slice and under the release owner's existing authorization.

## Hosted acceptance

The release owner must integrate the reviewed leaf, run CI and the forward
migration, verify the deployed reviewer routes and perform the authorized live
delivery check. Local fake-adapter success does not prove live inbox delivery.
