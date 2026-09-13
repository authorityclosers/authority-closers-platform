# Sales report section navigation

This increment follows the accepted `63d5a5e` report and measurement runtime.
The product change is confined to the mounted CallStudio report and new
ReportExplorer component, styles and four-mode navigation labels.

The report now offers Overview, Sales factors, Call moments, Transcript,
Sound and Next steps. Selecting a section preserves mounted audio, transcript
search and sound chart state. Arrow keys, Home and End move selected tab and
keyboard focus. Sections absent from the supplied data are omitted; this does
not authorize or fetch additional report fields. Printing displays all supplied
sections, including inactive tabs, while keeping navigation controls out of PDF.
Original report text and exact timestamp playback remain unchanged.

The three new behavioral tests verify retained state across language/section
changes, keyboard focus and removal of a formerly selected section. The full
Sales suite currently passes **70 tests across 10 files**. JUnit is preserved at
`D:/AC-authority-closers-release-audit/sales-xray-report-navigation-20260914-vitest.xml`.
Sales ESLint passes. An initial refactor had a syntax error caught by the test
transformer; it was fixed before this checkpoint. The optimized build passed
before a final style adjustment; final build/browser evidence follows separately.

Existing browser harnesses now select the visible tabs before exercising the
same actual audio, factors, transcript and measurements assertions. They are
not replaced with source-string checks. The fixture UX browser additionally
checks all six sections, persistent media element, four label modes, 320px
keyboard navigation, retained sound channel/cursor and complete print output.

This is a separate candidate, not a deployed version. It does not change guest
contracts, identity, minute accounting, worker/provider activation or review
policy. No new provider or private recording execution is claimed.
