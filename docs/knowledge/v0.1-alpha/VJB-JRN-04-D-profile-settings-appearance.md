---
id: VJB-JRN-04-D
type: visual-board
title: JRN-04 Desktop Storyboard
status: pending-capture
version: v0.1-alpha
updated: 2026-09-01
journey_id: JRN-04
viewport: desktop
slot_ids:
  [
    VJS-J04-D-01,
    VJS-J04-D-02,
    VJS-J04-D-03,
    VJS-J04-D-04,
    VJS-J04-D-05,
    VJS-J04-D-06,
  ]
tags:
  - ac/visual-board/desktop
---

# JRN-04 desktop storyboard

Parent: [[JRN-04-profile-settings-appearance]]. MOC: [[VJB-MOC-001-visual-journey-boards]].

| #   | Slot           | Expected route/state                                | Source reference                                              | Candidate/live evidence                                                                                                                   |
| --- | -------------- | --------------------------------------------------- | ------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------- |
| 1   | `VJS-J04-D-01` | `/settings` profile/session facts `ready`           | [[SF-SET-001-settings]]                                       | **PENDING — matching desktop settings capture not found**                                                                                 |
| 2   | `VJS-J04-D-02` | `/settings` appearance `light` selected             | [[VAR-THEME-001-theme]]                                       | **PENDING — matching desktop light-theme settings capture not found**                                                                     |
| 3   | `VJS-J04-D-03` | `/settings` appearance `dark` selected              | [[VAR-THEME-001-theme]], [[DEC-004-device-local-theme]]       | **PENDING — matching desktop dark-theme settings capture not found**                                                                      |
| 4   | `VJS-J04-D-04` | `/onboarding` existing profile editor `ready`       | [[ONB-01-onboarding]]                                         | **PENDING — matching ready desktop profile-editor capture not found**                                                                     |
| 5   | `VJS-J04-D-05` | `/privacy` `ready`                                  | [[RT-001-public-auth]]                                        | [local privacy](../../evidence/screenshots/v0.1-local/08-privacy-desktop.png) — local preview only                                        |
| 6   | `VJS-J04-D-06` | intended route → `/session-expired` after auth loss | [[API-004-session-settings]], [[SF-SYS-001-universal-states]] | [drive-aligned session expiry](../../evidence/screenshots/v0.1-drive-aligned/03-session-expired-desktop.png) — local design evidence only |

## Existing embeds

### `VJS-J04-D-05`

![[../../evidence/screenshots/v0.1-local/08-privacy-desktop.png]]

### `VJS-J04-D-06`

![[../../evidence/screenshots/v0.1-drive-aligned/03-session-expired-desktop.png]]
