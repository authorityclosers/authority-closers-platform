---
id: GATE-001
type: test-gate
title: G0 Control Plane Gate
status: open
version: v0.1-alpha
updated: 2026-09-01
tags:
  - ac/gate/G0
---

# G0 control plane gate

G0 requires reproducible repositories/workspace, CI, environment and secret contracts, migrations/roles/tenant tests, API authorization inventory, outbox/jobs, observability, backup/restore, side-effect hold/reconciliation, and no production secrets available to agents.

Repository checklist: [G0_CONTROL_PLANE.md](../../gates/G0_CONTROL_PLANE.md). It contains both checked and open items; therefore this graph does not declare G0 complete.

- controlled-by: [[SRC-010-implementation-controls]] and [[SRC-050-trust-operations]].
- implemented-by: [[IMP-002-platform-api-domain]], [[IMP-003-seed-bootstrap]], [[IMP-004-tests]].
- hands-off-to: [[GATE-002-G1-free-course]].
- known-limitation: measured restore/RPO/RTO and several operational hardening items remain open in the repository checklist.
