---
id: DEC-004
type: decision
title: Device-Local Theme and Appearance Preferences
status: implementation-candidate
version: v0.1-alpha
updated: 2026-09-01
tags:
  - ac/decision/theme
---

# Device-local theme and appearance preferences

Light, Dark, and System remain the non-sensitive theme mode choices. Named
appearance presets are convenience bundles, while accent palette, display
density, and motion preference are independently selectable presentation
variants. All of these values are stored best-effort on the current browser;
System follows `prefers-color-scheme` and motion System follows
`prefers-reduced-motion`.

Theme mode and every named appearance variant are browser-local presentation
state only. They are never account, tenant, authority, consent, access,
enrollment, progress, notification, or session state.

There is no authorized account-preference API, cross-device sync, learner/admin
sync, or tenant branding implication. Storage failure falls back to usable
current-page presentation for the current session.

The current browser keys are `ac-appearance-theme`, `ac-appearance-accent`,
`ac-appearance-density`, and `ac-appearance-motion`. Their values are not
canonical product data.

- controls: [[VAR-THEME-001-theme]], [[SF-SET-001-settings]], [[API-004-session-settings]].
- implements: [theme control](../../../apps/learner-web/app/components/theme-control.tsx), [theme CSS](../../../apps/learner-web/app/theme.css), [theme initializer](../../../apps/learner-web/public/theme-init.js).
- validated-by: [[GATE-003-exact-release-staging]].
- status boundary: implementation candidate/runtime pending; no live proof claim.
