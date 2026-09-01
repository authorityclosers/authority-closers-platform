---
id: SF-COURSE-001
type: screen-family
title: Exact Authority Closers Free Course Screens
status: runtime-pending
version: v0.1-alpha
updated: 2026-09-01
screen_ids:
  - COURSE-01
  - COURSE-02
tags:
  - ac/screen/course
  - ac/free-course
---

# Exact Authority Closers Free Course screens

Program title: `Authority Closers Free Course`. Stable slug: `authority-closers-free-course`.

| ID          | Route                  | Boundary                                                                                                      |
| ----------- | ---------------------- | ------------------------------------------------------------------------------------------------------------- |
| `COURSE-01` | `/programs/{slug}`     | public published detail, processing start action, eligibility/consent lock; current candidate runtime pending |
| `COURSE-02` | `/learn/{programSlug}` | enrolled learner path, projection, module locks and reasons; specification ready                              |

The public screen never substitutes the retained two-module fixture. `Start free course` is explicit and idempotent; the server resolves person, tenant, learner membership, current consent, exact published program, eligibility fact, and enrollment.

- controlled-by: [[SRC-010-implementation-controls]] and [[SRC-040-engineering-contracts]].
- appears-in: [[JRN-01-account-to-first-value]] and [[JRN-03-module-1-learning-loop]].
- route: [[RT-003-learning]].
- calls: [[API-002-catalog-enrollment]] and [[API-003-learning-evidence]].
- exact content: [versioned seed](../../../packages/python/ac_platform/seed/data/free_course_foundation_v1.json).
- constraint: [[DEC-001-public-learner-tenancy-consent]].
