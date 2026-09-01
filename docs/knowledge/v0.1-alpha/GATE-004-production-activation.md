---
id: GATE-004
type: test-gate
title: Production Activation Gate
status: no-go
version: v0.1-alpha
updated: 2026-09-01
tags:
  - ac/gate/production
---

# Production activation gate

Production is a separate approval and evidence decision after exact-release staging. It requires production DNS, secrets/bootstrap, database and tenant references, access controls, legal/privacy/provider review where applicable, observability, backup/restore, rollback, security/load/browser/device evidence, and action-time approval.

Current evidence explicitly reports production `NO-GO`; no production application mutation or hostname activation is claimed by this graph.

- controlled-by: [[SRC-050-trust-operations]] and [[DEC-005-capability-gates]].
- depends-on: [[GATE-001-G0-control-plane]], [[GATE-002-G1-free-course]], [[GATE-003-exact-release-staging]].
- constrained-by: [[LIM-001-known-limitations]].
- evidence source: [v0.1 Alpha handoff](../../evidence/V0_1_ALPHA_HANDOFF.md).
