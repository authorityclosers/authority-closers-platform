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
| `STG-SET-02` | `SET-02`     | Light/Dark/System mode plus named preset, accent, density, and motion controls are non-sensitive browser-local presentation only |
| `STG-SET-03` | `SET-03`     | learning profile remains a summary and links to the revisioned onboarding editor                                                  |
| `STG-SET-04` | `SET-04`     | use existing password recovery and Terms/Privacy routes only; no invented deletion/MFA/SSO/notification/integration behavior   |
| `STG-SET-05` | `SET-05`     | same-origin logout and session-expiry recovery remain the session boundary                                                          |

Storage failure falls back safely for the current page. Theme mode and every
advanced appearance choice must preserve hierarchy, meaning, focus, state, and
permissions; none is account, tenant, or authority state.

- routes-to: [[RT-004-progress-settings-system]].
- renders: [[SF-SET-001-settings]] and [[VAR-THEME-001-theme]].
- calls: [[API-004-session-settings]] and [[API-001-identity-onboarding]].
- constrained-by: [[DEC-004-device-local-theme]].
- known-limitation: implementation candidate/runtime pending; no exact-current staging, account sync, or cross-app theme claim.
