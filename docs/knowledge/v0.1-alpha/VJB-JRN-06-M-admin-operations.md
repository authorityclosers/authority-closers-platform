---
id: VJB-JRN-06-M
type: visual-board
title: JRN-06 Mobile Storyboard
status: pending-capture
version: v0.1-alpha
updated: 2026-09-01
journey_id: JRN-06
viewport: mobile
slot_ids:
  [
    VJS-J06-M-01,
    VJS-J06-M-02,
    VJS-J06-M-03,
    VJS-J06-M-04,
    VJS-J06-M-05,
    VJS-J06-M-06,
    VJS-J06-M-07,
  ]
tags:
  - ac/visual-board/mobile
---

# JRN-06 mobile storyboard

Parent: [[JRN-06-admin-operations]]. MOC: [[VJB-MOC-001-visual-journey-boards]].

| #   | Slot           | Expected route/state                                         | Source reference                                           | Candidate/live evidence                                                                                                           |
| --- | -------------- | ------------------------------------------------------------ | ---------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------- |
| 1   | `VJS-J06-M-01` | `/admin` named-operator overview `ready`                     | [[API-005-admin-operations]], [[VAR-RESP-001-responsive]]  | [drive-aligned overview](../../evidence/screenshots/v0.1-drive-aligned/15-admin-overview-mobile.png) — local design evidence only |
| 2   | `VJS-J06-M-02` | `/admin/people` `ready/empty`                                | [[SRC-050-trust-operations]]                               | **PENDING — matching mobile people capture not found**                                                                            |
| 3   | `VJS-J06-M-03` | `/admin/catalog` `ready`                                     | [[API-005-admin-operations]]                               | [drive-aligned studio](../../evidence/screenshots/v0.1-drive-aligned/16-admin-studio-mobile.png) — local design evidence only     |
| 4   | `VJS-J06-M-04` | `/admin/learning-operations` `ready`                         | [[DEC-003-canonical-progress-evidence]]                    | **PENDING — matching mobile learning-operations capture not found**                                                               |
| 5   | `VJS-J06-M-05` | `/admin/people/corrections` `processing/success` with reason | [[API-005-admin-operations]]                               | **PENDING — matching mobile correction capture not found**                                                                        |
| 6   | `VJS-J06-M-06` | `/admin/people/grants` `processing/success` with reason      | [[API-005-admin-operations]], [[DEC-005-capability-gates]] | **PENDING — matching mobile grant capture not found**                                                                             |
| 7   | `VJS-J06-M-07` | requested admin route `permission-denied`                    | [[SF-SYS-001-universal-states]]                            | **PENDING — matching mobile permission-denied capture not found**                                                                 |

## Existing embeds

### `VJS-J06-M-01`

![[../../evidence/screenshots/v0.1-drive-aligned/15-admin-overview-mobile.png]]

### `VJS-J06-M-03`

![[../../evidence/screenshots/v0.1-drive-aligned/16-admin-studio-mobile.png]]
