---
id: API-004
type: api-contract
title: Self, Context, Session, and Settings API Boundary
status: implementation-candidate
version: v0.1-alpha
updated: 2026-09-01
tags:
  - ac/api/session
  - ac/api/settings
---

# Self, context, session, and settings API boundary

| Method and path                        | Boundary                                               |
| -------------------------------------- | ------------------------------------------------------ |
| `GET /v1/me`                           | authenticated self facts only                          |
| `GET /v1/context`                      | selected person/session/tenant role and permissions    |
| `POST /v1/context`                     | active membership; server-resolved tenant; safe origin |
| `POST /v1/sessions/{sessionId}/revoke` | self-scoped session mutation                           |
| `POST /v1/auth/logout`                 | same-origin session termination                        |

There is no account-theme or account-appearance API. `/settings` reads self
facts, routes profile edits to `/v1/onboarding`, invokes logout, and stores
theme mode plus bounded appearance variants locally. That absence is
deliberate and prevents invented cross-device, account, tenant, or authority
synchronization.

- controlled-by: [[DEC-002-host-only-sessions]] and [[DEC-004-device-local-theme]].
- called-by: [[HOME-01-learner-home]] and [[SF-SET-001-settings]].
- implements: [auth HTTP](../../../packages/python/ac_platform/http/auth.py), [settings runtime](../../../apps/learner-web/app/components/settings-runtime.tsx), and [theme control](../../../apps/learner-web/app/components/theme-control.tsx).
