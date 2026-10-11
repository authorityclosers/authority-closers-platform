These opt-in Playwright journeys use an already running shared server. They do
not start a server, create accounts, seed a database, call providers, deploy,
send learner feedback or change sharing/billing. Run under the shared heavy slot.

```sh
WB_BASE_URL=http://127.0.0.1:3026 \
WB_SHOTS_DIR=/home/acdev/strikes/1694/shots/2026-10-11-workbench \
LD_LIBRARY_PATH=/home/acdev/.local/lib/playwright-deps \
ac-heavy uv run pytest tests/e2e/workbench/test_workbench_journeys.py \
  -k 'not dashboard' -q --tb=short
```

Without `WB_BASE_URL` all browser cases skip, so ordinary test collection does
not contact a live server. There are four viewport/theme pairs: 1440/light,
1440/dark, 390/light and 390/dark. Each checks dashboard-to-report, six report
sections in Dipak's order, reload/Document/valid DOCX/return, independent Document,
and call/personal/team/sandbox Coaching. The current More views menu is opened
before selecting Document; older direct view controls also work. A sign-in or
empty dashboard is a failure.
The eight skill rows follow Dipak's order. "Explore deeper analysis" starts
collapsed; the populated example opens all four groups and captures each one.
Live calls are checked only for deeper groups actually supplied by their report.
The independent Document journey checks six actual sections in order and
captures each section's content at both widths/themes, alongside its top sheet.
Rendered Document links/buttons must meet the 32 px desktop / 44 px phone floor.
Print-specific compact text is outside this screen-control check.

Coaching also reads all six fictional rep pillars with their own labels. Its
progress accessibility snapshot must contain one summary of the forty calls
(40 needed work in this fictional rep's data), rather than announcing
one list row per call. Every rep pillar gets a readability screenshot.
Team totals also check that rendered text fits its clipping containers; DOM
visibility alone cannot pass an ellipsised count or context line. The sandbox's
latest-call footnote must fit fully in view and gets its own screenshot.

The separate fictional formatting journey checks Won, Lost with a required reason, Follow-up Set
with a required date, Decision Pending (the no-decision choice), and optional
deal value. It checks human attribution, Deal status, Document and the Word
file's 1.1 Call Outcome. Fixture outcome API requests are blocked and counted;
the in-memory fixture deliberately resets on reload. Its receipt identifies
format agreement and explicitly says canonical reload is unverified.
The ordinary live-mode Report/Document/Coaching journeys are read-only.

Required-field corner cards must clear the phone's bottom navigation and leave
every navigation target reachable. Document and Word retain the same eight
short skill names/order as the Report and Dipak's sheet.

Four additional cases, `test_fictional_outcome_persistence`, require `WB_MODE=live`,
an existing approved dev session and `WB_OUTCOME_WRITE_PATH` naming an explicitly
fictional finished call owned by that account. They save through the real control,
fully reload each choice, check Report/Document/Word and read the saved API value
and increasing revision. They refuse staging origins. No fixture storage or
React-state result substitutes for this evidence. Without the explicit write
path they skip. These eight optional cases plus the original sixteen collect
28 cases. The original Report journey retains its full thirteen steps.
The additional dev-only long-quote journey verifies the exact fictional
1,232-character source once, its original time span, one expand/collapse click,
32/44 px reachable disclosure targets and no eager media in both widths/themes.

The version 0.40 chunk covers Report, Document, DOCX and Coaching (12 cases).
Dashboard is outside this chunk, per the coordinator's 11 October scope order.
Its four cases remain available for a later populated, approved-session run by
omitting the Dashboard filter. `/review-fixture/dashboard` does not exist;
the retained dashboard journey requires a populated `WB_DASHBOARD_PATH` or live
mode. A missing fixture does not prove the protected product route is broken.

The other default routes are `/review-fixture/report/story`,
`/review-fixture/document`, `/review-fixture/coaching`. They contain labelled
fictional content and are development-only.

For coordinator-run staging smoke, set `WB_MODE=live`, `WB_BASE_URL` to the
approved staging origin, `WB_STORAGE_STATE` to an existing private Playwright
session file, and `WB_REPORT_PATH` to a retained populated report for that user.
`WB_STORAGE_STATE` accepts Playwright JSON or a standard Netscape cookie jar.
The jar is loaded into the browser in memory with its existing domain/path,
expiry, secure and HttpOnly flags; expired cookies and a different host fail.
No new session or converted credential file is created.
Team requires a user with the existing team-read permission. Optional route
overrides are `WB_DASHBOARD_PATH`, `WB_COACHING_PATH`, `WB_TEAM_PATH`. No credentials
go into this directory, Git, commands or test output. Live mode uses real product
routes; it never tries to enable development-only fixtures on staging.
For live runs use `--tb=no -rN`; Playwright failure messages can quote page text.
Use the receipt's safe exception type and check/line for the failure handoff.
The read-only twelve-case staging selection is
`-k 'not dashboard and not fictional_outcome_persistence and not fixture_outcome_formats and not fixture_coaching_quote_fold'`. Clear the optional
write path when running smoke; no outcome mutation is part of staging acceptance.

The coordinator-approved local deployed transport is opt-in:
`WB_LOCAL_TRANSPORT=http://127.0.0.1:8080`, with live mode and the original
staging or production HTTPS `WB_BASE_URL`. It preserves that browser origin,
Host and existing cookie scope in memory, fetches through foundation :8080,
and leaves redirects to Chromium. Other origins/ports and fixture mode refuse.
Non-read methods abort before reaching the app and fail the read-only journey.
Receipts label the local transport; this does not establish public Cloudflare
access. It cannot replace an admitted, populated Report/Team context. Do not
run populated smoke against a rejected session or an empty/unpermitted context.

Screenshots and compact JSON receipts go outside Git via `WB_SHOTS_DIR` (default
`~/.cache/ac-workbench-qa`). Receipts omit cookies, request bodies and customer text.
Use a fresh output directory for each readback to preserve earlier evidence.
Navigation and Fast Refresh counts help identify live-edit interruptions;
console messages are never retained. Recheck an interrupted case before treating
it as a persistent product defect or claiming a complete PASS.
Refresh receipts retain only a fixed phase (rebuilding/done/other) and timestamp;
the single Coaching click has a comparable timestamp. No console text is saved.
Failure receipts retain exception type and the journey's check/line, without
exception text, so an interrupted batch still has a useful failure location.
Coaching verifies that My coaching is selected after its single click before
checking the personal pillars. Fixture receipts retain that click's fixed control
identifier, coordinates, selected states and view parameter to diagnose a lost
switch, without retrying or retaining page text. It also follows both call and personal "See the mission" links, checks
that their targets are at least 32 px on desktop / 44 px on phones and reachable
at the center, and verifies that the mission heading comes into view. Target
dimensions are retained in the receipt; no learner feedback is saved.
No traces or storage-state files are generated. Read the screenshots yourself;
font floors, menu pointer reachability, root overflow, cleared loading state,
browser exceptions and HTTP
500s cannot establish visual quality alone. Document pages intentionally remain
paper-coloured in both application themes.

Run after builders' commits, at most every 15 minutes. Record the source SHA,
receipts, remaining gaps and screenshot findings in strike NOTES, and append
exact defects to the owning strike's INBOX. The coordinator owns any staging
run or shipping. These journeys never promote a version themselves.
