---
id: VJB-JRN-05-D
type: visual-board
title: JRN-05 Desktop Storyboard
status: partial
version: v0.1-alpha
updated: 2026-09-01
journey_id: JRN-05
viewport: desktop
slot_ids:
  [
    VJS-J05-D-01,
    VJS-J05-D-02,
    VJS-J05-D-03,
    VJS-J05-D-04,
    VJS-J05-D-05,
    VJS-J05-D-06,
    VJS-J05-D-07,
  ]
tags:
  - ac/visual-board/desktop
---

# JRN-05 desktop storyboard

Parent: [[JRN-05-resilient-web-pwa]]. MOC: [[VJB-MOC-001-visual-journey-boards]].

| #   | Slot           | Expected route/state                                   | Source reference                | Candidate/live evidence                                                                                                                      |
| --- | -------------- | ------------------------------------------------------ | ------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------- |
| 1   | `VJS-J05-D-01` | current route `loading`, structure preserved           | [[SF-SYS-001-universal-states]] | [drive-aligned loading](../../evidence/screenshots/v0.1-drive-aligned/06-universal-loading-desktop.png) — local design evidence only         |
| 2   | `VJS-J05-D-02` | current route `retryable-error` with recovery          | [[SF-SYS-001-universal-states]] | [local error](../../evidence/screenshots/v0.1-local/16-universal-error-desktop.png) — local preview only                                     |
| 3   | `VJS-J05-D-03` | `/home` `offline/stale` with blocked unsafe mutation   | [[SF-SYS-001-universal-states]] | [drive-aligned offline home](../../evidence/screenshots/v0.1-drive-aligned/05-learner-home-offline-desktop.png) — local design evidence only |
| 4   | `VJS-J05-D-04` | current route `locked` with reason/recovery            | [[SF-SYS-001-universal-states]] | [local locked](../../evidence/screenshots/v0.1-local/18-universal-locked-desktop.png) — local preview only                                   |
| 5   | `VJS-J05-D-05` | intended route → `/session-expired`                    | [[API-004-session-settings]]    | [drive-aligned session expiry](../../evidence/screenshots/v0.1-drive-aligned/03-session-expired-desktop.png) — local design evidence only    |
| 6   | `VJS-J05-D-06` | installed Edge PWA, dirty-work update blocked          | [[VAR-RESP-001-responsive]]     | **PENDING — installed Edge PWA capture not found**                                                                                           |
| 7   | `VJS-J05-D-07` | same state in Light/Dark/System without semantic drift | [[VAR-THEME-001-theme]]         | **PENDING — matching desktop theme-parity captures not found**                                                                               |

## Existing embeds

### `VJS-J05-D-01`

![[../../evidence/screenshots/v0.1-drive-aligned/06-universal-loading-desktop.png]]

### `VJS-J05-D-02`

![[../../evidence/screenshots/v0.1-local/16-universal-error-desktop.png]]

### `VJS-J05-D-03`

![[../../evidence/screenshots/v0.1-drive-aligned/05-learner-home-offline-desktop.png]]

### `VJS-J05-D-04`

![[../../evidence/screenshots/v0.1-local/18-universal-locked-desktop.png]]

### `VJS-J05-D-05`

![[../../evidence/screenshots/v0.1-drive-aligned/03-session-expired-desktop.png]]
