# Paused processing layout — 2026-09-24

## Scope

Kept a held C5 analysis readable when the processing panel is shown at compact desktop heights. The processing stages, waveform/status card, saved audio card, and recovery footer remain in normal flow. The processing-only getting-started rail is hidden while an uploaded call is being processed.

The paused browser screenshots use the local synthetic review fixture; they contain no uploaded recording or generated report. The component regression test separately renders the real-call paused panel contract and verifies that the uploaded file and recovery actions remain in order.

## Browser evidence

- Runtime: local Next.js dev server at `http://salesxray.localhost:3016`; Playwright Chromium; light appearance; `?new=1&sx-fixture=processing.paused`.
- 1448×900: document height 900px. Stage list: y=288–463; waveform/status card: y=481–596; example audio card: y=625–757; footer: y=766–781.
- 1024×768: document height 768px (no document scroll). Stage list: y=215–342; waveform/status card: y=355–458; example audio card: y=482–596; footer: y=605–618.
- Both viewports passed ordered-boundary assertions for all three cards and no onboarding rail in the processing fixture.

Screenshots:

- [Desktop 1448×900](desktop-1448x900.png)
- [Compact 1024×768](compact-1024x768.png)

## Checks

- `pnpm --filter @ac/sales-xray-web exec vitest run app/acquisition-processing-panel.test.tsx app/acquisition-studio.test.tsx app/fixture-review-states.test.ts` — 77 tests passed.
- `pnpm --filter @ac/sales-xray-web typecheck` — passed.
- Focused ESLint — passed.
- Focused Prettier check — passed.
- `git diff --check` — passed.

The workspace runtime is Node 22.17.0, below the package's declared Node 24 requirement; commands completed successfully with the engine warning.

## Release integration

Integrated from UI checkpoint `5bed485246119314f2b755a3d6dcc5ca66e0506c` onto release candidate `0b3f031e23985770519b45c305517489e23be50f`. The release keeps its existing compact spacing and recovery actions before the stage list and uploaded file. The conflicting upstream test asserting file-before-actions was not adopted; the release regression asserts the earlier recovery-action order.

The three focused suites pass together: 77 tests using Node 24.19.0. The screenshots above belong to the UI checkpoint, not the combined release candidate; they do not establish browser acceptance of the merged candidate.
