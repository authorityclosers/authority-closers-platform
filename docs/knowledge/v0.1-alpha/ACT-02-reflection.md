---
id: ACT-02
type: screen-family
title: Reflection and Draft Activity
status: specification-ready
version: v0.1-alpha
updated: 2026-09-01
tags:
  - ac/screen/activity
  - ac/screen/reflection
---

# ACT-02 — Reflection and draft activity

Route: `/activity/{activityId}`. Actor: enrolled learner. Purpose: record a reflection as first-class evidence with durable draft behavior.

Meaningful states: restored ready, dirty local input, saving, saved, retryable save failure, offline-unsaved, stale revision conflict, expired session, evidence processing, and completion success. Input remains recoverable where safe; the API uses `If-Match` revision and logical idempotency.

- appears-in: [[JRN-03-module-1-learning-loop]].
- route: [[RT-003-learning]].
- calls: [[API-003-learning-evidence]].
- implementation: [activity renderers](../../../apps/learner-web/app/components/activity-renderers.tsx), [local drafts](../../../apps/learner-web/app/lib/local-drafts.ts), and [learner API](../../../apps/learner-web/app/lib/learner-api.ts).
- validated-by: [[GATE-002-G1-free-course]] and [[GATE-003-exact-release-staging]].
- evidence boundary: [[EVD-001-staging-27fafae]] showed restored draft read state; current save/conflict/evidence mutation still needs exact-current proof.
