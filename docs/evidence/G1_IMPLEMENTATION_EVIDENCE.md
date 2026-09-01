# G1 implementation evidence

Branch: `codex/g1-free-course-foundation`

Historical checkpoint: this page records the earlier walking-skeleton review.
Current route/runtime status is maintained in
[`PLATFORM_SURFACE_STATUS.md`](../traceability/PLATFORM_SURFACE_STATUS.md), and
the current release handoff is
[`V0_1_ALPHA_HANDOFF.md`](V0_1_ALPHA_HANDOFF.md). Do not use the immutable
release ID or focused-test counts below as the latest release identity.

## Permanent primitive

Production-shaped Free Course walking skeleton: identity -> explicit free enrollment -> protected activity -> evidence/progress -> completion -> course-completion certificate -> narrow admin diagnosis.

## Current evidence

| Work                                 | Evidence                                                                                                                                                                                                                | Status                                  |
| ------------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------- |
| Reproducible workspace               | Node/pnpm and Python/uv lockfiles; digest-pinned local Compose                                                                                                                                                          | PASS                                    |
| Learner/admin shell                  | 27 learner and 30 admin checks; independent Next.js production builds; fail-closed admin context                                                                                                                        | PASS (API action wiring remains)        |
| API kernel                           | live/ready split, sanitized request ID, release identity, RFC 7807 domain errors, complete OpenAPI generation                                                                                                           | PASS                                    |
| Authorization kernel                 | self, selected tenant, named permission allow/deny tests                                                                                                                                                                | PASS                                    |
| Event boundary                       | domain/audit/analytics/operational/cost categories; tenant-bound audit invariant                                                                                                                                        | PASS                                    |
| Identity/OAuth                       | durable pre-redirect transaction, PKCE/nonce/state, host-only same-surface cookies, and staging/production surface-host denial tests; domain/PostgreSQL evidence                                                        | INDEPENDENT REVIEW                      |
| Learner Google registration          | consent-gated browser start, signed consent-version binding, verified-provider persistence, public learner provisioning, allowlisted same-origin callback recovery, and focused unit/API/PostgreSQL/browser regressions | LOCAL VERIFIED; UPDATED STAGING PENDING |
| Public course + free enrollment HTTP | published-global-only query; server-owned actor/tenant; CSRF and idempotency gates; fresh PostgreSQL journey                                                                                                            | PASS (1 PostgreSQL E2E)                 |
| Catalog/enrollment/certificates      | independent review found actor-trust and direct-SQL integrity gaps                                                                                                                                                      | REMEDIATION                             |
| Learning                             | 31 focused checks, fresh PostgreSQL 18 suite, eight repeated concurrency runs, independent rereview                                                                                                                     | PASS (domain)                           |
| Operations                           | independent review found an audit-head GUC bypass and Alembic registry drift                                                                                                                                            | REMEDIATION                             |
| Edge/application release             | same-origin `/v1` routing, pinned Caddy validation, immutable release `d8980d839a8f30e9ccde83ccdb380dd440b1fb1b`, and public staging learner/API/Admin Access smoke                                                     | PASS (staging)                          |
| Security/accessibility/recovery/load | not yet executed against integrated slice                                                                                                                                                                               | PENDING                                 |

No production application mutation has occurred. These rows are component and
integration evidence, not a G1 release declaration.

## Deferred scope

Paid commerce, community, voice, WhatsApp, native stores, autonomous official scoring, broad B2B UI, white-label UI, Kafka, Redis, Kubernetes, and a second canonical database remain disabled.
