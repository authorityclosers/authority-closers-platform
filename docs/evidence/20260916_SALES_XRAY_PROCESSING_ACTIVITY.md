# Sales Xray — visible processing activity

2026-09-16. Bounded follow-up to the approved/released report UI; base `e6cf596`.

## Scope and state contract

- Preserve the approved shell, panel, stage rail and recovery controls.
- Add a phase-coloured rotating ring and animated audio bars to the existing
  decorative processing visual (upload, recording check, C2, C4, C5).
- Rotate concise informational cues every eight seconds **within the same
  confirmed stage**. Queued stages use waiting copy, not running-stage claims.
- Stage/title/completion remain owned by the mounted acquisition flow and its
  parsed server status. No percentage, completion estimate or timer-driven stage.
- Reserve all cue text in the existing grid so wrapping does not move the panel.
  Informational rotation is excluded from live-region announcements.
- Stop cue rotation at the existing 60-second delayed-update notice. Paused/error
  guidance takes priority; unmounting for a report clears timers. Reduced motion
  disables ring, waveform and cue cycling, including preference changes.
- No acquisition-studio, API, parser, quote, restore or pipeline logic changed.

## Verification

- Node 24.19.0, Next production build and TypeScript: pass.
- ESLint: pass. Frontend Vitest: **244/244**, 27 files, two workers.
- Independent read-only review: no P0–P2; 14/14 focused tests passed. That review
  test subprocess emitted a Node22 engine warning; the full suite/build above
  used the pinned Node24 runtime.
- Compiled loopback3117 Chromium QA, every API intercepted with synthetic data:
  **65 normal-motion records** at 1536×674, 1440×900, 1024×626, 390×844, 375×667;
  **52 reduced-motion records** at the latter four sizes.
- Upload/check/C2/C4/C5/held fit the document and main viewport. Normal active
  visuals have seven running decorative animations; held and reduced-motion
  visuals have zero. Cues change after eight seconds only in normal motion,
  retaining stage/title and layout (less than 0.5 CSSpx measurement tolerance).
  Cue rotation produces no mutations. Nine synthetic upload→report transitions
  pass across the two motion runs. Timer cleanup/report removal is unit-tested.
- Normal-motion phone C4 and desktop C5, plus reduced-motion phone recording
  check screenshots visually inspected. Measured data and screenshots:
  [evidence directory](sales-xray-processing-activity-20260916/normal-motion.json).

This is local compiled/fixture evidence, not a fresh real-call pipeline or live
release claim. The release orchestrator owns deployment and fresh guest E2E.
