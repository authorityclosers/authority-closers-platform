---
id: VJB-JRN-01-D
type: visual-board
title: JRN-01 Desktop Storyboard
status: partial
version: v0.1-alpha
updated: 2026-09-01
journey_id: JRN-01
viewport: desktop
slot_ids:
  [
    VJS-J01-D-01,
    VJS-J01-D-02,
    VJS-J01-D-03,
    VJS-J01-D-04,
    VJS-J01-D-05,
    VJS-J01-D-06,
  ]
tags:
  - ac/visual-board/desktop
---

# JRN-01 desktop storyboard

Parent: [[JRN-01-account-to-first-value]]. MOC: [[VJB-MOC-001-visual-journey-boards]].

| #   | Slot           | Expected route/state                    | Source reference                                                                        | Candidate/live evidence                                                                                                                   |
| --- | -------------- | --------------------------------------- | --------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------- |
| 1   | `VJS-J01-D-01` | `/` published catalog `ready`           | `COURSE-01`; [[SF-COURSE-001-free-course]]                                              | [27fafae catalog](../../evidence/screenshots/v0.1-staging-exact-27fafae/11-public-catalog.png) — historical exact release                 |
| 2   | `VJS-J01-D-02` | `/register` `ready`                     | [AUTH-01 Drive](https://drive.google.com/file/d/1K9qpP-OTsgyuhJ3mtmZYDj2-7EFv_MJb/view) | [81635d1 register](../../evidence/screenshots/v0.1-staging-exact-81635d1/register-desktop-1488x1058.jpg) — historical exact release       |
| 3   | `VJS-J01-D-03` | `/verify-email` `success`/session       | [AUTH-02 Drive](https://drive.google.com/file/d/1NLx4nRVxS_5bsu9hOMjEHW5Yb25GwNr5/view) | **PENDING — successful desktop verification not captured**                                                                                |
| 4   | `VJS-J01-D-04` | `/onboarding` `loading → ready`         | [ONB-01 Drive](https://drive.google.com/file/d/1-iZ5l-57RezRmFYyXcyY45jWiIFTF0um/view)  | [local loading](../../evidence/screenshots/v0.1-drive-aligned/04-onboarding-loading-desktop.png) — local preview                          |
| 5   | `VJS-J01-D-05` | `/home` authenticated `ready`           | `SHELL-01`; [[HOME-01-learner-home]]                                                    | [27fafae home](../../evidence/screenshots/v0.1-staging-exact-27fafae/01-learner-home-authorized.png) — historical exact release           |
| 6   | `VJS-J01-D-06` | exact course detail; start `processing` | [[DEC-001-public-learner-tenancy-consent]]                                              | [27fafae detail](../../evidence/screenshots/v0.1-staging-exact-27fafae/14-program-detail.png) — predates current consent-backed candidate |

## Existing embeds

### `VJS-J01-D-01`

![[../../evidence/screenshots/v0.1-staging-exact-27fafae/11-public-catalog.png]]

### `VJS-J01-D-02`

![[../../evidence/screenshots/v0.1-staging-exact-81635d1/register-desktop-1488x1058.jpg]]

### `VJS-J01-D-04`

![[../../evidence/screenshots/v0.1-drive-aligned/04-onboarding-loading-desktop.png]]

### `VJS-J01-D-05`

![[../../evidence/screenshots/v0.1-staging-exact-27fafae/01-learner-home-authorized.png]]

### `VJS-J01-D-06`

![[../../evidence/screenshots/v0.1-staging-exact-27fafae/14-program-detail.png]]
