---
id: JRN-04
type: journey
title: Profile, Settings, and Appearance
status: runtime-pending
version: v0.1-alpha
updated: 2026-09-01
controlled_by:
  - "[[SRC-020-product-experience]]"
  - "[[SRC-030-state-interface-assurance]]"
tags:
  - ac/journey/settings
---

# JRN-04 — Profile, settings, and appearance

Actor: authenticated learner. Goal: inspect bounded account facts, return to the existing onboarding profile editor, control local appearance, and sign out safely.

| Stage        | Surface      | Boundary                                                                                                                         |
| ------------ | ------------ | -------------------------------------------------------------------------------------------------------------------------------- |
| `STG-SET-01` | `SET-01`     | `/v1/me` facts are read-only on settings; profile edits route to `ONB-01` and reuse revision semantics                           |
| `STG-SET-02` | `SET-02`     | Light, Dark, System is non-sensitive device-local presentation only                                                              |
| `STG-SET-03` | `SET-03..05` | use existing password recovery, Terms/Privacy, and logout routes; no invented deletion/MFA/SSO/notification/integration behavior |

Storage failure falls back safely for the current page. Theme changes must preserve hierarchy, meaning, focus, state, and permissions.

- routes-to: [[RT-004-progress-settings-system]].
- renders: [[SF-SET-001-settings]] and [[VAR-THEME-001-theme]].
- calls: [[API-004-session-settings]] and [[API-001-identity-onboarding]].
- constrained-by: [[DEC-004-device-local-theme]].
- known-limitation: implementation candidate/runtime pending; no exact-current staging, account sync, or cross-app theme claim.
