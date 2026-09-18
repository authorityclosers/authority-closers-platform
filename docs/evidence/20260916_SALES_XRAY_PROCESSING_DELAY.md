# Sales Xray — stable delayed-update guidance

2026-09-16. Bounded candidate on `d68db7501d381c94da9fe088b3c9a05271e7b277`.
This is compiled local synthetic QA, not a production deployment claim.

## Change and authority

After 60 seconds without a change in the parsed progress projection, the
existing status copy becomes “Waiting for an update” / “No new stage update
yet. Your call is saved; no need to upload again.” The actual stage heading,
stage statuses, source identity and saved-call navigation remain unchanged.
This is a local observation window, not an SLA, provider timeout or failure.

The component is keyed by submission identity and semantic progress. Identical
polls do not reset it; new stage rows, state changes and new submissions do.
Held/error guidance takes precedence and unmounts its timer. Completion removes
the panel. There are no new requests, approval actions or re-upload behavior.
Both copy variants occupy one reserved text area; the hidden variant is absent
from the accessibility tree. Existing reduced-motion handling is unchanged.

Selected visual grounding: the user's Sep16 report references and the genuine
[desktop](../design/sales-xray-20260916/processing-paused-desktop-v1.png) and
[mobile](../design/sales-xray-20260916/processing-paused-mobile-v1.png) processing
references. This is an in-place refinement of that implemented state family,
not a regenerated design direction. No new raster artwork is required.

## Verification

- Full frontend suite: **221 tests, 26 files, passed**.
- Independent reviewer: **50 tests, 2 files, passed**; no concrete P0–P2 finding.
- ESLint with zero warnings; production Next build and TypeScript: passed.
- `git diff --check`: passed.
- Browser: compiled Next app, Node24.19.0, Chromium, reduced motion, loopback3125.
- All `/v1` requests intercepted with synthetic fixtures; no real recording,
  provider processing, session transfer or production mutation.
- Baseline d68 compiled on loopback3124: C4 and held at all four sizes.
- Candidate: C2, C4, C5, delayed-C2/C4/C5, held = **28 viewport checks**.
- **12 delayed-copy transitions**: all four status-panel child rectangles
  identical before/after, zero new mutations, exact server status retained.
- **12 delayed-to-held transitions**: recovery replaces wait copy, retains
  completed transcript and stays within viewport without auto-resume.
- Mounted tests additionally exercise delay → new stage → report, same-stage
  chunk progress, different source, held/error precedence and timer cleanup.

| Viewport | Main visible height | Main scroll height | Document height |
| --- | --- | --- | --- |
| 1440×900 | 838 | 838 | 900 |
| 1024×626 | 564 | 564 | 626 |
| 390×844 | 698 | 698 | 844 |
| 375×667 | 521 | 521 | 667 |

Every row applies to all seven candidate states. No runtime page errors.
Measured data: [candidate](sales-xray-processing-delay-20260916/results.json),
[baseline](sales-xray-processing-delay-20260916/baseline-results.json).
Screenshots in the same directory preserve both baselines and all delayed
variants. Desktop1440 and mobile375 delay/held were visually inspected against
the selected state-family references; compact1024/390 are measured as well.

## Scope limitations / next work

This does not claim that provider work stopped, explain a provider delay, or
fix connection errors. Existing poll-error classification/layout is separate
recovery work. Overview, Moments, remaining review-sheet states and Admin UI
remain open. Native device behavior, zoom and screen-reader certification are
not established by these desktop-emulated viewports. Production release is
owned by the release coordinator; do not label this candidate live until that
exact release is verified.

The workflow-ui-production skill shaped the bounded state change, preserved
authority boundaries and baseline/candidate evidence.
