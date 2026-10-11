Workbench QA, AUT-1694 — 11 October 2026

Scope: shared `dev/live`, existing server `127.0.0.1:3026`, labelled fictional
review data. Changes are only browser tests and their documentation. Browsers
use `ac-heavy`; no server, provider request, database change or shipping action.

The 16 opt-in cases cover 1440/390, light/dark, dashboard-to-report, all six
Report sections in Dipak's order, their required example blocks, eight skills,
progressive disclosure, reload, Document, six DOCX bookmarks and return. Coaching
covers This call, all six personal pillars, Team, AC Sandbox and a named rep.
The same journeys support coordinator-run staging smoke with existing product
routes and a private approved session. They never create a session or account.

Continuation at 15:54 UTC: a fresh 12-case dev batch started at `f35f2bf7`, with
uncommitted Report/Document edits and live refreshes. Desktop/light Report passed
all nine steps. Desktop/dark completed six pillars, then failed before Document
capture during six refresh notices; its failure image is a blank dark viewport.
The batch subsequently ended 143 before pytest's summary, its end-SHA line and
the remaining ten cases. Runtime/server/visual error lists are empty in both
receipts. This incomplete batch cannot replace the prior completed four-pair
acceptance below or certify the newer dev changes. Exact capture and safe run
log are in `2026-10-11-workbench-mission-readback/`. Report and backend owners
received the observations; a bounded repeat is pending at the 15-minute interval.

`3a47bf6a` adds real call/personal mission-link taps, center reachability and
32 px desktop / 44 px phone target checks. Browser acceptance of these new checks
is pending because the interrupted batch did not reach Coaching. Failure
receipts now preserve exception type and the journey's check/line, excluding
exception/customer text, even if pytest's batch summary is interrupted.

Coordinator supplied existing private session references at 15:43 UTC; the
session file is not Playwright storage-state JSON (format checked, no values
printed). Populated staging smoke still needs a compatible approved session
reference/format contract, retained Report route, existing Team-read permission
and confirmed staging version. Coordinator's second staging attempt is running;
QA has performed no staging writes, new sign-in/account/access grants or deploy.

Latest completed checks:

| Journey | Result | Evidence / remaining owner |
| --- | --- | --- |
| Populated dashboard | Not in scope for v0.40 | Coordinator's 14:26 UTC order excludes it. Four retained cases need a populated route/session; the missing review fixture does not prove a protected-route defect. |
| Report → Document → DOCX → Report | PASS, 4/4 | Fresh nine-step run includes open actions, six sections, eight skills, reload, valid six-bookmark Word file and return; no browser errors/HTTP 500s/root overflow. |
| Report visual floor | PASS, 4/4 | Open `.docx` label clears 12px after `7081f2f6` + `a55cec67`; no undersized visible text in any captured step. Minute spacing is fixed in `e2b27225`. |
| Phone Report actions | PASS | Copy link center-point is pointer-reachable in all four pairs. Inspected phone/light and desktop/dark menus are fully visible; the toolbar overlap is resolved. |
| Standalone Document | PASS, 4/4 | Native document has six sections and readable text at both widths/themes. |
| Coaching | PASS across four pairs | Three current pairs pass all 11 steps; the bounded 390/light repeat also passes all 11 at recorded HEAD `7058bd8f`. No runtime/server errors, visual faults or autoplay. The earlier phone view reset did not reproduce. |

Source changed from `27d679e0` through `807b3fa8` while builders edited the live
checkout. These are rendering receipts, not immutable release or authenticated
API acceptance. Latest native Document fixes supersede the original page crash
and phone fit-to-width readability finding. Report title and final-section
highlight are also corrected in inspected screenshots. Earlier selectors were
adapted to the renamed controls, personalized labels, compact phone Word action
and More views menu. The fresh passing four-case run's source range is `b3d40eb8`
to `807b3fa8`; all nine observations complete per pair. Earlier records attributed
an unclassed SMALL element to the minute pill and counted closed-menu layout
bounds as visible; those findings are superseded. The journey now opens More
report actions for its font screenshot and excludes closed native-details
content. The explicit 11.5px rule is in A's `acquisition-studio.module.css`;
B's first font class did not win that cascade; the subsequent A/B fixes are
independently verified. Closed-menu, font and phone-overlap failures are superseded.
The top bar now correctly says Report in the inspected screenshots.

After B replaced the example data with Dipak's exact scenario (`c195f4cb`),
another focused Report run passes all four pairs and all nine steps at unchanged
recorded start/end HEAD `c195f4cb`. Menu reachability, six sections/eight skills,
reload, Document, valid six-bookmark Word file and return all pass; no browser,
server or visual errors. Latest phone overview was inspected. Live API readiness
returns HTTP 200; the backend deploy log was checked without printing raw lines.

The font audit checks native element visibility, text ranges and ancestor
transform scaling. A read-only center-point hit test checks the open menu's
Copy link action without changing the clipboard or invoking a download.
Decorative aria-hidden avatar initials with a separate full name do not count
as readable labels. Receipts omit cookies, request bodies and customer text.
No traces or storage-state files are produced.

Ruff passes, all 16 cases collect, and the no-server invocation skips all 16
without contacting a live server. The required `uv run python -c
"import ac_platform.http"` check passes. Report/Document/DOCX rendering is green.
Coaching's source-changing batch (`4b058a59` to `56ea01c6`) passed three pairs;
its phone/light repeat passed at unchanged recorded HEAD `7058bd8f`. The repeat
records two navigations and two Fast Refresh notices, showing that unchanged Git
HEAD does not mean a refresh-free live checkout. All 11 checks still completed.
The original view reset's cause remains unconfirmed. Receipts retain only counts,
never console text. Combined dev rendering checks are green; no immutable release
or authenticated staging verdict is implied. Staging awaits the coordinator's
version confirmation, approved session-file path and populated Report route.

External screenshots/JSON: `/home/acdev/strikes/1694/shots/`:
- `2026-10-11-workbench-verified/`: all four Coaching and Document passes.
- `2026-10-11-workbench-report-final/`: all eight connected Report steps per pair.
- `2026-10-11-workbench-1400/`: complete 16-case matrix, before final selector calibration.
- `2026-10-11-workbench-final-check/`: final phone run with More views, compact
  Word label and all eight completed steps; font failure recorded above.
- `2026-10-11-workbench-menu-audit/`: latest four-pair, nine-step Report run;
  earlier open-menu failure screenshots and source-pinned receipts.
- `2026-10-11-workbench-fixed-report/`: fresh four-pair PASS, pointer reachability,
  all nine observations and start/end source pins.
- `2026-10-11-workbench-current-coaching/`: three current passes and the
  phone/light view-selection interruption; no persistent defect conclusion yet.
- `2026-10-11-workbench-coaching-repeat/`: 390/light PASS, all 11 steps;
  navigation/refresh counts and unchanged recorded start/end HEAD.
- `2026-10-11-workbench-dipak-example/`: final exact-example Report PASS, four
  pairs/all nine steps, at recorded HEAD `c195f4cb`.

Strike NOTES records current verdicts, commits and exact owning INBOX handoffs.
Two queued checks ended 143; those incomplete runs do not establish acceptance.
