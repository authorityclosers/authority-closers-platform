---
id: SRC-060
type: source
title: Controlled and Repository Decision Records
status: mixed-authority
version: v0.1-alpha
updated: 2026-09-01
controls:
  - "[[DEC-001-public-learner-tenancy-consent]]"
  - "[[DEC-005-capability-gates]]"
tags:
  - ac/source/decisions
---

# Controlled and repository decision records

The [controlled ADR, Risk, Assumption, Open Question & Change Log](https://docs.google.com/document/d/1cNE-8DB0iX28U5IR_StkO-JGE2TPG-pbKn6LQ-bZSaY/edit) (`1cNE-8DB0iX28U5IR_StkO-JGE2TPG-pbKn6LQ-bZSaY`) is the long-form decision authority.

Code-adjacent repository ADRs provide implementation evidence and must propagate business changes back to the controlled layer:

- [ADR-024: bounded benchmark quality](../../adr/0024-benchmark-quality-with-bounded-scope.md)
- [ADR-025: proposed G1 definition](../../adr/0025-formalize-g1-free-course-readiness.md)
- [ADR-026: infrastructure source migration](../../adr/0026-migrate-infrastructure-source-to-platform.md)
- [ADR-027: host-only same-origin sessions](../../adr/0027-use-host-only-same-origin-browser-sessions.md)
- [ADR-028: public learner tenancy and consent-backed free enrollment](../../adr/0028-separate-public-learner-context-and-consent-backed-free-enrollment.md)

- represented by: [[DEC-001-public-learner-tenancy-consent]], [[DEC-002-host-only-sessions]], [[DEC-003-canonical-progress-evidence]], [[DEC-004-device-local-theme]], [[DEC-005-capability-gates]].
- known limitation: ADR-025 remains proposed pending controlled reconciliation; see [[GATE-002-G1-free-course]].
