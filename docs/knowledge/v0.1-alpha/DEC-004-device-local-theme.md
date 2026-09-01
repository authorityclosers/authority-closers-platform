---
id: DEC-004
type: decision
title: Device-Local Theme Preference
status: implementation-candidate
version: v0.1-alpha
updated: 2026-09-01
tags:
  - ac/decision/theme
---

# Device-local theme preference

Light, Dark, and System are non-sensitive presentation preferences stored best-effort on the current browser. System follows `prefers-color-scheme`. Theme is not account, tenant, consent, access, progress, notification, or branding state.

There is no authorized account-preference API, cross-device sync, learner/admin sync, or tenant branding implication. Storage failure falls back to System/current-page presentation.

- controls: [[VAR-THEME-001-theme]], [[SF-SET-001-settings]], [[API-004-session-settings]].
- implements: [theme control](../../../apps/learner-web/app/components/theme-control.tsx), [theme CSS](../../../apps/learner-web/app/theme.css), [theme initializer](../../../apps/learner-web/public/theme-init.js).
- validated-by: [[GATE-003-exact-release-staging]].
- status boundary: implementation candidate/runtime pending; no live proof claim.
