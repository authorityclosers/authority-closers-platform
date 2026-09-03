---
id: JRN-03
type: journey
title: Module 1 Learning Loop
status: implementation-candidate
version: v0.1-alpha
updated: 2026-09-01
controlled_by:
  - "[[SRC-010-implementation-controls]]"
  - "[[SRC-040-engineering-contracts]]"
tags:
  - ac/journey/learner
  - ac/free-course
---

# JRN-03 — Module 1 learning loop

Actor: enrolled learner. Goal: make durable, explainable progress through the exact Module 1 sequence.

| Stage          | Screen                                                                           | Canonical behavior                                                                                                               |
| -------------- | -------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------- |
| `STG-LEARN-01` | [[HOME-01-learner-home]] → [[SF-COURSE-001-free-course]] → [[MOD-01-module-one]] | read enrollment, pinned version, eligibility, projection, available/locked reasons                                               |
| `STG-LEARN-02` | [[ACT-01-watch]]                                                                 | video progress requires approved media plus server-authoritative unique watched-interval evidence; page open is never completion |
| `STG-LEARN-03` | [[ACT-02-reflection]]                                                            | draft is revision-safe, resumable, and explicit about saving/offline/conflict states                                             |
| `STG-LEARN-04` | [[SF-EVIDENCE-001-implement-review-improve]]                                     | record supported implementation evidence without claiming real-world verification                                                |
| `STG-LEARN-05` | same activity shell                                                              | review an observed pattern without fabricating coach or AI output                                                                |
| `STG-LEARN-06` | same activity shell                                                              | choose one explicit improvement/next action; completion remains server-authoritative                                             |

Exact course: `Authority Closers Free Course`, slug `authority-closers-free-course`. Exact Module 1: `SHIFT 1 — Why High-Ticket Sales Is A Completely Different Game.` Required order: `VIDEO → REFLECTION → IMPLEMENTATION_CHALLENGE → REVIEW → IMPROVE`.

Entry: authenticated, active learner membership plus canonical enrollment pinned to the published version. Exit: Module 1 completion evaluated and next state explained. Modules 2–4 are topology-only in the current seed.

- calls: [[API-002-catalog-enrollment]] and [[API-003-learning-evidence]].
- implements: [[IMP-001-learner-web]], [[IMP-002-platform-api-domain]], [[IMP-003-seed-bootstrap]].
- validated-by: [[GATE-002-G1-free-course]] and [[GATE-003-exact-release-staging]].
- evidenced-by: [[EVD-001-staging-27fafae]] for read/draft surfaces; current evidence mutation remains candidate-only.
- next: [[PROG-01-progress]] and [[JRN-04-profile-settings-appearance]].
