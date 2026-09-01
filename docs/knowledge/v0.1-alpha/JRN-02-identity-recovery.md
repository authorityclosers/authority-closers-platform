---
id: JRN-02
type: journey
title: Identity and Session Recovery
status: specification-ready
version: v0.1-alpha
updated: 2026-09-01
controlled_by:
  - "[[SRC-030-state-interface-assurance]]"
  - "[[SRC-050-trust-operations]]"
tags:
  - ac/journey/recovery
---

# JRN-02 — Identity and session recovery

Actor: person whose login, verification, password recovery, Google callback, or session cannot complete normally. Goal: regain a safe session or receive a terminal/support path without leaking identity or provider details.

| Stage        | Screen IDs           | Required recovery behavior                                                                                                               |
| ------------ | -------------------- | ---------------------------------------------------------------------------------------------------------------------------------------- |
| `STG-REC-01` | `AUTH-01`, `AUTH-03` | distinguish invalid credentials, verification required, expired link, and resend acknowledgement while remaining existence-neutral       |
| `STG-REC-02` | `AUTH-04`, `AUTH-05` | accept recovery request neutrally; consume reset token once; revoke active sessions after reset                                          |
| `STG-REC-03` | `AUTH-06`            | show bounded `consent_required`, `consent_update_required`, `registration_required`, provider-rejected, or provider-unavailable recovery |
| `STG-REC-04` | `AUTH-07`            | preserve return intent and safe drafts across reauthentication; recheck current authorization                                            |

Offline identity mutation is unsupported. Malformed, replayed, wrong-host, wrong-surface, or ambiguous callback state fails closed.

- renders: [[SF-AUTH-001-authentication]] and [[SF-SYS-001-universal-states]].
- calls: [[API-001-identity-onboarding]] and [[API-004-session-settings]].
- implements: [[IMP-001-learner-web]] and [[IMP-002-platform-api-domain]].
- evidenced-by: [[EVD-002-auth-81635d1]] for the named historical release only.
- known-limitation: final real-account re-consent completion and current-candidate exact-release recovery remain open; see [[LIM-001-known-limitations]].
