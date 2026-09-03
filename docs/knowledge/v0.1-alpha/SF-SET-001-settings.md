---
id: SF-SET-001
type: screen-family
title: Learner Settings Screen Family
status: runtime-pending
version: v0.1-alpha
updated: 2026-09-01
screen_ids:
  - SET-01
  - SET-02
  - SET-03
  - SET-04
  - SET-05
tags:
  - ac/screen/settings
---

# Learner settings screen family

Route: `/settings`.

| ID       | Card/action                    | Boundary                                                |
| -------- | ------------------------------ | ------------------------------------------------------- |
| `SET-01` | verified account/profile facts | reads `/v1/me`; profile edits return to `ONB-01`        |
| `SET-02` | appearance                     | Light/Dark/System mode plus named preset, accent, density, and motion controls; browser-local only |
| `SET-03` | learning profile               | links to existing onboarding editor                     |
| `SET-04` | security/privacy               | existing password recovery and Terms/Privacy links only |
| `SET-05` | session                        | same-origin logout and session-expiry recovery          |

Named presets and accent, density, and motion choices are presentation-only
browser state. They never become account, tenant, authority, consent, access,
progress, or session state. No account deletion workflow, MFA, SSO,
notifications, integrations, tenant branding, or account-level theme sync is
inferred.

- appears-in: [[JRN-04-profile-settings-appearance]].
- routes-to: [[RT-004-progress-settings-system]].
- calls: [[API-004-session-settings]] and [[API-001-identity-onboarding]].
- implementation: [settings page](../../../apps/learner-web/app/settings/page.tsx) and [settings runtime](../../../apps/learner-web/app/components/settings-runtime.tsx).
- variant: [[VAR-THEME-001-theme]].
