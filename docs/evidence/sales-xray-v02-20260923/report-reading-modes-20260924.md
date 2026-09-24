# Sales Xray report reading checkpoint

## Implementation

- The saved report opens in a continuous reading view. A mode control switches to section tabs without unmounting report panels or the audio dock.
- Reading view exposes the supplied Overview, Prospect, Moments, Sales skills, Next-call plan, and Transcript content. Source excerpt actions retain their seek callbacks. Reading bookmarks are bound to the selected call UUID.
- The report uses the existing self-hosted Source Sans 3 font and semantic surface, text, border, and action tokens. The section labels are smaller chapter markers so they do not compete with content titles.
- The mobile report reserves space below the final content for the fixed audio dock and bottom navigation.
- A saved call awaiting plan approval now says “Ready to analyse” in the shell. It does not claim analysis has started.

## Verification

- `pnpm --dir apps/sales-xray-web exec vitest run --maxWorkers=2` with the nine report, shell, and fixture test files — 68 tests passed. The large `app/acquisition-studio.test.tsx` file was run separately with `--maxWorkers=1` after a Windows worker-start error; all 71 tests passed. Total: 139 passing tests.
- `pnpm --dir apps/sales-xray-web typecheck` — passed.
- `git diff --check` — passed.
- Local browser review of `/review-fixture/report` at 1366 × 768: continuous reading layout, left contents rail, Source Sans 3, no horizontal overflow (document and client widths both 1351 px). Section jump placed its heading at 72 px, below the 54 px sticky toolbar.
- Local browser review of `/review-fixture/report` at 390 × 844: single-column content, Source Sans 3, no horizontal overflow (document and client widths both 375 px). The Next-call plan jump placed its heading at 155 px, below the 129 px sticky controls, and marked that chapter current.

## Render evidence

- [Laptop opening view](report-reading-laptop-top-1366x768.png)
- [Laptop chapter view](report-reading-laptop-1366x768.png)
- [Mobile opening view](report-reading-mobile-top-390x844.png)
- [Mobile chapter view](report-reading-mobile-chapter-390x844.png)

The browser images use invented fixture dialogue and contain no recording or provider output. The real saved-report audio continuity is verified by the acquisition integration test with its mocked source; the local fixture has no audio. The fixed dock clearance is based on the app's 70 px mobile dock above its 72 px bottom navigation and the report's 160 px bottom reserve; that exact combined layout was not browser rendered in this fixture.
