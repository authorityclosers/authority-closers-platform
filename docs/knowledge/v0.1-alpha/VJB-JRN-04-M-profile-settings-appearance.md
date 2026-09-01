---
id: VJB-JRN-04-M
type: visual-board
title: JRN-04 Mobile Storyboard
status: pending-capture
version: v0.1-alpha
updated: 2026-09-01
journey_id: JRN-04
viewport: mobile
slot_ids:
  [
    VJS-J04-M-01,
    VJS-J04-M-02,
    VJS-J04-M-03,
    VJS-J04-M-04,
    VJS-J04-M-05,
    VJS-J04-M-06,
  ]
tags:
  - ac/visual-board/mobile
---

# JRN-04 mobile storyboard

Parent: [[JRN-04-profile-settings-appearance]]. MOC: [[VJB-MOC-001-visual-journey-boards]].

| #   | Slot           | Expected route/state                                | Source reference                                              | Candidate/live evidence                                                                                                                  |
| --- | -------------- | --------------------------------------------------- | ------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------- |
| 1   | `VJS-J04-M-01` | `/settings` profile/session facts `ready`           | [[SF-SET-001-settings]], [[VAR-RESP-001-responsive]]          | **PENDING — matching mobile settings capture not found**                                                                                 |
| 2   | `VJS-J04-M-02` | `/settings` appearance `light` selected             | [[VAR-THEME-001-theme]]                                       | **PENDING — matching mobile light-theme settings capture not found**                                                                     |
| 3   | `VJS-J04-M-03` | `/settings` appearance `dark` selected              | [[VAR-THEME-001-theme]], [[DEC-004-device-local-theme]]       | **PENDING — matching mobile dark-theme settings capture not found**                                                                      |
| 4   | `VJS-J04-M-04` | `/onboarding` profile editor `ready`                | [[ONB-01-onboarding]]                                         | [local onboarding](../../evidence/screenshots/v0.1-local/28-onboarding-mobile.png) — local preview only                                  |
| 5   | `VJS-J04-M-05` | `/privacy` `ready`                                  | [[RT-001-public-auth]]                                        | **PENDING — matching mobile privacy capture not found**                                                                                  |
| 6   | `VJS-J04-M-06` | intended route → `/session-expired` after auth loss | [[API-004-session-settings]], [[SF-SYS-001-universal-states]] | [drive-aligned session expiry](../../evidence/screenshots/v0.1-drive-aligned/12-session-expired-mobile.png) — local design evidence only |

## Existing embeds

### `VJS-J04-M-04`

![[../../evidence/screenshots/v0.1-local/28-onboarding-mobile.png]]

### `VJS-J04-M-06`

![[../../evidence/screenshots/v0.1-drive-aligned/12-session-expired-mobile.png]]
