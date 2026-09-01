---
id: VAR-RESP-001
type: screen-family
title: Responsive and Platform Variants
status: runtime-pending
version: v0.1-alpha
updated: 2026-09-01
tags:
  - ac/screen/responsive
  - ac/pwa
---

# Responsive and platform variants

The same screen IDs and business meaning apply across desktop, mobile web, installed Edge PWA, iOS Safari, and iOS Home Screen. Responsive layout is a variant, not a new route or permission model.

Required checks include 320–1440px reflow, no unintended horizontal overflow at 390px, visible non-obscured focus, keyboard order, semantic landmarks, 200% zoom, AC 44px mobile target intent, safe-area insets, reduced motion, update safety, and protected-cache boundaries.

- controlled-by: [[SRC-030-state-interface-assurance]] and [[SRC-050-trust-operations]].
- used-by: [[JRN-05-resilient-web-pwa]].
- implementation: [root layout](../../../apps/learner-web/app/layout.tsx), [learner styles](../../../apps/learner-web/app/learner-clarity.css), [PWA manifest](../../../apps/learner-web/app/manifest.ts), and [service worker](../../../apps/learner-web/public/sw.js).
- evidenced-by: [[EVD-002-auth-81635d1]] and [[EVD-003-current-candidate-design-qa]] only for their named viewports.
- known-limitation: real Edge installed-PWA and iOS Safari/Home Screen exact-release runs remain open.
