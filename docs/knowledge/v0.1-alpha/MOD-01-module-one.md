---
id: MOD-01
type: screen-family
title: Free Course Module 1
status: specification-ready
version: v0.1-alpha
updated: 2026-09-01
tags:
  - ac/screen/module
  - ac/free-course
---

# MOD-01 — Free Course Module 1

Route: `/learn/{programSlug}/module/{moduleId}`. Exact title: `SHIFT 1 — Why High-Ticket Sales Is A Completely Different Game.`

The screen renders ordered activities and prerequisite explanations from the learning projection. Required order is [[ACT-01-watch|Watch]] → [[ACT-02-reflection|Reflect]] → [[SF-EVIDENCE-001-implement-review-improve|Implement → Review → Improve]]. Locked content explains the prerequisite without revealing unauthorized payloads. Completion and unlock are server decisions.

Modules 2–4 contain titles and sequential prerequisite topology only in the current seed; no activities or completion semantics may be invented for them.

- appears-in: [[JRN-03-module-1-learning-loop]].
- route: [[RT-003-learning]].
- calls: [[API-003-learning-evidence]].
- implementation: [module route](../../../apps/learner-web/app/learn/[programSlug]/module/[moduleId]/page.tsx) and [course path](../../../apps/learner-web/app/components/course-path.tsx).
- exact seed: [Free Course foundation v1](../../../packages/python/ac_platform/seed/data/free_course_foundation_v1.json).
