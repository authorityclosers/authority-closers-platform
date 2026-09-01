---
id: JRN-06
type: journey
title: Separate Admin Operations
status: foundation-only
version: v0.1-alpha
updated: 2026-09-01
controlled_by:
  - "[[SRC-050-trust-operations]]"
  - "[[SRC-060-decisions-risk]]"
tags:
  - ac/journey/admin
---

# JRN-06 — Separate admin operations

Actor: named AC operator on the separate admin surface. Goal: diagnose or invoke a specifically authorized command without direct SQL, learner-session reuse, or silent history rewrite.

Current stable screen IDs: `ADM-01` overview/auth boundary, `ADM-02` permission denial, `ADM-03` catalog, `ADM-04` learning operations, `ADM-05` correction, `ADM-06` grant.

Every mutation requires actor, selected tenant/context, named permission, purpose/reason, idempotency where applicable, and append-safe audit. Product admin and ERP remain separate; neither ERP nor analytics grants learner access or progress.

- calls: [[API-005-admin-operations]].
- implements: [[IMP-002-platform-api-domain]].
- constrained-by: [[DEC-003-canonical-progress-evidence]] and [[DEC-005-capability-gates]].
- validated-by: [[GATE-002-G1-free-course]] and [[GATE-003-exact-release-staging]].
- known-limitation: admin UI action wiring and privileged staging actions are not declared complete; see [[LIM-001-known-limitations]].
