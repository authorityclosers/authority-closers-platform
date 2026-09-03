---
id: PROG-01
type: screen-family
title: Learner Progress
status: runtime-pending
version: v0.1-alpha
updated: 2026-09-01
tags:
  - ac/screen/progress
---

# PROG-01 — Learner progress

Route: `/progress`. Actor: learner. States: loading, canonical ready, no-enrollment empty, retryable failure, and session expiry. It displays course percentage/counts, module activity states, and lock reasons from the canonical learning projection. Missing projection is not zero; analytics is not authority; completion is not mastery.

- appears-in: [[JRN-03-module-1-learning-loop]].
- route: [[RT-004-progress-settings-system]].
- calls: [[API-003-learning-evidence]].
- implementation: [progress page](../../../apps/learner-web/app/progress/page.tsx) and [progress runtime](../../../apps/learner-web/app/components/progress-runtime.tsx).
- decision: [[DEC-003-canonical-progress-evidence]].
- known-limitation: the implementation is included in exact release `5c7333c5`
  but still lacks route-specific staging, responsive, accessibility, and
  visual-comparison proof.
