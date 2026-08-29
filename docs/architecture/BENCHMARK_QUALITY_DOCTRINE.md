# Benchmark quality with bounded scope

## Decision

Dipak's approved first learning outcome and the controlled Authority Closers documents define the release boundary. They do not cap implementation quality.

The Free Course foundation will therefore be intentionally small in breadth and production-grade in depth. Duolingo, Unacademy, Udemy, and other mature learning products are quality references, not feature checklists and not designs to copy.

## What benchmark quality means here

| Dimension | Release expectation |
|---|---|
| Learning clarity | Every learner screen answers: where am I, what am I learning, what must I do, and what happens next? |
| First value | A learner reaches a meaningful First Win within approximately 15 minutes. |
| Progress truth | Completion is server-authoritative, explainable, version-aware, and resistant to duplicated heartbeats or seeking abuse. |
| Continuity | Drafts, position, evidence, and next action survive refresh, reconnect, session expiry, and device changes. |
| Feedback | Reflection and implementation steps provide timely, deterministic guidance without pretending that unverified AI output is authoritative. |
| Mobile quality | Critical journeys work at narrow widths, with touch-safe targets, captions, resilient resume, and installable PWA behavior. |
| Accessibility | Critical journeys meet WCAG 2.2 AA, including keyboard, focus, semantics, contrast, reduced motion, captions, and error recovery. |
| Performance | At the controlled cohort gate, p75 Core Web Vitals target LCP <= 2.5 s, INP <= 200 ms, and CLS <= 0.1 on supported mobile conditions. |
| Reliability | Mutations are idempotent where required, external side effects use durable jobs/outbox, and recovery is proven rather than asserted. |
| Operations | An authorized operator can publish, diagnose, correct by supersession, reconcile, and support a learner without direct database edits. |
| Observability | Every critical journey carries release, environment, actor-safe, request, and trace context without secrets or unnecessary personal data. |
| Security | Least privilege, named identities, tenant-negative tests, immutable audit evidence, secret references, and protected origin are release gates. |

## Scope boundary

The first slice implements only the reusable primitives needed for:

`WATCH -> REFLECT -> IMPLEMENT -> REVIEW -> IMPROVE`

It does not expose paid commerce, autonomous official AI scoring, live-call AI, native store releases, WhatsApp, community, scaled B2B, white-label UI, or voice simulation. Architectural seams for later capabilities may exist only when they simplify the permanent model and do not add an untested runtime system.

## Anti-patterns

- A visually polished shell over client-only or fabricated state.
- Gamification that rewards clicks instead of evidence-backed learning.
- A disposable course schema that cannot support later activity kinds.
- Premature microservices, Kafka, Kubernetes, or duplicated sources of truth.
- Hidden admin database edits or destructive correction of original evidence.
- Feature breadth used to excuse weak accessibility, recovery, testing, or telemetry.
- Claims such as "world class" or "100% secure" without measured evidence.

## Review rule

Every implementation slice must state:

1. the controlled requirement and learning outcome it serves;
2. the permanent primitive it exercises;
3. the benchmark-quality acceptance criteria;
4. the explicit deferred scope;
5. tests, telemetry, recovery impact, and vault evidence.
