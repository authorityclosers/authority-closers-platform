---
id: VAR-THEME-001
type: screen-family
title: Light, Dark, and System Theme Variants
status: runtime-pending
version: v0.1-alpha
updated: 2026-09-01
tags:
  - ac/screen/theme
---

# Light, Dark, and System theme variants

Allowed preference values: `light`, `dark`, `system`. Storage key: `ac-appearance-theme`. `system` resolves through the device color-scheme signal. Storage is best-effort; failure falls back to usable current-page presentation.

Theme changes presentation only. They cannot alter account, tenant, consent, access, enrollment, content, progress, completion, notification, or learner/admin synchronization. Both effective palettes must preserve semantic hierarchy, contrast, focus, non-color status, controls, skeletons, locked/offline/error states, and first paint.

- appears-in: [[JRN-04-profile-settings-appearance]] and [[JRN-05-resilient-web-pwa]].
- decision: [[DEC-004-device-local-theme]].
- implementation: [theme control](../../../apps/learner-web/app/components/theme-control.tsx), [theme CSS](../../../apps/learner-web/app/theme.css), and [first-paint initializer](../../../apps/learner-web/public/theme-init.js).
- validated-by: [[GATE-003-exact-release-staging]].
- known-limitation: no account, cross-device, or admin theme synchronization is authorized or claimed.
