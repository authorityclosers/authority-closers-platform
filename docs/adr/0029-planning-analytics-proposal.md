# ADR-0029: Planning and descriptive analytics proposal boundary

- Status: Proposed; pending promotion into the controlled product/data/security sources
- Date: 2026-09-02
- Scope: learner planning, explicit next-action projections, and descriptive product analytics

## Decision

Ship only an integration seam for the existing authenticated learner application:

- `today`, `week`, and `month` are labels on explicitly authored plan items;
  no timezone calculation, due-date promise, workload recommendation, streak
  target, or automatic schedule is generated.
- Up-next is read only from an explicit server-owned projection. The API never
  selects the first incomplete activity.
- Canonical progress is read from the existing enrollment/activity progress
  tables. No analytics table can create, unlock, complete, or otherwise mutate
  progress, entitlement, payment, or access.
- Product analytics accepts only the allowlisted proposal events, requires an
  injected authoritative consent resolver and explicit retention policy, and
  stores no event when consent is denied or unavailable.
- Plan, next-action, and analytics records are tenant/person scoped through the
  existing membership foreign-key boundary and routes use the existing
  authenticated transaction dependency.

The learner Calendar route is informational when no explicit plan rows exist.
It does not infer dates from the current day or rewrite the existing dashboard
and learning surfaces.

## Required promotion gates

Before these proposal records become product authority, the controlled PRD,
IA, UX States, SRS, Data/Tenancy, API, Telemetry, Security, and privacy/
retention sources must decide plan ownership and authoring, period boundaries
and timezone behavior, next-action semantics, descriptive insight families,
consent scope and retention schedules, and cross-person access.

Until then, the API returns `not_configured` or `insufficient_signal` rather
than fabricated schedule or metric values. The analytics disclaimer remains
explicit in every descriptive projection.
