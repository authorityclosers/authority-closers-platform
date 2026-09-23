---
id: API-001
type: api-contract
title: Identity and Onboarding API Contract
status: implementation-candidate
version: v0.1-alpha
updated: 2026-09-23
tags:
  - ac/api/identity
---

# Identity and onboarding API contract

| Method and path                              | Caller                      | Canonical effect                                                                  |
| -------------------------------------------- | --------------------------- | --------------------------------------------------------------------------------- |
| `POST /v1/auth/password/register`            | anonymous, safe origin      | unverified person/credential/consent/challenge/outbox; existence-neutral response |
| `POST /v1/auth/password/resend-verification` | anonymous, safe origin      | supersede eligible outstanding links; neutral response                            |
| `POST /v1/auth/password/login`               | anonymous, safe origin      | verify credential/person and issue opaque host-only session                       |
| `POST /v1/auth/password/recovery`            | anonymous, safe origin      | enqueue eligible reset flow; neutral response                                     |
| `POST /v1/auth/password/verify`              | anonymous, safe origin      | consume token once, verify email, issue session                                   |
| `POST /v1/auth/password/reset`               | anonymous, safe origin      | consume token once, replace verifier, revoke active sessions                      |
| `GET /v1/auth/email-code/config`              | public, configured surface  | return current consent version, configured Google availability, and OTP policy    |
| `POST /v1/auth/email-code/request`            | anonymous, safe origin      | queue separate-purpose numeric email code with neutral acknowledgement           |
| `POST /v1/auth/email-code/verify`             | anonymous, safe origin      | consume code once, provision consented identity if new, issue host-only session    |
| `GET/PUT /v1/onboarding`                     | authenticated self          | read/save bounded profile with ETag/`If-Match` revision                           |
| `GET /v1/auth/google/start`                  | anonymous or link actor     | create signed, expiring, surface-bound OAuth transaction                          |
| `GET /v1/auth/google/callback`               | verified provider assertion | consume transaction atomically; link/login or bounded recovery                    |

- controlled-by: [[SRC-040-engineering-contracts]] and [[SRC-050-trust-operations]].
- called-by: [[SF-AUTH-001-authentication]] and [[ONB-01-onboarding]].
- Sales Xray email-code behavior is narrowed by [[API-001A-sales-xray-email-code-auth]].
- implements: [auth HTTP](../../../packages/python/ac_platform/http/auth.py), [onboarding domain](../../../packages/python/ac_platform/identity/onboarding.py), and [learner API client](../../../apps/learner-web/app/lib/learner-api.ts).
- validated-by: [[IMP-004-tests]] and [[GATE-003-exact-release-staging]].
