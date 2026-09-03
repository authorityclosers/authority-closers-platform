---
id: SF-SYS-001
type: screen-family
title: Universal Presentation and Recovery States
status: specification-ready
version: v0.1-alpha
updated: 2026-09-01
screen_ids:
  - SYS-01
  - SYS-02
  - SYS-03
  - SYS-04
tags:
  - ac/screen/state
---

# Universal presentation and recovery states

Presentation vocabulary: `DEFAULT`, `LOADING`, `EMPTY`, `ERROR_RETRYABLE`, `ERROR_TERMINAL`, `OFFLINE`, `PERMISSION_DENIED`, `LOCKED`, `PARTIAL`, `SUCCESS_FEEDBACK`.

Stable system screens: `SYS-01` loading, `SYS-02` retryable error, `SYS-03` offline, `SYS-04` locked. These are Layer 1 presentation states. They must be paired with Layer 2 canonical business state and Layer 3 recovery/operator ownership; `PARTIAL` or a generic spinner cannot stand in for pending enrollment, evidence processing, reconciliation, or another durable domain state.

- controlled-by: [[SRC-030-state-interface-assurance]].
- used-by: every screen family and [[JRN-05-resilient-web-pwa]].
- implementation: [surface-state vocabulary](../../../apps/learner-web/app/lib/surface-state.ts) and [surface-state component](../../../apps/learner-web/app/components/surface-state.tsx).
- route: `/offline` is in [[RT-004-progress-settings-system]].
- validated-by: [[GATE-003-exact-release-staging]].
