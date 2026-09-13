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

## Final acceptance on cb886ef

Runtime source: `cb886effe8f6d21c5fbe1e645d625adeca4d3107`.
The last change adds space between the practice callout and first overview
finding, after inspecting the Marathi mobile screenshot.

- **70 UI tests pass** across 10 files; the last CSS-only spacing change does
  not change those tested components or test code.
- Optimized standalone and learner builds pass on the final source.
- The optimized standalone served through `next start` on loopback3204 passes
  all six report sections, four language modes,320px layout, keyboard navigation,
  persistent audio/search/sound state and playback error recovery. This browser
  uses synthetic API/media fixtures and substitutes `media.play` for recovery
  coverage; it is not live provider proof or Linux packaged-image acceptance.
- Its three-page PDF includes all eight factor observations, draft status,
  sound value and next-step guidance. Inactive panels print; tab controls do not.
- **3 actual HTTP/AC identity/disposable PostgreSQL browser tests pass in
  103.33 seconds** using the same source's static export. The identity case has
  14 checks/18 API responses; each upload case has8 checks/23 API responses.
  They cover password login, explicit workspace selection, actual WAV playback
  and seek, saved native48kHz measurements, logout401, fresh private WAV upload,
  actual local native completion and saved report reopening. Zero external
  browser requests or browser errors were recorded. Durable report inference
  uses a synthetic ReportingBroker; it is not a paid/free provider run.

[Portable receipts and synthetic report](sales-xray-navigation-20260914/README.md)
include exact-byte manifests. Earlier failed setup receipts remain outside Git:
`sales-xray-navigation-cb886ef-auth-20260914` rejected the default repository
test storage path; `...-auth-retry2-20260914` lacked the prebuilt native artifact.
The final retry uses a new external fixture directory and the existing binary
whose native source and binary checksums were verified before reuse. No storage
or native-runtime guard was changed to make the test pass.

Read-only live checks at2026-09-13T18:51:42Z still find both learner Sales pages
200 and anonymous recording APIs401/no-store. Both standalone hosts fail to
connect. This update is not staged or production-published. Combined candidate
975653e is being validated by the sole release owner; no competing image or
installer was dispatched from this lane. Hosted real-call approval remains
pending in this thread, and no new provider spend occurred.
