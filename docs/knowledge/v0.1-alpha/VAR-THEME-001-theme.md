---
id: VAR-THEME-001
type: screen-family
title: Theme Mode and Advanced Appearance Variants
status: runtime-pending
version: v0.1-alpha
updated: 2026-09-01
tags:
  - ac/screen/theme
---

# Theme mode and advanced appearance variants

Theme mode values are `light`, `dark`, and `system`; `system` resolves through
the device color-scheme signal. The appearance surface also supports bounded
named presets, accent palette (`cobalt`, `indigo`, `emerald`, `amber`, `slate`),
display density (`comfortable`, `compact`), and motion (`system`, `reduced`,
`full`). A named preset is a convenience bundle of these presentation values,
not a separate authority or account profile.

Storage keys are `ac-appearance-theme`, `ac-appearance-accent`,
`ac-appearance-density`, and `ac-appearance-motion`. Storage is best-effort on
the current browser; failure falls back to usable current-page presentation.
Motion `system` follows `prefers-reduced-motion`.

Light/Dark/System mode and every advanced appearance variant change
presentation only. They cannot alter account, tenant, authority, consent,
access, enrollment, content, progress, completion, notification, or
learner/admin synchronization. Both effective palettes and all variants must
preserve semantic hierarchy, contrast, focus, non-color status, controls,
skeletons, locked/offline/error states, and first paint.

- appears-in: [[JRN-04-profile-settings-appearance]] and [[JRN-05-resilient-web-pwa]].
- decision: [[DEC-004-device-local-theme]].
- implementation: [theme control](../../../apps/learner-web/app/components/theme-control.tsx), [theme CSS](../../../apps/learner-web/app/theme.css), and [first-paint initializer](../../../apps/learner-web/public/theme-init.js).
- validated-by: [[GATE-003-exact-release-staging]].
- known-limitation: no account, cross-device, or admin theme synchronization is authorized or claimed.
