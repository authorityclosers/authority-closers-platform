---
id: DEC-005
type: decision
title: Capability-Scoped Activation Gates
status: controlled
version: v0.1-alpha
updated: 2026-09-01
tags:
  - ac/decision/gates
---

# Capability-scoped activation gates

A P0 blocks the affected capability, not unrelated foundation work.

| Gate                   | Blocked activation                               | Effect on v0.1 Alpha graph                                 |
| ---------------------- | ------------------------------------------------ | ---------------------------------------------------------- |
| paid commerce          | public payment/refund/access exposure            | Free Course uses explicit free enrollment; no fake payment |
| official autonomous AI | learner-authoritative score/credential decisions | no official autonomous scoring nodes or claims             |
| real-call data         | recording/upload/transcription/external AI       | no real-call processing nodes or provider activation       |
| native stores          | public store submission/commerce                 | responsive web/PWA remains independently testable          |
| WhatsApp               | provider integration                             | email remains separate; no WhatsApp runtime claim          |
| scaled B2B             | manager/workforce/white-label exposure           | tenant semantics exist; broad UI remains deferred          |

- controlled-by: [[SRC-010-implementation-controls]].
- constrains: [[GATE-002-G1-free-course]], [[GATE-004-production-activation]], [[LIM-001-known-limitations]].
- protects: [[JRN-03-module-1-learning-loop]] from speculative scope.
