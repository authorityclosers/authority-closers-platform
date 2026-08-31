# v0.1 alpha candidate handoff

Evidence date: 2026-08-31 (Asia/Kolkata)
Branch: `codex/g1-free-course-foundation`
Base commit inspected: `dd1757c880da4c2e6f966f6edbb05baea0e1d98d`
Repository: `authorityclosers/authority-closers-platform` (private)
Hosted baseline: `dd1757c880da4c2e6f966f6edbb05baea0e1d98d`
Current delta: uncommitted; exact candidate SHA and hosted CI are pending

## Outcome

The worktree contains a coherent v0.1 implementation candidate for the
browser-first learner foundation: email/password identity, verification and
resend, recovery/reset, progressive onboarding, API-backed learner shell and
learning loop adapters, draft/evidence/progress states, PWA shell, separate
admin surface, modular API, migrations, tenancy/permission primitives,
deployment contracts, and tests. The current delta adds the controlled
four-shift topology with the complete Module 1 loop, exact-tenant learner
provisioning, a bounded Resend transactional adapter, and explicit
18+/service-email staging consent.

This is **not** a launch declaration. Passing local gates does not prove fresh
hosted CI, deployment, staging seeding, or real email delivery.

## Verification performed

| Gate | Result |
|---|---|
| Repository ownership | PASS — `origin` and GitHub metadata resolve to private `authorityclosers/authority-closers-platform` |
| Full formatting/lint/type/test/build gate | PASS on the current uncommitted worktree via `pnpm run validate`; rerun on the exact commit in hosted CI |
| Admin web tests | 67 passed |
| Learner web tests | 46 passed after final identity hardening |
| Fresh PostgreSQL runtime | PASS — disposable pinned PostgreSQL 18 container, migrations through `20260830_0011`, `alembic check` clean, runtime/migrator/owner role separation exercised |
| Python suite | 896 passed, 7 skipped, one dependency deprecation warning on the current uncommitted worktree |
| Candidate wheel | PASS locally — the built wheel contains `ac_platform/seed/data/free_course_foundation_v1.json`; exact-commit packaging remains pending |
| Hosted application CI | PASS for baseline `dd1757c` on [workflow 33339057014](https://github.com/authorityclosers/authority-closers-platform/actions/runs/33339057014); fresh candidate CI is pending |
| Hosted control-plane CI | PASS for baseline `dd1757c` on [workflow 33339057010](https://github.com/authorityclosers/authority-closers-platform/actions/runs/33339057010); fresh candidate CI is pending |
| Production Next builds | PASS — 15 learner routes and 8 admin routes generated |
| Alembic graph | one head; fresh password-identity migration added with duplicate-email preflight and forward-only downgrade |
| Docker-backed composed services | PASS — PostgreSQL, Mailpit, and Jaeger healthy; API liveness/readiness, learner manifest/offline/auth routes, separate admin preview routes, and Windows worker startup exercised |
| Desktop browser smoke | PASS at 1440x900 for learner public/auth/policy/protected boundaries, universal states, and six separate admin/studio surfaces |
| Mobile responsive smoke | PASS at 390x844 for key learner/admin routes; no horizontal overflow on checked mobile or desktop routes |
| Screenshot evidence | PASS — 32 indexed captures in [`screenshots/v0.1-local/`](screenshots/v0.1-local/README.md), each labeled by route and evidence boundary |
| PWA assets | manifest/service worker/offline shell present; PNG icons verified at 180, 192, and 512 square pixels |
| Token transport | PASS — email tokens use URL fragments, are removed from history, and are submitted only in JSON bodies |
| Production JavaScript dependency audit | PASS — patched workspace overrides for `sharp` 0.35.0 and `postcss` 8.5.23; `pnpm audit --prod` reports no known vulnerabilities |
| Local Python dependency audit | PASS — `uvx pip-audit --local` reports no known vulnerabilities; `uv pip check` reports compatible installed packages |
| Local frontend load probe | 800 requests, concurrency 25, 0 errors; 88.9 req/s; mean 270.06ms; p50 208.97ms; p95 719.76ms; p99 951.91ms; max 1550.53ms |

The seven Python skips are explicit: four Bash-syntax proofs run on POSIX CI,
two POSIX file-lock proofs are unavailable on Windows, and one live restore
drill requires an approved dump and explicit opt-in. PostgreSQL, strict
staging-seed, catalog-concurrency, learning HTTP, identity/session,
exact-tenant provisioning, operations, and runtime-privilege tests ran.

## Current published URLs (direct probe on evidence date)

| URL | Observed result | Meaning |
|---|---|---|
| `https://staging.authorityclosers.com/` | HTTP 200; page still displays “Preview surface” | old learner preview, not this candidate |
| `https://admin-staging.authorityclosers.com/` | HTTP 302 | Cloudflare Access boundary responds; no authenticated admin action was executed |
| `https://api-staging.authorityclosers.com/health/live` | HTTP 200, release `89be92d510d181574743200476731b7cc333d68c` | old API process is alive |
| `https://api-staging.authorityclosers.com/health/ready` | HTTP 200, same release | old API can reach its configured readiness dependency |

## Unresolved activation blockers

1. The exact candidate SHA and fresh hosted Node 24/Linux CI do not exist yet.
   Local Node 22 emits the expected engine warning; it is not the release
   authority even though the complete gate passes locally.
2. The bounded Resend adapter is implemented, but checked-in profiles remain
   `fake`. Provider credentials/sender activation, monitoring, and a real
   verification plus recovery delivery proof remain pending.
3. The controlled four-shift/Module 1 foundation is implemented and present in
   a locally inspected wheel. Fresh PostgreSQL seed application and
   idempotency pass, but approved staging execution requires an exact release
   artifact and canonical existing admin/owner actor. Catalog/API reads and
   exact-release staging verification remain pending. Final course copy/media
   and later-module content remain unclaimed.
4. Exact-tenant learner provisioning is implemented without tenant creation,
   role change, or membership reactivation. Fresh PostgreSQL and password
   session integration tests pass; exact staging tenant configuration and a
   deployed browser cohort journey remain pending. No staging cohort or
   end-to-end enrollment is claimed yet.
5. The configured learner consent version is staging test material, not final
   production legal approval.
6. Edge and iOS Safari engine runs were unavailable. Chromium desktop/mobile
   viewport evidence is not cross-browser certification.
7. Authorized non-production security probing, database load/stress,
   deployment, rollback, and runtime observability evidence remain to be run
   against the exact committed candidate. Release image packaging and
   transport-digest proof remain pending while the pull request is draft.
8. Repository documentation was updated. The exact existing Drive handoff
   folder (`13EZMwDgjK4SrE5PwD5PPHPohZ7AQv6Oo`) and Notion implementation page
   (`3ccf0c5d-822d-8160-94f6-d4875e9043f4`) are identified; publication waits
   for an exact commit and hosted-CI evidence so those systems do not record an
   unverified candidate as a release.

## Explicit non-claims

No future SaaS breadth, simulator/call-review engine, native Windows/iOS app,
billing, SSO/SCIM, broad enterprise functionality, autonomous official
scoring, real-call processing, production authentication, production backend
authorization, or production deployment is claimed.

## Release sequence

1. Commit the reviewed worktree and run fresh hosted Node 24/Linux PostgreSQL
   CI for the implemented seed and exact-tenant
   provisioning contracts.
2. Build and attest immutable release images, then configure the exact staging
   tenant, apply the controlled seed, and complete
   the email-provider governance and runtime proof.
3. Run Edge and iOS Safari, accessibility automation/manual checks, security
   probes, database load/stress, failure recovery, and observability checks.
4. Complete independent review, take the PR out of draft only when the open
   gates close, package images, and deploy the exact immutable artifact to
   staging, verify critical journeys and rollback, then update this evidence.
