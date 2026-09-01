---
id: VJB-JRN-01-M
type: visual-board
title: JRN-01 Mobile Storyboard
status: partial
version: v0.1-alpha
updated: 2026-09-01
journey_id: JRN-01
viewport: mobile
slot_ids:
  [
    VJS-J01-M-01,
    VJS-J01-M-02,
    VJS-J01-M-03,
    VJS-J01-M-04,
    VJS-J01-M-05,
    VJS-J01-M-06,
  ]
tags:
  - ac/visual-board/mobile
---

# JRN-01 mobile storyboard

Parent: [[JRN-01-account-to-first-value]]. MOC: [[VJB-MOC-001-visual-journey-boards]].

| #   | Slot           | Expected route/state              | Source reference                                                                        | Candidate/live evidence                                                                                                           |
| --- | -------------- | --------------------------------- | --------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------- |
| 1   | `VJS-J01-M-01` | `/` mobile catalog `ready`        | `COURSE-02`; [[SF-COURSE-001-free-course]]                                              | [local public home](../../evidence/screenshots/v0.1-local/25-learner-public-home-mobile.png) — local preview                      |
| 2   | `VJS-J01-M-02` | `/register` mobile `ready`        | [AUTH-01 Drive](https://drive.google.com/file/d/1K9qpP-OTsgyuhJ3mtmZYDj2-7EFv_MJb/view) | [81635d1 register](../../evidence/screenshots/v0.1-staging-exact-81635d1/register-mobile-375x1125.jpg) — historical exact release |
| 3   | `VJS-J01-M-03` | `/verify-email` `success`/session | [AUTH-02 Drive](https://drive.google.com/file/d/1NLx4nRVxS_5bsu9hOMjEHW5Yb25GwNr5/view) | **PENDING — successful mobile verification not captured**                                                                         |
| 4   | `VJS-J01-M-04` | `/onboarding` `loading → ready`   | [ONB-02 Drive](https://drive.google.com/file/d/1ewm-HXQZv10tkfq3UNvly4JWHeIAFOWT/view)  | [local loading](../../evidence/screenshots/v0.1-drive-aligned/13-onboarding-loading-mobile.png) — local preview                   |
| 5   | `VJS-J01-M-05` | `/home` authenticated `ready`     | [HOME-01 Drive](https://drive.google.com/file/d/1CgJ3XhYcclRxj2Zb6HRUXnH6pcQEcu01/view) | **PENDING — matching authenticated mobile home not captured**                                                                     |
| 6   | `VJS-J01-M-06` | exact course detail/start         | `COURSE-02`; [[DEC-001-public-learner-tenancy-consent]]                                 | **PENDING — matching mobile start state not captured**                                                                            |

## Existing embeds

### `VJS-J01-M-01`

![[../../evidence/screenshots/v0.1-local/25-learner-public-home-mobile.png]]

### `VJS-J01-M-02`

![[../../evidence/screenshots/v0.1-staging-exact-81635d1/register-mobile-375x1125.jpg]]

### `VJS-J01-M-04`

![[../../evidence/screenshots/v0.1-drive-aligned/13-onboarding-loading-mobile.png]]
