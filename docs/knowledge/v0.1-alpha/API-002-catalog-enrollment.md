---
id: API-002
type: api-contract
title: Public Catalog and Free Enrollment API Contract
status: runtime-pending
version: v0.1-alpha
updated: 2026-09-01
tags:
  - ac/api/catalog
  - ac/api/enrollment
---

# Public catalog and free enrollment API contract

| Method and path             | Caller                              | Canonical effect                                                                                       |
| --------------------------- | ----------------------------------- | ------------------------------------------------------------------------------------------------------ |
| `GET /v1/programs`          | anonymous                           | bounded published-global catalog only                                                                  |
| `GET /v1/programs/{slug}`   | anonymous/member                    | published detail; no draft/protected payload                                                           |
| `POST /v1/enrollments/free` | authenticated eligible learner self | explicit action creates/reuses consent-backed eligibility and idempotent enrollment in one transaction |

Free enrollment is limited to `authority-closers-free-course` and policy `AC-FREE-SELF-ATTESTATION-v1`. The client selects only the program version; server context selects person and tenant. Existing positive facts are reused; negative, expired, conflicting, wrong-course, stale-consent, inactive, unverified, or wrong-role inputs fail closed and are not overwritten.

- controlled-by: [[DEC-001-public-learner-tenancy-consent]].
- called-by: [[HOME-01-learner-home]] and [[SF-COURSE-001-free-course]].
- implements: [course HTTP](../../../packages/python/ac_platform/http/course.py), [self-attestation](../../../packages/python/ac_platform/enrollment/self_attestation.py), and [learner API client](../../../apps/learner-web/app/lib/learner-api.ts).
- validated-by: [[IMP-004-tests]]; exact-current runtime remains [[GATE-003-exact-release-staging]].
