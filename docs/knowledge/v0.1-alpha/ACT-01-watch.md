---
id: ACT-01
type: screen-family
title: Watch Activity
status: gap-blocked
version: v0.1-alpha
updated: 2026-09-01
tags:
  - ac/screen/activity
  - ac/gap/media
---

# ACT-01 — Watch activity

Route: `/activity/{activityId}`. Applicable states: ready, processing, retryable provider error, and completion success. The intended completion rule is versioned/configurable server-authoritative unique instructional coverage; the initial operating default is 90%, not mastery.

Current limitation `GAP-MEDIA-001`: no approved media/transcript/caption source and no composed playback-policy resolver prove real video or watched-interval evidence. The existing screen must show an honest provider gate and cannot mark completion from page open or player position.

- appears-in: [[JRN-03-module-1-learning-loop]].
- route: [[RT-003-learning]].
- calls: [[API-003-learning-evidence]].
- implementation: [activity route](../../../apps/learner-web/app/activity/[activityId]/page.tsx) and [activity renderers](../../../apps/learner-web/app/components/activity-renderers.tsx).
- constrained-by: [[DEC-003-canonical-progress-evidence]] and [[DEC-005-capability-gates]].
- known-limitation: [[LIM-001-known-limitations]].
