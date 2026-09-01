---
id: API-003
type: api-contract
title: Learning, Draft, and Evidence API Contract
status: mixed-evidence
version: v0.1-alpha
updated: 2026-09-01
tags:
  - ac/api/learning
---

# Learning, draft, and evidence API contract

| Method and path                             | Caller                    | Canonical boundary                                                        |
| ------------------------------------------- | ------------------------- | ------------------------------------------------------------------------- |
| `GET /v1/learning/{programId}`              | enrolled learner self     | pinned program version, modules, activity reasons and progress projection |
| `GET /v1/activities/{activityId}`           | enrolled learner self     | prerequisite, entitlement, payload and allowed actions                    |
| `PUT /v1/activities/{activityId}/draft`     | enrolled learner self     | revision-safe durable draft; safe origin and idempotency                  |
| `POST /v1/activities/{activityId}/evidence` | learner/assigned reviewer | append-safe evidence/submission under policy and activity revision        |
| `POST /v1/evidence/{submissionId}/review`   | assigned reviewer         | explicit review result with provenance                                    |
| playback start/heartbeat/finish             | enrolled learner          | conditional routes; absent until a reviewed policy resolver is composed   |
| `GET /v1/certificates/{certificateId}`      | certificate subject self  | immutable course-completion certificate read                              |

- controlled-by: [[SRC-040-engineering-contracts]] and [[DEC-003-canonical-progress-evidence]].
- called-by: [[JRN-03-module-1-learning-loop]] and [[PROG-01-progress]].
- implements: [learning HTTP](../../../packages/python/ac_platform/http/learning.py), [learning service](../../../packages/python/ac_platform/learning/services.py), and [certificate HTTP](../../../packages/python/ac_platform/http/certificates.py).
- evidence boundary: read/draft paths have historical evidence in [[EVD-001-staging-27fafae]]; current evidence mutation and playback remain open.
