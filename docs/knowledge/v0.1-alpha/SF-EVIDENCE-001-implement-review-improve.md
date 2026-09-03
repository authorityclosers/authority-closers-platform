---
id: SF-EVIDENCE-001
type: screen-family
title: Implement, Review, and Improve Evidence Activities
status: implementation-candidate
version: v0.1-alpha
updated: 2026-09-01
screen_ids:
  - ACT-03
  - ACT-04
  - ACT-05
tags:
  - ac/screen/activity
  - ac/screen/evidence
---

# Implement, Review, and Improve evidence activities

All three use `/activity/{activityId}` and the common activity lifecycle.

| ID       | Kind                       | Evidence boundary                                                                                  |
| -------- | -------------------------- | -------------------------------------------------------------------------------------------------- |
| `ACT-03` | `IMPLEMENTATION_CHALLENGE` | records the learner's supported evidence/reflection; does not prove the real-world action occurred |
| `ACT-04` | `REVIEW`                   | captures an observed pattern; no fabricated human reviewer or AI result                            |
| `ACT-05` | `IMPROVE`                  | records one explicit correction or next action; no score or readiness claim                        |

Submission is server-authorized, append-safe, revision-checked, and idempotent. Progress changes only from canonical evidence/completion policy.

- appears-in: [[JRN-03-module-1-learning-loop]].
- calls: [[API-003-learning-evidence]].
- implementation: [activity renderers](../../../apps/learner-web/app/components/activity-renderers.tsx) and [learning HTTP](../../../packages/python/ac_platform/http/learning.py).
- constrained-by: [[DEC-003-canonical-progress-evidence]].
- evidence: historical route captures in [[EVD-001-staging-27fafae]] predate current mutation wiring; current runtime proof is open.
