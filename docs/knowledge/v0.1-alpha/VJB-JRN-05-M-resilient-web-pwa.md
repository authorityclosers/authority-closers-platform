---
id: VJB-JRN-05-M
type: visual-board
title: JRN-05 Mobile Storyboard
status: partial
version: v0.1-alpha
updated: 2026-09-01
journey_id: JRN-05
viewport: mobile
slot_ids:
  [
    VJS-J05-M-01,
    VJS-J05-M-02,
    VJS-J05-M-03,
    VJS-J05-M-04,
    VJS-J05-M-05,
    VJS-J05-M-06,
    VJS-J05-M-07,
    VJS-J05-M-08,
  ]
tags:
  - ac/visual-board/mobile
---

# JRN-05 mobile storyboard

Parent: [[JRN-05-resilient-web-pwa]]. MOC: [[VJB-MOC-001-visual-journey-boards]].

| #   | Slot           | Expected route/state                                   | Source reference                    | Candidate/live evidence                                                                                                                  |
| --- | -------------- | ------------------------------------------------------ | ----------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------- |
| 1   | `VJS-J05-M-01` | current route `loading`, structure preserved           | [[SF-SYS-001-universal-states]]     | **PENDING — matching mobile loading capture not found**                                                                                  |
| 2   | `VJS-J05-M-02` | current route `retryable-error` with recovery          | [[SF-SYS-001-universal-states]]     | **PENDING — matching mobile retryable-error capture not found**                                                                          |
| 3   | `VJS-J05-M-03` | `/offline` or current route `offline/stale`            | [[RT-004-progress-settings-system]] | [local offline](../../evidence/screenshots/v0.1-local/29-offline-mobile.png) — local preview only                                        |
| 4   | `VJS-J05-M-04` | current route `locked` with reason/recovery            | [[SF-SYS-001-universal-states]]     | [local locked](../../evidence/screenshots/v0.1-local/30-locked-mobile.png) — local preview only                                          |
| 5   | `VJS-J05-M-05` | intended route → `/session-expired`                    | [[API-004-session-settings]]        | [drive-aligned session expiry](../../evidence/screenshots/v0.1-drive-aligned/12-session-expired-mobile.png) — local design evidence only |
| 6   | `VJS-J05-M-06` | installed Edge PWA, safe-area and keyboard handling    | [[VAR-RESP-001-responsive]]         | **PENDING — installed mobile Edge PWA capture not found**                                                                                |
| 7   | `VJS-J05-M-07` | iOS Safari/Home Screen, safe recovery                  | [[VAR-RESP-001-responsive]]         | **PENDING — iOS Safari/Home Screen capture not found**                                                                                   |
| 8   | `VJS-J05-M-08` | same state in Light/Dark/System without semantic drift | [[VAR-THEME-001-theme]]             | **PENDING — matching mobile theme-parity captures not found**                                                                            |

## Existing embeds

### `VJS-J05-M-03`

![[../../evidence/screenshots/v0.1-local/29-offline-mobile.png]]

### `VJS-J05-M-04`

![[../../evidence/screenshots/v0.1-local/30-locked-mobile.png]]

### `VJS-J05-M-05`

![[../../evidence/screenshots/v0.1-drive-aligned/12-session-expired-mobile.png]]
