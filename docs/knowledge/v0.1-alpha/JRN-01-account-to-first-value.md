---
id: JRN-01
type: journey
title: Account to First Value
status: specification-ready
version: v0.1-alpha
updated: 2026-09-01
controlled_by:
  - "[[SRC-010-implementation-controls]]"
  - "[[SRC-020-product-experience]]"
tags:
  - ac/journey/learner
---

# JRN-01 — Account to first value

Actor: anonymous or unverified person becoming an account-ready learner. Goal: reach the exact Free Course entry without inventing identity, consent, tenant, or access state.

| Stage         | Route/surface                          | User action                                                | System response and recovery                                                                                                        |
| ------------- | -------------------------------------- | ---------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------- |
| `STG-AUTH-01` | [[RT-001-public-auth]]                 | discover course; choose register or sign in                | published catalog only; loading/empty/retry stay honest                                                                             |
| `STG-AUTH-02` | `/register`                            | enter bounded fields and explicitly accept current consent | create or acknowledge account without revealing existence; preserve safe input on retry                                             |
| `STG-AUTH-03` | `/verify-email` or Google callback     | verify identity                                            | issue host-only session or show bounded recovery; no token/provider payload in UI                                                   |
| `STG-ONB-01`  | [[RT-002-onboarding-home]]             | complete, resume, or skip bounded profile                  | revision-safe save; conflict and session-expiry recovery preserve safe work                                                         |
| `STG-ENR-01`  | authenticated [[HOME-01-learner-home]] | explicitly choose `Start free course`                      | server selects the exact public learner context after consent-backed provisioning, then commits eligibility and enrollment together |

Entry: public course or auth route. Exit: verified session, onboarding completed/skipped, and either an enrolled course path or a precise unmet-precondition state.

- routes-to: [[SF-AUTH-001-authentication]], [[ONB-01-onboarding]], [[HOME-01-learner-home]], [[SF-COURSE-001-free-course]].
- calls: [[API-001-identity-onboarding]], [[API-002-catalog-enrollment]], [[API-004-session-settings]].
- constrained-by: [[DEC-001-public-learner-tenancy-consent]] and [[DEC-002-host-only-sessions]].
- measurement intent: registration and First Win telemetry is secondary; it cannot create account, consent, membership, eligibility, or enrollment state.
- next journey: [[JRN-03-module-1-learning-loop]].
- supersedes: prior same-file stage wording that placed `Start free course` on
  the public program detail.
