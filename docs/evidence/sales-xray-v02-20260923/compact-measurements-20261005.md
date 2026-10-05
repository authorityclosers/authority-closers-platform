# AUT-1000 · compact call measurements · 5 October 2026

Source pin: `a6a68c9c310142a49e71f6cd25db108c297e39f1` (latest main at lane start).
Branch: `task/sx-report/1000-compact-measurements`.

## Scope and implementation

This is the existing call-measurements step only. The three product files are
`app/overview-call-visuals.tsx`, its CSS module and its focused test, under
`apps/sales-xray-web/`. Two existing integration tests update the duration label:
`app/overview-hook.test.tsx` and
`app/review-fixture/report/synthetic-report-preview.test.tsx`.
The exact file scope was recorded before editing; open PR files had no overlap.

Two primary numbers per speaker: talk share and question count. Existing curves
remain visible and are labelled “Talk share by minute”. Talk times and the three
existing playable monologues remain under a native keyboard-operable disclosure.
Cards sit alongside each other when space permits; phone padding stays compact.

Plain-language copy states the transcript basis, excluded gaps, separately
counted overlaps, question-mark counting, included pauses and existing quiet/
recovery thresholds. Call length is distinguished from the last timed-segment
fallback; an empty timing span shows “Unavailable”. Formulas, fields, source
identity, seeks and backend contracts are unchanged.

`owner-surfaces.json` is currently reserved by open PR #334 and absent from this
main pin. Its exact GitHub version was read; all listed report/document/calls
surfaces remain in their existing source. No owner surface or mode was removed.
Navigation and DOCX work are outside this slice.

## Verification

- 39 focused tests passed across measurements, metric vectors, OverviewHook and
  the fictional report fixture. Five measurements tests passed again after the
  final fixture type correction. The initial 5-second fixture timeout passed in
  the two-worker 15-second rerun; no test configuration changed.
- Web lint and TypeScript passed. The first lint process ended with SIGTERM;
  the second complete run passed. Prettier and diff whitespace checks passed.
- Latest-main `ac-gate check` passed.
- Fictional fixture browser checks passed at 390 and 1440 px on the sx-report
  dev server, port 3037. Collapsed section: 362 × 811.75 px and
  1306.19 × 453.94 px. No horizontal overflow, page errors, API mutations or
  external requests. Enter opens the details; Space closes them; playback
  selects the unchanged 20000 ms source. All fixture modes/panels remain.

The evidence bundle contains screenshots, the browser script/receipt and scope
record. The laptop check explicitly chooses Reading after hydration (desktop
otherwise defaults to Tabs); earlier blank/failed captures are not evidence.

## Dev check and limits

Open `https://salesxray-dev.authorityclosers.com/review-fixture/report`; choose
Reading view, then Call-map fixture. Check shares 56%/44%, questions 2/1 and
call length 00:43. Open “Talk time and longest monologues” by keyboard; verify
00:23/00:18 and play 00:20. Repeat at both widths. Operators can inspect this
branch directly at `http://127.0.0.1:3037/review-fixture/report`.

Public dev returned 403 here; port 3026 serves the separate UI checkout.
Staging, physical devices, the complete web suite and compiled production
browser journey were not checked in this run. CI and independent review remain
required before the watchdog merge; then verify dev and staging.

The Windows-only ac-orchestra skill and authorized Pro browser were unavailable
locally (no matching skill, Chrome CDP or ChatGPT connection tool). Existing
Report workspace redesign handoff/data-contract evidence was reused locally.
No new cloud chat or paid provider was used. This is local implementation proof.

Later E8 steps remain on AUT-1000: prospect visuals, remaining chart work,
phone-padding reconciliation against AUT-1003 and final staging captures.
