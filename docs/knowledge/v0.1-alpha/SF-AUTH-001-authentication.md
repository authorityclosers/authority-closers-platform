---
id: SF-AUTH-001
type: screen-family
title: Authentication Screen Family
status: specification-ready
version: v0.1-alpha
updated: 2026-09-01
screen_ids:
  - AUTH-01
  - AUTH-02
  - AUTH-03
  - AUTH-04
  - AUTH-05
  - AUTH-06
  - AUTH-07
tags:
  - ac/screen/auth
---

# Authentication screen family

| ID        | Route              | Meaningful states                                                                         |
| --------- | ------------------ | ----------------------------------------------------------------------------------------- |
| `AUTH-01` | `/login`           | ready, processing, validation error, verification locked, retryable provider error        |
| `AUTH-02` | `/register`        | ready, missing/invalid consent, processing existence-neutral acknowledgement              |
| `AUTH-03` | `/verify-email`    | token processing, success/session, resend success, terminal invalid/expired link          |
| `AUTH-04` | `/forgot-password` | ready and existence-neutral accepted response                                             |
| `AUTH-05` | `/reset-password`  | ready, success with session revocation, invalid/expired token                             |
| `AUTH-06` | `/auth/callback`   | bounded consent/registration recovery and provider failure; hostile callback fails closed |
| `AUTH-07` | `/session-expired` | reauthentication plus safe-draft/return-intent reassurance                                |

Inputs require labels, accessible error association, password-manager/paste support, preservation where safe, and no account enumeration. Consent is explicit and exact-version-bound; marketing consent is not inferred.

- controlled-by: [[SRC-030-state-interface-assurance]] and [[SRC-050-trust-operations]].
- appears-in: [[JRN-01-account-to-first-value]] and [[JRN-02-identity-recovery]].
- routes-to: [[RT-001-public-auth]].
- calls: [[API-001-identity-onboarding]] and [[API-004-session-settings]].
- implementation: [auth pages](../../../apps/learner-web/app/login/page.tsx), [login form](../../../apps/learner-web/app/components/login-form.tsx), and [password forms](../../../apps/learner-web/app/components/password-auth-forms.tsx).
- evidence: [[EVD-002-auth-81635d1]] and [[EVD-003-current-candidate-design-qa]] with their stated boundaries.
