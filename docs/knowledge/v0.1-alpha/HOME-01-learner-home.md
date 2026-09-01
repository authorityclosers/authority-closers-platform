---
id: HOME-01
type: screen-family
title: Learner Home
status: mixed-evidence
version: v0.1-alpha
updated: 2026-09-01
tags:
  - ac/screen/home
---

# HOME-01 — Learner home

Route: `/home`. Actor: learner. The screen reads `/v1/me`, selected context, published catalog, enrollment, and learning projection. It must distinguish loading, no enrollment, authorized ready, retryable API failure, offline/stale, and expired session. Missing data is not rendered as zero progress.

Primary next action is based on canonical enrollment/progression, not analytics. Home presents one dominant start, resume or continue action and does not repeat the same Free Course as competing cards. An eligible learner may use the explicit consent-backed in-app `Start free course` action; the UI itself grants no access.

- controlled-by: [[SRC-020-product-experience]], [[SRC-021-evidence-based-learner-experience]], and [[SRC-040-engineering-contracts]].
- enrollment-decision: [[DEC-006-authenticated-in-app-free-course-enrollment]].
- appears-in: [[JRN-01-account-to-first-value]] and [[JRN-03-module-1-learning-loop]].
- route: [[RT-002-onboarding-home]].
- calls: [[API-002-catalog-enrollment]], [[API-003-learning-evidence]], [[API-004-session-settings]].
- implementation: [home page](../../../apps/learner-web/app/home/page.tsx) and [learner runtime](../../../apps/learner-web/app/components/learner-runtime.tsx).
- evidence: [[EVD-001-staging-27fafae]] proves the older exact release; current candidate changes still require [[GATE-003-exact-release-staging]].
