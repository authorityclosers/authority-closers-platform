# v0.1 alpha candidate handoff

Evidence date: 2026-08-31 (Asia/Kolkata)
Branch: `codex/g1-free-course-foundation`
Base commit inspected: `491677803bce05f2eeb224bd8c13e11898756ad0`
Repository: `authorityclosers/authority-closers-platform` (private)

## Outcome

The worktree contains a coherent v0.1 implementation candidate for the
browser-first learner foundation: email/password identity, verification and
resend, recovery/reset, progressive onboarding, API-backed learner shell and
learning loop adapters, draft/evidence/progress states, PWA shell, separate
admin surface, modular API, migrations, tenancy/permission primitives,
deployment contracts, and tests.

This is **not** a launch declaration. Passing local gates does not prove CI,
deployment, a healthy PostgreSQL journey, or real email delivery.

## Verification performed

| Gate | Result |
|---|---|
| Repository ownership | PASS — `origin` and GitHub metadata resolve to private `authorityclosers/authority-closers-platform` |
| Full formatting/lint/type/test/build gate | PASS on the final worktree via `pnpm run validate` |
| Admin web tests | 67 passed |
| Learner web tests | 46 passed after final identity hardening |
| Python suite | 773 passed, 74 skipped, one dependency deprecation warning on the final worktree |
| Production Next builds | PASS — 15 learner routes and 8 admin routes generated |
| Alembic graph | one head; fresh password-identity migration added with duplicate-email preflight and forward-only downgrade |
| Desktop browser smoke | PASS at 1280x720 for login; registration, verification, recovery/reset shell, and onboarding exercised against deterministic mocked API responses |
| Mobile responsive smoke | PASS at 390x844 after touch-target correction; no horizontal overflow and no sub-44px interactive target found |
| PWA assets | manifest/service worker/offline shell present; PNG icons verified at 180, 192, and 512 square pixels |
| Token transport | PASS — email tokens use URL fragments, are removed from history, and are submitted only in JSON bodies |
| Production JavaScript dependency audit | PASS — patched workspace overrides for `sharp` 0.35.0 and `postcss` 8.5.23; `pnpm audit --prod` reports no known vulnerabilities |
| Local Python dependency audit | PASS — `uvx pip-audit --local` reports no known vulnerabilities; `uv pip check` reports compatible installed packages |
| Local frontend load probe | 800 requests, concurrency 25, 0 errors; 88.9 req/s; mean 270.06ms; p50 208.97ms; p95 719.76ms; p99 951.91ms; max 1550.53ms |

The Python skips are material: most are PostgreSQL, Docker, POSIX backup/lock,
or opt-in restore tests. They are not counted as runtime proof.

## Current published URLs (direct probe on evidence date)

| URL | Observed result | Meaning |
|---|---|---|
| `https://staging.authorityclosers.com/` | HTTP 200; page still displays “Preview surface” | old learner preview, not this candidate |
| `https://admin-staging.authorityclosers.com/` | HTTP 302 | Cloudflare Access boundary responds; no authenticated admin action was executed |
| `https://api-staging.authorityclosers.com/health/live` | HTTP 200, release `89be92d510d181574743200476731b7cc333d68c` | old API process is alive |
| `https://api-staging.authorityclosers.com/health/ready` | HTTP 200, same release | old API can reach its configured readiness dependency |

## Unresolved activation blockers

1. Local Docker Desktop cannot start because its stale `dockerInference`
   reparse point crashes the backend; WSL Ubuntu also lacks its `ext4.vhdx`.
   No PostgreSQL service was available, so the fresh end-to-end identity,
   migrations, tenant isolation, concurrency, backup, and restore gates were
   skipped here.
2. `resend` is deliberately rejected by the checked-in provider factory;
   `fake` delivery does not send mail. Verification/recovery is implemented and
   tested at service/API/worker boundaries but has no real delivery evidence.
3. The controlled four-module course seed is absent and conflicts with the old
   two-module preview fixture. No content topology was invented.
4. New learner tenant membership/selected-tenant provisioning semantics are
   unresolved in controlled sources. A verified new account therefore cannot
   be claimed to complete enrollment end to end.
5. The configured learner consent version is staging test material, not final
   production legal approval.
6. Edge and iOS Safari engine runs were unavailable. Chromium desktop/mobile
   viewport evidence is not cross-browser certification.
7. CI, authorized non-production security probing, database load/stress,
   deployment, rollback, and runtime observability evidence remain to be run
   against the exact committed candidate.
8. Repository documentation was updated; no authoritative Drive/Notion target
   ID was supplied or inferred, so external publication remains pending.

## Explicit non-claims

No future SaaS breadth, simulator/call-review engine, native Windows/iOS app,
billing, SSO/SCIM, broad enterprise functionality, autonomous official
scoring, real-call processing, production authentication, production backend
authorization, or production deployment is claimed.

## Release sequence

1. Repair or provide a healthy non-production PostgreSQL/Docker environment.
2. Run all currently skipped PostgreSQL, concurrency, backup/restore, and
   password-journey tests; fix and rerun.
3. Resolve controlled seed and learner tenant-provisioning decisions.
4. Complete the approved email-provider governance gate and runtime proof.
5. Run Edge and iOS Safari, accessibility automation/manual checks, security
   probes, database load/stress, failure recovery, and observability checks.
6. Commit, review, push, let CI pass, deploy the exact immutable artifact to
   staging, verify critical journeys and rollback, then update this evidence.
