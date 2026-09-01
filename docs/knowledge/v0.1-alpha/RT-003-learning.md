---
id: RT-003
type: route-family
title: Free Course Learning Routes
status: specification-ready
version: v0.1-alpha
updated: 2026-09-01
tags:
  - ac/route/learning
  - ac/free-course
---

# Free Course learning routes

| Browser route                            | Screen       | Canonical checks                                                                  |
| ---------------------------------------- | ------------ | --------------------------------------------------------------------------------- |
| `/home`                                  | `HOME-01`    | authenticated person, exact public learner context, consent, start/continue state |
| `/learn/{programSlug}`                   | `COURSE-02`  | enrollment, pinned version, tenant/resource ownership                             |
| `/learn/{programSlug}/module/{moduleId}` | `MOD-01`     | same plus module prerequisite state                                               |
| `/activity/{activityId}`                 | `ACT-01..05` | enrollment, entitlement, activity prerequisite, allowed action, revision          |

Human-facing routes use slugs or stable opaque IDs. Possession of a route or identifier never grants access. Locked payloads follow the authorization policy and do not reveal protected content.

`/programs/{slug}` remains a read-only public preview under
[[RT-001-public-auth]]. Enrollment begins only from authenticated `/home` under
[[DEC-006-authenticated-in-app-free-course-enrollment]].

- renders: [[SF-COURSE-001-free-course]], [[MOD-01-module-one]], [[ACT-01-watch]], [[ACT-02-reflection]], [[SF-EVIDENCE-001-implement-review-improve]].
- appears-in: [[JRN-03-module-1-learning-loop]].
- calls: [[API-002-catalog-enrollment]] and [[API-003-learning-evidence]].
- implementation: [program learning page](../../../apps/learner-web/app/learn/[programSlug]/page.tsx), [module page](../../../apps/learner-web/app/learn/[programSlug]/module/[moduleId]/page.tsx), and [activity page](../../../apps/learner-web/app/activity/[activityId]/page.tsx).
- supersedes: prior same-file wording that treated the public program preview as
  the Free Course start surface.
