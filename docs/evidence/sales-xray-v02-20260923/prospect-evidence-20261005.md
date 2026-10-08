# AUT-1000: Prospect evidence presentation, 5 October 2026

Source pin: `e63899342d8d122e83bb01690c280640c9c1bbe3`.
Branch: `task/sx-report/1000-prospect-evidence`.

Next existing E8 step: Prospect visuals only. Each supplied interpretation now
has an accessible three-part reading order: playable source words, the report
observation, then the possible meaning. Icons and a vertical connector help
scan the card. The dashed hypothesis treatment and “A guess, not a fact” remain.
Quotes, timestamps, speaker lookup, source callbacks, guest counts, missing-data
copy and the call-only boundary retain their existing meaning. No new fields,
metrics, scoring, API contracts or backend behaviour were introduced.

Exact scope was recorded before edits: `app/prospect-snapshot.tsx`, its CSS and
focused test; `app/review-fixture/report/synthetic-report-preview.tsx` and its
test; this evidence file. Paths are under `apps/sales-xray-web/` except this
note. Open PRs #345/#347 had no file overlap. Owner-approved surfaces are retained.
The display fixture now mounts the real Prospect component with invented data.

Validation: 54 focused tests passed (Prospect, both fixtures, report modes and
owner surfaces), plus full web lint/typecheck, Prettier, whitespace and lane
checks. Browser checks on the lane dev server at port 3037 passed at 390/1440 px:
Reading and Tabs, large text, exact 00:01–00:02 source selection, retained report
sections and no horizontal overflow, page errors, API mutations or external
requests. The fictional full-shell fixture uses the actual report components;
its source selection is a callback check, not recorded audio playback.

Dev check: `https://salesxray-dev.authorityclosers.com/review-fixture/report` →
Prospect. Read the three parts and press Enter on the source control; inspect
its unchanged quote/timestamps in the fixture status. Repeat in Reading/Tabs
and at large text, 390/1440 px. The branch preview is on port 3037; port 3026
serves the separate UI checkout. Public HTTPS redirected to the access path;
authenticated public access, staging, physical devices and the full web suite
were not verified here. CI, independent review and watchdog merge remain.

Navigation reconciliation: latest main deliberately reverted PR #295 through
AUT-1192 / PR #324 (`fa079c6`), restoring the earlier report. This slice preserves
that source and does not reapply the navigation change. Initial browser scripts
used superseded dropdown/button selectors; they were corrected to the current
controls and native tab roles, with an explicit desktop hydration wait.

The Windows-only ac-orchestra skill and authorized Pro browser are unavailable
here. Reused the recorded [Report workspace redesign handoff](../../research/sales-xray-ui-completeness-20260927/FOLLOWTHROUGH.md)
and [Prospect integration](prospect-report-integration.md): separate source,
observation and hypothesis; preserve source fidelity; reuse existing visual
primitives. No new cloud chat or paid provider was used. Screenshots and the
repeatable browser/scope receipts are uploaded to AUT-1000.

Later E8 steps stay on AUT-1000: remaining supported charts, phone-padding
reconciliation against AUT-1003 and final full-section staging captures.
