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

| ID          | Route                  | Boundary                                                                             |
| ----------- | ---------------------- | ------------------------------------------------------------------------------------ |
| `COURSE-01` | `/programs/{slug}`     | read-only public preview; signs in or opens authenticated learner app; never enrolls |
| `COURSE-02` | `/learn/{programSlug}` | enrolled learner path, projection, module locks and reasons; specification ready     |

The public screen never substitutes the retained two-module fixture and never
mutates access. [[HOME-01-learner-home]] owns the explicit, idempotent
`Start free course` action. The server resolves person, exact configured public
learner tenant, current consent, exact published program, eligibility fact and
enrollment; the client supplies no person or tenant identifier.

- controlled-by: [[SRC-010-implementation-controls]] and [[SRC-040-engineering-contracts]].
- appears-in: [[JRN-01-account-to-first-value]] and [[JRN-03-module-1-learning-loop]].
- route: [[RT-003-learning]].
- calls: [[API-002-catalog-enrollment]] and [[API-003-learning-evidence]].
- exact content: [versioned seed](../../../packages/python/ac_platform/seed/data/free_course_foundation_v1.json).
- constraint: [[DEC-001-public-learner-tenancy-consent]].
- enrollment surface: [[DEC-006-authenticated-in-app-free-course-enrollment]].
- supersedes: prior same-file wording that assigned enrollment processing to
  `COURSE-01`.
