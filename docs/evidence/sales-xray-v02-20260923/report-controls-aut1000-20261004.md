# AUT-1000: compact report navigation, 4 October 2026

Source baseline: `0daf0a5fca7c7e0896ab6365861d876b002dba54`.
Branch: `task/ui/1000-report-polish`.

This is the navigation slice of AUT-1000. Reading, Tabs and Document plus the
existing text sizes now share one dropdown. The adjacent ellipsis opens all
sections by hover, click or keyboard. Escape returns focus to the trigger;
outside presses and focus close disclosures. Section choices preserve the
existing bookmarks and mounted panel state. At the end of a scroll, the tracker
also recognises a visible short final chapter that cannot reach the reading line.

The actual dev server on `http://127.0.0.1:3026` was inspected before edits and
checked afterwards at 390 × 844 and 1440 × 900. All API responses in the shell
checks were intercepted with checked-in fictional fixtures; there were no API
mutations, external requests or page errors. Both sticky placements worked,
including the portaled laptop toolbar. The DOCX check confirmed that its preview
and download contain identical bytes and that all three sizes still work.

Checks: 43 report-mode tests passed; TypeScript, ESLint, Prettier, the lane gate,
and the existing DOCX browser check passed. The default full app run ended with
1188 passed, 6 skipped and two 5-second upload-test timeouts (SIGTERM). Both tests
passed in isolation. The full-suite rerun with two workers and a 15-second timeout
passed: 121 test files, 1191 tests; one file and six tests skipped (305.72 seconds).
The test configuration is unchanged. CI must still pass on the PR head.

The public dev URL returned HTTP 403 from this runtime. These are local dev
screenshots, not staging or production evidence. No Chrome Pro session or local
`ac-orchestra` skill was available; the slice reuses the existing native report
menu pattern without new research, provider calls or a new visual system.

Remaining AUT-1000 slices: measurements, prospect presentation, richer charts,
phone section padding, and final staging captures. This change does not complete
the whole report-polish brief. Review this slice before beginning another area.
