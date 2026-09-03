---
id: JRN-05
type: journey
title: Resilient Web and PWA Use
status: specification-ready
version: v0.1-alpha
updated: 2026-09-01
controlled_by:
  - "[[SRC-030-state-interface-assurance]]"
  - "[[SRC-050-trust-operations]]"
tags:
  - ac/journey/resilience
---

# JRN-05 — Resilient web and PWA use

Actor: learner using Windows Edge/browser/PWA or iOS Safari/Home Screen under interruption. Goal: recover current state without fabricated mutation or silent work loss.

- Loading preserves structure and never becomes a false empty state.
- Offline cached data is labeled stale only when safe; protected or sensitive mutations remain blocked unless an explicit local-draft contract exists.
- Session expiry returns to the intended route and preserves safe draft context.
- Service-worker updates must not reload over dirty learner work.
- Responsive variants preserve the same business meaning; safe areas, keyboard focus, reflow, and target size are release checks.

- renders: [[SF-SYS-001-universal-states]], [[VAR-RESP-001-responsive]], [[VAR-THEME-001-theme]].
- routes-to: [[RT-004-progress-settings-system]].
- validated-by: [[GATE-003-exact-release-staging]].
- known-limitation: current viewport captures do not substitute for real Edge installed-PWA or iOS Safari/Home Screen evidence; see [[LIM-001-known-limitations]].
