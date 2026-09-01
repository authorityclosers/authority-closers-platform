---
id: ONB-01
type: screen-family
title: Progressive Onboarding
status: specification-ready
version: v0.1-alpha
updated: 2026-09-01
tags:
  - ac/screen/onboarding
---

# ONB-01 — Progressive onboarding

Route: `/onboarding`. Actor: verified learner. Bounded fields: experience context, learning goal, practice situation, weekly minutes, status, current step, and revision.

Applicable states: loading; new/restored ready; processing; retryable save failure; revision conflict; offline/stale; completed or skipped success. Reauthentication must return to the exact step with safe work preserved. Recommendation failure must not block neutral course access.

- controlled-by: [[SRC-020-product-experience]] and [[SRC-030-state-interface-assurance]].
- appears-in: [[JRN-01-account-to-first-value]].
- route: [[RT-002-onboarding-home]].
- calls: [[API-001-identity-onboarding]].
- implementation: [onboarding page](../../../apps/learner-web/app/onboarding/page.tsx) and [form](../../../apps/learner-web/app/components/onboarding-form.tsx).
- constraint: onboarding does not infer role, access, score, persona, or course enrollment.
