---
id: VJB-JRN-02-D
type: visual-board
title: JRN-02 Desktop Storyboard
status: scoped-evidence-complete
version: v0.1-alpha
updated: 2026-09-01
journey_id: JRN-02
viewport: desktop
slot_ids:
  [
    VJS-J02-D-01,
    VJS-J02-D-02,
    VJS-J02-D-03,
    VJS-J02-D-04,
    VJS-J02-D-05,
    VJS-J02-D-06,
  ]
tags:
  - ac/visual-board/desktop
---

# JRN-02 desktop storyboard

Parent: [[JRN-02-identity-recovery]]. MOC: [[VJB-MOC-001-visual-journey-boards]].

| #   | Slot           | Expected route/state                           | Source reference                           | Candidate/live evidence                                                                                                 |
| --- | -------------- | ---------------------------------------------- | ------------------------------------------ | ----------------------------------------------------------------------------------------------------------------------- |
| 1   | `VJS-J02-D-01` | `/login` `ready`                               | `AUTH-01`; [[SF-AUTH-001-authentication]]  | [81635d1 login](../../evidence/screenshots/v0.1-staging-exact-81635d1/login-desktop-1488x1058.jpg)                      |
| 2   | `VJS-J02-D-02` | `/forgot-password` neutral `success`           | `AUTH-04`; [[API-001-identity-onboarding]] | [81635d1 recovery](../../evidence/screenshots/v0.1-staging-exact-81635d1/forgot-password-desktop-1488x1058.jpg)         |
| 3   | `VJS-J02-D-03` | `/reset-password` empty-token `terminal_error` | `AUTH-05`; [[SF-AUTH-001-authentication]]  | [81635d1 reset](../../evidence/screenshots/v0.1-staging-exact-81635d1/reset-password-empty-desktop-1488x1058.jpg)       |
| 4   | `VJS-J02-D-04` | `/verify-email` empty-token `terminal_error`   | `AUTH-02`                                  | [81635d1 verify](../../evidence/screenshots/v0.1-staging-exact-81635d1/verify-email-desktop-1488x1058.jpg)              |
| 5   | `VJS-J02-D-05` | callback `consent_required` locked recovery    | `AUTH-06`; [[DEC-002-host-only-sessions]]  | [81635d1 callback](../../evidence/screenshots/v0.1-staging-exact-81635d1/google-consent-recovery-desktop-1488x1058.jpg) |
| 6   | `VJS-J02-D-06` | `/session-expired` recovery                    | `AUTH-07`; [[JRN-02-identity-recovery]]    | [local session expiry](../../evidence/screenshots/v0.1-drive-aligned/03-session-expired-desktop.png) — local preview    |

All `81635d1` images are historical exact-release evidence; final real-account re-consent remained open.

## Existing embeds

![[../../evidence/screenshots/v0.1-staging-exact-81635d1/login-desktop-1488x1058.jpg]]
![[../../evidence/screenshots/v0.1-staging-exact-81635d1/forgot-password-desktop-1488x1058.jpg]]
![[../../evidence/screenshots/v0.1-staging-exact-81635d1/reset-password-empty-desktop-1488x1058.jpg]]
![[../../evidence/screenshots/v0.1-staging-exact-81635d1/verify-email-desktop-1488x1058.jpg]]
![[../../evidence/screenshots/v0.1-staging-exact-81635d1/google-consent-recovery-desktop-1488x1058.jpg]]
![[../../evidence/screenshots/v0.1-drive-aligned/03-session-expired-desktop.png]]
