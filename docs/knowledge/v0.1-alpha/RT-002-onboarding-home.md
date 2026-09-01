---
id: RT-002
type: route-family
title: Onboarding and Learner Home Routes
status: implementation-candidate
version: v0.1-alpha
updated: 2026-09-01
tags:
  - ac/route/learner
---

# Onboarding and learner home routes

| Browser route | Screen    | Auth/data boundary                                                             |
| ------------- | --------- | ------------------------------------------------------------------------------ |
| `/onboarding` | `ONB-01`  | verified authenticated self; `/v1/onboarding`; revision precondition           |
| `/home`       | `HOME-01` | active session; `/v1/me`, context, catalog, enrollment and learning projection |

The two routes are independent: identity can exist while onboarding is incomplete, and a recommender/profile failure cannot fabricate or revoke course access. Home distinguishes no enrollment, unavailable projection, locked state, and expired session.

- renders: [[ONB-01-onboarding]] and [[HOME-01-learner-home]].
- appears-in: [[JRN-01-account-to-first-value]] and [[JRN-03-module-1-learning-loop]].
- calls: [[API-001-identity-onboarding]], [[API-002-catalog-enrollment]], [[API-003-learning-evidence]], [[API-004-session-settings]].
- implementation: [onboarding page](../../../apps/learner-web/app/onboarding/page.tsx) and [home page](../../../apps/learner-web/app/home/page.tsx).
