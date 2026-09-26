# Sales Xray web: settled report jumps after a view or viewport change

Implementation evidence based on source HEAD `01743f580e3583821521fe62d1649f7c1a3aaf9b`. It covers the frontend only (`apps/sales-xray-web`). The local browser observations below are separate from deployment.

## Defect

This was reported from staging, using a fictional retained report.

1. The report was loaded at 1440×900 (Tabbed by default). The jump to the final verdict and the return both worked.
2. The viewport was then resized to 720×640, which defaults to Reading view.
   - The first jump to the final verdict settled with the verdict heading at 136.9px.
   - The sticky report navigation ended at 161.8px, so it covered the heading.
3. A second jump without resizing landed correctly, at 181.9px.

## Cause

Three defects in `report-modes.tsx`, plus one fixture gap.

- **Stale end point.** A scroll's end point is resolved only once, when the scroll starts. After a Tabbed→Reading or viewport change, sections render at full length for the first time, and layout can still shift while the smooth scroll is moving. Nothing checked where the destination actually ended up. The later jump was correct because layout had settled by then.
- **Scroll padding not counted.** The sticky navigation sits inside its scroll container's top padding (`.studio-main`, 12px), but scroll margins are measured from the scrollport's edge. The target offset left that padding out (101.8px instead of 113.8px), so even a correct jump put the target's top edge 4px under the navigation.
- **Competing scroll on return.** On Back or Return to an origin URL that carries a `section`, the restored URL's bookmark scroll started as well as the origin restore, so two smooth scrolls ran at once.
- **Fixture fidelity.** The full-shell fixture mounted the report directly in `.xray-app`, without the mobile-fit shell or `.studio-main`, so it had a different scroll container from production.

## Changes

`report-modes.tsx`:

- **Fresh offsets.** Every jump re-measures the shell chrome and navigation immediately before scrolling, instead of relying on a ResizeObserver callback that may not have run yet.
- **Settle check.** After the scroll ends (`scrollend`, or scroll position unchanged for three frames; at most 240 frames), the destination is measured once more. If it has drifted more than 1px from the navigation offset, only the report's real scroller (its nearest scrolling ancestor, else the document) is corrected once with an instant `scrollTo`. Nothing else is scrolled.
  - No fixed padding or timer is added.
  - Reader wheel, touch, pointer or key input cancels the correction.
  - A new jump, Return, Back or unmount also cancels it.
  - Hidden or unmeasurable targets are left alone.
- **Offset includes padding.** The target offset now counts the scroll container's top padding.
- **Return without a second scroll.** While an origin restore is pending, the restored URL's section bookmark scroll is suppressed. Focus and position return only to the control that started the jump.
- **Unchanged:** reduced-motion instant scrolling, Tabbed/Reading defaults, section push/replace history, return-pill placement and keyboard tab navigation.

`review-fixture/shell/full-shell-preview.tsx` and its CSS module:

- The fixture now mounts inside the mobile-fit shell, in the same ancestry as production: `main` > `.xray-app` (light theme, standalone variant, report stage) > `.studio-main` > `.studio-report`.
- The fixture's own page padding is removed, so `.studio-main` owns padding and scrolling as in production.

## Tests (local, Vitest with 2 workers)

- `report-modes.test.tsx`: 23 passed. It includes two new regression tests:
  - **Stale first jump.** Production geometry: the scroller starts at 56px with 12px padding, and the navigation is 93.8px tall. The browser's scroll is simulated landing the verdict at 113.1px. The jump settles with the verdict at 169.8px, below the navigation bottom of 161.8px. Only one smooth scroll runs, and focus is on the verdict.
  - **Back to a section URL.** Only the originating control is scrolled back into view and focused. No second section scroll runs.
- Focused set: `report-modes`, `full-shell-preview` (which now asserts the production scroll ancestry), `report-header` and `dipak-overview`. 4 files, 62 tests passed.
- `tsc --noEmit`: passed. ESLint (max warnings 0) on the changed files: passed. Prettier: applied.

## Browser proof

Root checked the fictional `/review-fixture/shell` on the local development server with Chrome. At 720×640 the settled final-verdict heading was at 194.03px, below the navigation bottom at 161.80px. There was no horizontal document overflow. Browser Back restored focus to `Read the final verdict`, visible at 290.18px. With reduced motion emulated, the verdict again settled at 194.03px; the return control ended at 490.41px, above the dock at 503.20px. The temporary media emulation was cleared afterward.

The first immediate desktop-to-compact attempt did not establish a settled desktop state. Root repeated it after confirming 1440px width, the desktop media query, Tabbed pressed, Reading unpressed, and an origin URL with no view parameter. After resizing to 720×640, the first verdict jump again settled at 194.03px, navigation ended at 161.80px, focus was on review point 14, and the return control stayed above the dock with no horizontal overflow.

These are DOM geometry/focus observations using fictional data, not audio or report-quality tests. Screenshot requests timed out, so no screenshot proof is claimed. Staging still runs the preceding `01743f58` increment, not this patch. Repeat the original three steps after release and confirm the settled first jump, Back, keyboard navigation, and reduced motion on staging.

## Remaining risks

- If layout shifts again after the correction (for example, late media or fonts), the destination may move once more. The correction runs once per jump.
- In browsers without `scrollend`, "settled" is detected from three unchanged frames. A smooth scroll that pauses for three frames would be corrected early; the correction is instant but lands in the right place.
- The simulated geometry proves the logic, not the real browser's layout timing. Confirming the settled position in a real browser remains open.
