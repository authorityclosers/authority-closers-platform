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
Its standalone fictional source additionally checks repaired parts1.3/6.9 and
the Word file against the already-confirmed buyer-boundary excerpts; live
reports are never assumed to share those example words.
Rendered Document links/buttons must meet the 32 px desktop / 44 px phone floor.
Print-specific compact text is outside this screen-control check.

After a Report compatibility repair, run the bounded twelve-case readback:

```sh
WB_BASE_URL=http://127.0.0.1:3026 \
WB_SHOTS_DIR=/home/acdev/strikes/1694/shots/2026-10-12-report-compatibility \
LD_LIBRARY_PATH=/home/acdev/.local/lib/playwright-deps \
ac-heavy uv run pytest tests/e2e/workbench/test_workbench_journeys.py \
  -k 'report_sections_and_document or document_view or fixture_legacy_deal_action' \
  -q --tb=no -rN
```

The legacy fixture checks its saved next move after a full reload, in Document
part 6.9 and in the downloaded Word file's Recommended Deal Action. The separate
Document fixture retains its buyer-boundary action. These are fictional dev
checks; neither proves hosted access or canonical outcome persistence.

Coaching also reads all six fictional rep pillars with their own labels. Its
progress accessibility snapshot must contain one summary of the forty calls
(40 needed work in this fictional rep's data), rather than announcing
one list row per call. Every rep pillar gets a readability screenshot.
The font audit includes actual Coaching pillars in the standalone fixture and
requires a positive rendered-text count at every capture.
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
path they skip. The original sixteen plus four each for format, persistence,
quote, print, legacy-action, Team-search, Team-skill and supporting-moment checks,
plus eight focus-to-moment, eight call-search and four rep-call reset cases,
plus four Insights People, four Organisation People search and four Team
current-area cases, four Insights name-search and four Team missing-focus cases,
plus four each for summary clips, supplied shared dates and person-call search,
and four current-skill finding-filter cases, plus four skill-clip disclosure cases,
sixteen lesson/mission anchor cases, twelve call/retained-Report moment-anchor
cases, eight secondary-lesson disclosure cases and four controlled audio-startup
cases, plus four controlled native moment-end/replay and four narration shortcut
focus cases, sixteen interrupted-lesson resume and four Worked/Didn't clip disclosure
cases and four moment view-close cases, plus four phone mastery-name, four Report
clip-room, four call record-mark and four Team rep-record cases, collect 196 cases. The original Report
journey retains its full thirteen steps.
The separate dev-only `test_fixture_team_search_and_rep_calls` journey finds a
fictional rep outside the first eight, combines name/area filters, clears an
empty result and restores keyboard focus. It checks ready-call Report/coaching
destinations in the separate One rep fixture and follows See calls to expand
its history, filter it to the
saved current-skill records and return to All calls, with 32/44 px reachable
controls. Expanded Team and skill-history lists can be shortened again; the
journey checks keyboard focus, viewport return and the retained skill filter.
Fictional history links open Call coaching; its separate Report shortcut is
checked independently. Product call links are inspected without opening them;
this does not establish authenticated access to those calls.

```sh
WB_BASE_URL=http://127.0.0.1:3026 \
WB_SHOTS_DIR=/home/acdev/strikes/1694/shots/2026-10-12-team-search \
LD_LIBRARY_PATH=/home/acdev/.local/lib/playwright-deps \
ac-heavy uv run pytest tests/e2e/workbench/test_workbench_journeys.py \
  -k fixture_team_search_and_rep_calls -q --tb=no -rN
```

For the combined rep-link/disclosure and Deal mission-label repairs, select
`-k 'fixture_team_search_and_rep_calls or fixture_legacy_deal_action'` in the same
command. These eight cases also check the mission label's visible separation
and retain the saved next move across reload, Document and Word.

The additional dev-only long-quote journey verifies the exact fictional
1,232-character source once, its original time span, one expand/collapse click,
32/44 px reachable disclosure targets and no eager media in both widths/themes.
The separate dev print journey checks the native full-shell Document, six headings,
call facts and motionless hidden shell controls, saves A4 captures/PDFs and keeps
compact print typography outside the screen font/control audit.

After a supporting-moment repair, select `-k fixture_coaching_moment_fold` for
four focused cases. They check 2/1 compact desktop/phone moments, Show all/Show
fewer, restored list focus and retained source quotes, times and Call coaching
links. Reading these fictional moments requests no media; playback is not tested.

For the current-focus evidence link, select `-k fixture_coaching_focus_moments`.
Eight focused cases cover personal and fictional rep Coaching at both widths
and themes. Pointer and Enter activation must reach the original evidence,
focus its container and leave the next Tab inside that evidence. The first
source quote/time/call destination and 32/44 px reachable controls are checked.
No call destination, media playback or API mutation is invoked.

For the Team skill-summary action, select `-k fixture_team_skill_reps`.
Four cases exercise each Find reps action, preserve call suggestion counts,
check the exact current-focus names/routes and reset an expanded rep list.
Enter activation clears a conflicting name/area filter and brings keyboard
focus back to Find a rep. The same four cases then open One rep and check the
committed progress action, See calls on this skill. Pointer/Enter must select
the saved-record call filter, shorten an expanded history, focus its list and
preserve source call names/routes. No product destination is opened.

For the new saved-call name search, select `-k fixture_coaching_call_search`.
Eight cases cover personal/fictional rep histories at both widths/themes. A
trimmed mixed-case name finds the retained call, collapses expanded history
and combines with On this skill without changing source states or routes.
No matching calls and Clear search retain the skill filter; pointer/Enter
restore search focus. The progress shortcut clears a conflicting search and
lands on saved skill calls, with the next Tab in Find a call. The personal
fixture also checks that its pending call retains Analysing and its original
route, and remains excluded from saved skill calls. Controls meet 32/44 px.
No product call destination or API mutation is invoked.

For the rep's See calls shortcut repair, select `-k fixture_rep_calls_reset`.
Four cases deliberately expand history, select a skill and search for a missing
call. Pointer/Enter on See calls must restore All calls, clear search, fold the
list and focus its section, with the next Tab reaching Find a call. All source
call names/routes and the native hash/query are retained. These fictional
checks open no product call destination and invoke no API mutation.

For the coordinator-requested Insights People disclosure, select
`-k fixture_insights_people`. Four focused cases reuse G's existing fictional
65-person API harness on shared dev3026, with a fresh browser and every
non-read API request blocked. They preserve returned order, reach person65,
collapse to50 with focus recovery and check the selected source key in the
Person control, address and API read. This is fictional UI evidence; it creates
no account/session or data and establishes no authenticated hosted acceptance.

For A's Organisation name search and D's current-focus area picker, select
`-k 'fixture_organisation_people_search or fixture_team_current_areas'`.
Eight focused cases reuse the existing fictional read-only six-person and
current-focus examples. Organisation covers same-name active/quiet identities,
folded test names, names-only empty state and clear/focus/disclosure with unchanged
figures/routes. Team covers the existing Delivery reps absent from historical
totals, combined name filtering and reset/focus with unchanged historic counters.
All API writes are refused; no profile/call destination is opened.

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
`-k 'test_report_sections_and_document or test_document_view or test_coaching_pages'`. Clear the optional
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

For returned-name search and missing-focus changes, use
`-k 'fixture_insights_people_search or fixture_team_missing_focus'` only.
Insights searches the existing65-person fictional source, with source55 and65
sharing a display name while retaining distinct keys; it checks both selections,
all matching rows, figures, no local reads and both prior disclosure states.
Team uses the existing no-focus-reps example and retains source call dates,
counts, routes and historical totals. Its source supplies no shared dates or
absent latest dates; those browser edges require an explicit separate source.
These remain fictional read-only UI checks.

For the next completed summary/person-call/date changes, select only
`-k 'fixture_summary_clips or fixture_person_call_search or fixture_team_shared_dates'`.
Summary uses B's native/Revised/Older fictional reports and checks source times,
quotes, unchanged prose, pointer/Enter/Space,32–44px and no eager media or writes.
Duplicate-ref and different-summary browser cases are not supplied; builder unit
evidence remains separate. Person call search reuses A's twelve returned calls,
including duplicate names, queued status, an unnamed call and a Devanagari tail,
with partial-source scope and prior8/all disclosure. The date check uses D's
existing Design review Team, retaining distinct supplied call/share dates;
missing latest-date browser coverage remains unexecuted. No authenticated
hosted, real audio/provider or data-write claim follows from these examples.

For the saved-finding selector, choose only `-k fixture_coaching_call_findings`.
The existing fictional personal example supplies six ready calls on the skill:
four Needed work and two Skill used, nothing to fix. The check preserves original
names/order/IDs/Report routes, excludes pending/no-opportunity calls, intersects
name search, preserves the selected finding on Clear search and resets it through
All calls or the progress shortcut, including focus and32–44px targets.
No destination, mutation, authenticated read or AI-scoring claim is made.

After B returns its completed skill-disclosure source, select only
`-k fixture_skill_clip_disclosure`. It reuses B's browser-only fictional native
Report prop setup: five/six repeated original refs, zero refs and four refs.
Four/all counts, literal source order, independent skills, fold focus, original
selection times,32–44px and no eager media/extra reads/writes are checked.
This explicitly altered fictional input is not a customer Report or native
loaded-DB acceptance; no new fixture route or persisted data is created.

For the new lesson shortcut, select only `-k fixture_coaching_focus_lesson`.
Four existing fictional surfaces (personal, rep, call and rep-call) check
See the lesson/mission with pointer and Enter, exact target/hash/query/focus,
next Tab inside the folded lesson, unchanged source content, one-row32–44px
controls and no media/source reads or API writes. These16cases do not prove
canonical Report integration or authenticated lesson/sharing access.

For the call-to-moments shortcut, select only `-k fixture_call_focus_moments`.
Its three existing fictional surfaces retain original quotes/times/mission/query,
check32–44px and pointer/Enter target focus, require an actual heading hit below
sticky navigation and next Tab inside, with no media/source reads or writes.
The retained Report example is authored UI evidence; canonical Report bootstrap
and authenticated acceptance remain separate.

For the new secondary-lesson fold, select only
`-k fixture_coaching_secondary_lessons`. Its existing personal/fictional-rep
sources preserve recommended and secondary titles/reasons/takeaways/transcript,
access/preview labels and mission/query. Native pointer/Enter/nested disclosure
independence, focus/next Tab and40–44px summary targets are checked without
playback/source reads or writes. Audio-request/reveal and scoped fold-pause
remain separate mocked unit evidence, as does authenticated acceptance.

For the new stalled-audio recovery, select only
`-k fixture_coaching_audio_startup`. Four cases use the existing local Design
review at3026 and freeze the browser clock before interaction. The moment and
recommended narration requests stay intercepted until their15-second deadline;
keyboard retry receives an intercepted404 for that same source. A third stalled
attempt checks loading activation stays inert, keeps keyboard focus, and leaves
focus on another existing control when the user moves it before timeout. Original quote,
times, lesson/access/transcript, mission/query and32–44px retry targets remain
checked. No source request reaches a server or provider. Real playback, preview
limits, late play promises, switch/unmount cleanup and authenticated acceptance
remain outside this browser check; the builder's mocked unit coverage is separate.

For the new early recording-end behavior, select only
`-k fixture_coaching_moment_ended`. Four cases reuse the authored Design review
moment and D's short silent WAV as an in-memory, byte-range browser response.
Native muted playback ends before the saved excerpt's end; the existing Play
control must return, Enter must replay its original timestamp, and pointer Pause
must stop it. Source quote/time/call link/mission/query and32–44px targets remain
checked. This exercises native browser playback of silence only; no real recording,
provider, authenticated read or API write occurs.

For the new “Hear Dipak’s take” focus behavior, select only
`-k fixture_coaching_hear_lesson_focus`. Four cases check pointer and Enter on the
existing Design review shortcut: the recommended playback button receives focus,
is stationary/reachable at40–44px, and next Tab stays inside its card. Return an
intercepted404 only after that focus moves; the error must leave focus alone.
The source must still be loading through capture before that404 is returned.
Original quote/lesson/access/transcript/mission/query remain unchanged. No real
audio, provider, authenticated read or write is used.

For the new interruption resume, select only
`-k 'fixture_coaching_interrupted_lesson_resume and (moment or fold)'`. Eight cases reuse the existing
recommended/secondary Design review clips and D's native muted70-second silent
WAV response. A call moment or secondary fold interrupts before the first device
checkpoint; its saved window offset must equal the native paused time. Reload must
request no audio; Enter must resume that same source at the exact saved position
with focus/32–44px targets and original access/text/mission/query. The call source
receives an intercepted404. Only the isolated browser's device position changes;
no canonical progress, provider, real recording, authenticated read or API write.

For the separate direct Pause/view-close return, select only
`-k 'fixture_coaching_interrupted_lesson_resume and (pause or viewclose)'`. These
eight new cases use the same local silent source and exact native/device offset,
reload/Enter/focus/access guards. View-close also checks the detached player is
paused and stationary, with no eager media on return. Earlier switch/fold results
remain retained; do not rerun them for this new criterion.

For the new moment view-close behavior, select only
`-k fixture_coaching_moment_view_close`. Four width/theme cases check both native
silent playback and a held source: leaving detaches/pauses the old element, its
position stays stationary, and return fetches no audio. Enter replays the playing
case from its original timestamp with focus/32–44px; the held case cannot start
playing after a late local delivery attempt. Quote/call/mission/query remain.
Unresolved play promises stay unit-only; no real recording/provider/hosted claim.

For the new Worked/Didn't clip controls, select only
`-k fixture_worked_clip_disclosure`. Four cases reuse B's exact browser-only
boundary: each existing fictional card repeats its own original source ref for
0/1/2/3/4-ref counts. Check first two/all/fewer, independent cards, pointer/Enter/
Space selection of original displayed bounds/title, fold focus, unchanged six
findings/prose and32–44px controls, with no added API/media/write. Mixed source
order and original object identity stay unit-only; canonical payloads are untouched.

For labelled Report clip chips ("18:42 · Play"), select only
`-k fixture_report_clip_pause_room`. Four cases open the authored fictional
Report and, in Worked/Didn't, Moments That Mattered and the first opened Skills
row, swap the chip's word to Pause in the browser only (restored at once) and
require zero movement of the chip, its time, its row and any neighbour, with the
Pause text fitting the reserved width. The chip's real pointer area, including its
`::after`, must reach 32 px desktop / 44 px phone with the centre reachable. The
fixture never starts a clip, so the live Pause state during playback stays
unit-only; no media, reads or writes are added by the checks.

For each call's saved record on the current focus, select only
`-k fixture_coaching_call_record_marks`. Four width/theme cases open the signed-out
Design review and AC Sandbox My coaching views, press All calls (Show all first
where present) and compare every row against the fixture: a ready call with a
saved `suggested` or `no_suggestion` record carries "Needed work" or "Skill used,
nothing to fix" right after its own focus and before "Also on other calls", with a
10 px dot whose fill, ring and style equal pillar 5's legend for the same state.
Pending calls and calls without a saved record show no mark and no record words;
Design review marks 6 of 8 rows, Sandbox every ready row. "On this skill" shows
no marks (its filter keeps its own words) and All calls restores them. Report
links `/analysis/calls/<id>` and row targets are unchanged; no reads, writes or
media are added. The no-current-focus view stays unit-only.

For each rep's saved record on their current focus in Team, select only
`-k fixture_team_rep_records`. Four width/theme cases read pillar 5's legend on
the signed-out Sandbox My coaching view, then open the Sandbox Team view and
compare the first eight rows and, after "Show all 60 people", every row against
the fixture: name, focus and `/coaching?person=<id>` route unchanged, exactly one
record mark reading "Needed work in N of M calls" (or "Nothing to fix in M calls")
right after the focus and before "N calls" and "Latest call", on one line inside
its row, with a 10 px dot whose fill, ring and style equal the legend for the same
state. The Design review's shared reps, whose older records carry no counts, show
no mark and no record words. Row targets, clipping, reads, writes and refreshes
are checked as usual. The fixture holds only "Needed work" records, so "Nothing
to fix" stays unit-only.

For pillar 1's "Latest call with coaching" shortcut, select only
`-k fixture_coaching_latest_call_shortcut`. Eight cases (Design review My coaching
"Your latest call" and AC Sandbox One rep "This rep’s calls", 1440/390 light/dark)
find the one navigation inside `#coaching-focus` before "Why this matters", and
check it names the fixture's newest ready call with its date; its three links are
Open Report `/analysis/calls/<id>`, Call coaching `/coaching?call=<id>` and See
calls `#coaching-calls`, where `<id>` is that call's own row in "Coaching for each
call". The record mark is present exactly when that row carries one, with the
same words and a 10 px dot equal to pillar 5's legend (Design review's latest
call has no saved record; Sandbox shows "Needed work"). Links meet 32/44 px with
reachable centres; See calls focuses the call list on All calls, folded as usual. Reads,
writes, clipping, overflow and refreshes are checked as usual. Fixture-only.
