---
id: VJB-JRN-06-D
type: visual-board
title: JRN-06 Desktop Storyboard
status: partial
version: v0.1-alpha
updated: 2026-09-01
journey_id: JRN-06
viewport: desktop
slot_ids:
  [
    VJS-J06-D-01,
    VJS-J06-D-02,
    VJS-J06-D-03,
    VJS-J06-D-04,
    VJS-J06-D-05,
    VJS-J06-D-06,
    VJS-J06-D-07,
  ]
tags:
  - ac/visual-board/desktop
---

# JRN-06 desktop storyboard

Parent: [[JRN-06-admin-operations]]. MOC: [[VJB-MOC-001-visual-journey-boards]].

| #   | Slot           | Expected route/state                                         | Source reference                                           | Candidate/live evidence                                                                                                                      |
| --- | -------------- | ------------------------------------------------------------ | ---------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------- |
| 1   | `VJS-J06-D-01` | `/admin` named-operator overview `ready`                     | [[API-005-admin-operations]]                               | [27fafae admin](../../evidence/screenshots/v0.1-staging-exact-27fafae/15-admin-staging.png) — historical exact release                       |
| 2   | `VJS-J06-D-02` | `/admin/people` `ready/empty`                                | [[SRC-050-trust-operations]]                               | [local people](../../evidence/screenshots/v0.1-local/20-admin-people-desktop.png) — local preview only                                       |
| 3   | `VJS-J06-D-03` | `/admin/catalog` `ready`                                     | [[API-005-admin-operations]]                               | [local catalog](../../evidence/screenshots/v0.1-local/21-admin-catalog-desktop.png) — local preview only                                     |
| 4   | `VJS-J06-D-04` | `/admin/learning-operations` `ready`                         | [[DEC-003-canonical-progress-evidence]]                    | [local learning operations](../../evidence/screenshots/v0.1-local/22-admin-learning-operations-desktop.png) — local preview only             |
| 5   | `VJS-J06-D-05` | `/admin/people/corrections` `processing/success` with reason | [[API-005-admin-operations]]                               | [local corrections](../../evidence/screenshots/v0.1-local/23-admin-corrections-desktop.png) — local preview only; no privileged action proof |
| 6   | `VJS-J06-D-06` | `/admin/people/grants` `processing/success` with reason      | [[API-005-admin-operations]], [[DEC-005-capability-gates]] | [local grants](../../evidence/screenshots/v0.1-local/24-admin-grants-desktop.png) — local preview only; no privileged action proof           |
| 7   | `VJS-J06-D-07` | requested admin route `permission-denied`                    | [[SF-SYS-001-universal-states]]                            | **PENDING — matching desktop permission-denied capture not found**                                                                           |

## Existing embeds

### `VJS-J06-D-01`

![[../../evidence/screenshots/v0.1-staging-exact-27fafae/15-admin-staging.png]]

### `VJS-J06-D-02`

![[../../evidence/screenshots/v0.1-local/20-admin-people-desktop.png]]

### `VJS-J06-D-03`

![[../../evidence/screenshots/v0.1-local/21-admin-catalog-desktop.png]]

### `VJS-J06-D-04`

![[../../evidence/screenshots/v0.1-local/22-admin-learning-operations-desktop.png]]

### `VJS-J06-D-05`

![[../../evidence/screenshots/v0.1-local/23-admin-corrections-desktop.png]]

### `VJS-J06-D-06`

![[../../evidence/screenshots/v0.1-local/24-admin-grants-desktop.png]]
