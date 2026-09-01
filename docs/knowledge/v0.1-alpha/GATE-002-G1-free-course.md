---
id: GATE-002
type: test-gate
title: G1 Free Course Readiness Gate
status: proposed-not-passed
version: v0.1-alpha
updated: 2026-09-01
tags:
  - ac/gate/G1
  - ac/free-course
---

# G1 Free Course readiness gate

Repository candidate definition: `identity → free enrollment → protected activity → evidence/progress → completion → certificate → admin diagnosis`, using the permanent Program → Module → Activity kernel.

The full exit requires identity/session/deletion baseline, explicit access, versioned content, progression and media evidence, durable drafts, deterministic First Win, retry-safe email/jobs, mobile/PWA and WCAG 2.2 AA journeys, narrow audited admin, authorization/tenant/recovery tests, telemetry trace, and measured restore/side-effect reconciliation.

Source: [G1_FREE_COURSE_SLICE.md](../../gates/G1_FREE_COURSE_SLICE.md). [ADR-025](../../adr/0025-formalize-g1-free-course-readiness.md) marks this definition proposed pending controlled-document reconciliation. Therefore G1 is not declared passed.

- covers: [[JRN-01-account-to-first-value]], [[JRN-02-identity-recovery]], [[JRN-03-module-1-learning-loop]], [[JRN-06-admin-operations]].
- constrained-by: [[DEC-005-capability-gates]].
- hands-off-to: [[GATE-003-exact-release-staging]].
