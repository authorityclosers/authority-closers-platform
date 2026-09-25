# Report scroll chrome offsets

Date: 2026-09-26. This note records a narrow correction to report navigation and the Return shortcut. It does not claim browser acceptance or change deployment state.

The report nav row can stick at the top of its nearest scrollport while the shell's mobile bar also occupies the viewport top. `ReportModes` now measures the nav row, the overlap between a sticky mobile bar and the nearest scrollport, and the top of a fixed non-embedded audio dock. It applies those measured values to nav stickiness, report section and overview jump margins, and the Return pill's bottom clearance. Reports outside the shell do not acquire shell-bar or dock offsets; the Return pill keeps its existing CSS fallback. A non-sticky mobile bar and static dock in short viewports are not counted as overlays.

The measured fixture regression covers a 720×640 layout with a 56 px mobile bar and a 115.4 px report nav row, plus an inner scrollport that already starts below the bar. It asserts the computed offsets and a 12 px Return-pill gap above the audio dock.

Verification: `report-modes.test.tsx` **21 passed**; `dipak-overview.test.tsx` and `report-moments.test.tsx` **51 passed**; web typecheck passed; focused ESLint passed. Real-browser verification remains with the root owner.
