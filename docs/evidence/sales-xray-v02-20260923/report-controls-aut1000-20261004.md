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

The first PR run passed single-track and static checks, but the compiled
acquisition journey still searched for mode buttons inside the closed disclosure.
Its assertions now open the controls before inspecting choices and verify the
workspace mode after a selection closes them. The required journey must pass
on the updated PR head; this is a test adaptation, not a waiver of that gate.

The public dev URL returned HTTP 403 from this runtime. These are local dev
screenshots, not staging or production evidence. No Chrome Pro session or local
`ac-orchestra` skill was available; the slice reuses the existing native report
menu pattern without new research, provider calls or a new visual system.

Remaining AUT-1000 slices: measurements, prospect presentation, richer charts,
phone section padding, and final staging captures. This change does not complete
the whole report-polish brief. Review this slice before beginning another area.

## Review corrections

The independent review at `30c82d2` found two defects. The retained-library
browser journey now checks the visible report workspace's `data-view="tabs"`
after mode selection closes the dropdown. An outside pointer press now recovers
focus from a hidden option after the browser's native focus change, while keeping
focus on an outside input or link. Two regression tests cover both outcomes.

The review's focus defect reproduced on the current dev server at both 390 and
1440 px before the repair. Afterwards, native browser checks passed at both
widths: focus returned to the trigger after clicking the page heading; outside
input and link focus remained intact. The fictional actual-shell checks also
passed sticky placement, hover/click/keyboard dismissal and no horizontal
page overflow, without page errors, external requests or API mutations. The first
shell attempt timed out during initial route load; the same checks passed after
loading completed and on the canonical `/analysis/calls/<id>` route.

Current revision checks: 154 tests passed across `report-modes.test.tsx` (45) and
`acquisition-studio.test.tsx` (109), using direct Vitest execution with two workers
and a 15-second timeout. ESLint, TypeScript, Prettier, Ruff format/check, mypy,
14 browser-gate infrastructure tests and the lane check passed. The package-script
`test -- <file>` command did not apply the intended file filter; that unintended
whole-suite run was stopped after acquisition test failures at the default
timeout. The bounded two-file rerun passed, and no test configuration changed.
The prior full-suite result above belongs to the earlier revision.

The required compiled acquisition journey must still pass in CI on the new head;
it was not rerun locally. The repair evidence bundle is attached to AUT-1000 as
`06e94bba-cec8-4bb7-b24c-189750dfc398`. Staging, production and physical devices
remain unverified. Other tasks' uncommitted Calls-library files were preserved
and excluded from this commit.
