---
id: VJB-JRN-02-M
type: visual-board
title: JRN-02 Mobile Storyboard
status: scoped-evidence-complete
version: v0.1-alpha
updated: 2026-09-01
journey_id: JRN-02
viewport: mobile
slot_ids:
  [
    VJS-J02-M-01,
    VJS-J02-M-02,
    VJS-J02-M-03,
    VJS-J02-M-04,
    VJS-J02-M-05,
    VJS-J02-M-06,
  ]
tags:
  - ac/visual-board/mobile
---

# JRN-02 mobile storyboard

Parent: [[JRN-02-identity-recovery]]. MOC: [[VJB-MOC-001-visual-journey-boards]].

| #   | Slot           | Expected route/state                           | Source reference                           | Candidate/live evidence                                                                                              |
| --- | -------------- | ---------------------------------------------- | ------------------------------------------ | -------------------------------------------------------------------------------------------------------------------- |
| 1   | `VJS-J02-M-01` | `/login` `ready`                               | `AUTH-01`; [[SF-AUTH-001-authentication]]  | [81635d1 login](../../evidence/screenshots/v0.1-staging-exact-81635d1/login-mobile-390x844.jpg)                      |
| 2   | `VJS-J02-M-02` | `/forgot-password` neutral `success`           | `AUTH-04`; [[API-001-identity-onboarding]] | [81635d1 recovery](../../evidence/screenshots/v0.1-staging-exact-81635d1/forgot-password-mobile-390x844.jpg)         |
| 3   | `VJS-J02-M-03` | `/reset-password` empty-token `terminal_error` | `AUTH-05`                                  | [81635d1 reset](../../evidence/screenshots/v0.1-staging-exact-81635d1/reset-password-empty-mobile-390x844.jpg)       |
| 4   | `VJS-J02-M-04` | `/verify-email` empty-token `terminal_error`   | `AUTH-02`                                  | [81635d1 verify](../../evidence/screenshots/v0.1-staging-exact-81635d1/verify-email-mobile-390x844.jpg)              |
| 5   | `VJS-J02-M-05` | callback `consent_required` locked recovery    | `AUTH-06`; [[DEC-002-host-only-sessions]]  | [81635d1 callback](../../evidence/screenshots/v0.1-staging-exact-81635d1/google-consent-recovery-mobile-390x844.jpg) |
| 6   | `VJS-J02-M-06` | `/session-expired` recovery                    | `AUTH-07`                                  | [local session expiry](../../evidence/screenshots/v0.1-drive-aligned/12-session-expired-mobile.png) — local preview  |

## Existing embeds

![[../../evidence/screenshots/v0.1-staging-exact-81635d1/login-mobile-390x844.jpg]]
![[../../evidence/screenshots/v0.1-staging-exact-81635d1/forgot-password-mobile-390x844.jpg]]
![[../../evidence/screenshots/v0.1-staging-exact-81635d1/reset-password-empty-mobile-390x844.jpg]]
![[../../evidence/screenshots/v0.1-staging-exact-81635d1/verify-email-mobile-390x844.jpg]]
![[../../evidence/screenshots/v0.1-staging-exact-81635d1/google-consent-recovery-mobile-390x844.jpg]]
![[../../evidence/screenshots/v0.1-drive-aligned/12-session-expired-mobile.png]]
