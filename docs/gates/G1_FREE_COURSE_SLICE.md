# G1 — Free Course end-to-end readiness

The controlled documents reference G0/G1/G2 but do not formally define G1. This repository defines G1 as the production-shaped Free Course walking-skeleton gate. This definition must be reconciled back into the controlled document set before G1 is declared passed.

## Journey under test

`identity -> free enrollment -> protected activity -> evidence/progress -> course completion -> certificate -> admin diagnosis`

The course uses the permanent hierarchy `Program -> Module -> Activity` and the activity kinds `VIDEO`, `REFLECTION`, `IMPLEMENTATION_CHALLENGE`, `REVIEW`, and `IMPROVE`.

## Exit criteria

- Named learner identity, verified email, secure session lifecycle, revocation, and deletion-request path.
- Explicit free enrollment and entitlement; no analytics, ERP, provider callback, or UI state grants access.
- Versioned, immutable published content and an explicit learner-version policy.
- Sequential module prerequisites with server-authoritative progress and configurable video evidence threshold.
- Durable draft/save/resume across refresh, reconnect, expiry, and another device.
- Deterministic First Win guidance and human-authored review behavior; no autonomous official AI judgment.
- Course-completion certificate clearly separated from competency certification.
- Idempotent launch/transactional email, durable outbox/jobs, retries, and replay evidence.
- Mobile-first PWA and WCAG 2.2 AA acceptance for all critical journeys.
- Narrow admin workflows for publish, learner diagnosis, append-only correction, manual grant with reason, and audit.
- Tenant-negative, authorization, progression-invariant, abuse, retry, crash/replay, backup/restore, and accessibility tests.
- Critical telemetry trace from registration through completion plus operational queue/provider signals.
- Measured G1 RPO/RTO; restored jobs are held and reconciled before external side effects.
- Internal-team release evidence is complete before a controlled 20–50-user cohort.

## Explicit non-goals

Paid commerce, community, voice simulation, live-call AI, official autonomous scoring, native stores, WhatsApp, advanced analytics, broad B2B UI, and white-label UI are not G1 exit criteria.
