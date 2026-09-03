# Learner UI, offline, and staging candidate evidence

Date: 2026-09-04

This record describes the candidate now represented by exact release
`65ea3e1094ae462c071a70ef2463f5a8c7754196`. GitHub Application validation,
artifact identity, and trusted staging controller smoke are recorded in the
[exact-release evidence record](../knowledge/v0.1-alpha/EVD-006-exact-staging-65ea3e1.md);
the earlier `5c7333c5` record remains retained in
[EVD-005](../knowledge/v0.1-alpha/EVD-005-exact-staging-5c7333c5.md). This
document does not expand the bounded proof into full capability or production
approval.

## Implemented scope

- Premium learner shell with desktop sidebar/header and a five-item mobile tab
  bar, responsive at 1440 × 1024 and 390 × 844.
- Dashboard composition derived from canonical identity, catalog, enrollment,
  ordered activities, allowed actions, and the server progress projection.
- Learning, Discover, Progress, Notifications, Profile, Settings, program,
  module, activity, completion, and certificate route families with explicit
  loading, empty, failure, permission, locked, partial, offline, and success
  states as applicable.
- AES-GCM encrypted, seven-day-bounded, person/tenant/session-scoped offline
  read cache with recursive provenance, tamper/expiry/authorization cleanup,
  visible stale labeling, and disabled mutation paths.
- Development proxy restricted to the exact configured staging origin and
  anonymous catalog GETs; cookies and authorization are stripped, while private
  reads and all mutations fail before an upstream request.
- Provider-neutral media asset/playback contracts and unit evidence. No player,
  external provider, or real-call processing is activated.

## Truth boundary

The reference imagery contains scheduled times, coaching/calendar sessions,
weekly duration analytics, multiple enrolled-course summaries, notification
state, launch dates, media artwork, and playback. Those capabilities do not
have approved first-slice contracts or canonical data sources. The candidate
therefore preserves the reference hierarchy while rendering real projection
and catalog fields or explicit unavailable/empty copy. Production surfaces
contain no demo identity, fake enrollment, invented 65% progress, schedule,
coach, analytics, launch, or notify-me state. Generated references and
decorative artwork are never used as an API or canonical-state fallback.

## Verification

- Learner web: 17 files / 248 tests passed; zero-warning ESLint, TypeScript,
  optimized Next production build, repository formatting, service-worker
  syntax, and `git diff --check` passed on the active working tree. Exact-SHA CI
  remains a post-commit gate. The workstation is on Node 22.17.0 while the
  declared/CI runtime is Node 24, so CI remains authoritative.
- Admin web regression gate: 5 files / 71 tests passed; zero-warning ESLint,
  TypeScript, and the optimized Next production build passed after the shared
  Authority Closers brand mark change.
- Focused backend/API/domain/media audit: 254 tests passed with one existing
  warning; Ruff and mypy passed across 99 Python source files. Fourteen
  PostgreSQL cases remain environment-gated because this workstation has no
  configured test database.
- Full repository Python baseline before the final presentation-only repair:
  893 passed and 121 environment-gated skips; no direct database mutation was
  used.
- Full workspace frontend baseline before the final presentation-only repair:
  learner and admin suites, lint, typecheck, formatting, and builds passed.
- The real `/` route was captured at 1440 × 1024 and 390 × 844 after its
  anonymous staging catalog request returned the published Authority Closers
  Free Course. Both viewports returned 200, rendered exactly one H1 and one real
  catalog card, had document width equal to viewport width, and emitted zero
  headless Chromium console errors. Candidate captures are packaged as
  `docs/workflows/learner-product-v1/05-handoff-qa/public-entry-implementation-*.png`.
  Authenticated learner truth still requires staging without forwarding staging
  cookies through localhost.
- The dev proxy has no full-access staging mode: even an undeclared
  `AC_DEV_STAGING_FULL_ACCESS=true` value remains constrained to anonymous,
  allowlisted catalog GETs.
- Successful online `/v1/me` and `/v1/context` responses rotate the encrypted
  private cache scope across both person and tenant. Identity, email, tenant,
  role, permissions, and context are never persisted or supplied as an offline
  fallback; changing tenant clears the prior private scope.
- Ephemeral local captures are under `.artifacts/design-qa/current-candidate/`;
  `.artifacts` is excluded from Git. Selected source references and durable
  implementation captures are packaged in the learner-product workstream.
- The public hero presentation artwork at
  `apps/learner-web/public/media/dipak-learning-hero-v1.png` was generated with
  ImageGen from a portrait published on Dipak Vishwakarma's official website.
  It is presentation artwork only: it is not lesson media, identity evidence,
  progress evidence, or a substitute for an approved video asset. The source
  URL and generated-asset status are recorded in the workstream asset manifest.

## Release boundary

The exact candidate is now staging-deployed and bounded controller-smoked.
This slice contains no authenticated learner-route observation or visual proof.
Production remains blocked. Fresh enrollment, mutation, browser/device,
recovery, restore/rollback, and capability-specific gates remain open.
