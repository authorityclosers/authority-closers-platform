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

Latest completed checks:

| Journey | Result | Evidence / remaining owner |
| --- | --- | --- |
| Populated dashboard | Not in scope for v0.40 | Coordinator's 14:26 UTC order excludes it. Four retained cases need a populated route/session; the missing review fixture does not prove a protected-route defect. |
| Report → Document → DOCX → Report | Functional checks pass, 4/4 | Latest nine-step run includes open actions, six sections, eight skills, reload, valid six-bookmark Word file and return; no browser errors/HTTP 500s/root overflow. |
| Report visual floor | FAIL, A/1663 CSS + B/1677 header | Open actions menu's `.docx` label is 11.5px in all four pairs. A's studio selector overrides B's `bfbf7048` font class. Minute spacing is fixed in `e2b27225`. |
| Phone Report actions | FAIL, A/B | Inspected 390/light and 390/dark screenshots show the fixed toolbar/nav covering Download report/Copy link rows. The desktop menu is fully visible. Read-only pointer reachability is added for the next run. |
| Standalone Document | PASS, 4/4 | Native document has six sections and readable text at both widths/themes. |
| Coaching | PASS, 4/4 | Call/personal/team/sandbox; one focus/mission, explicit done-when, no autoplay, overflow, 500s or browser errors. |

Source changed from `27d679e0` through `127d111a` while builders edited the live
checkout. These are rendering receipts, not immutable release or authenticated
API acceptance. Latest native Document fixes supersede the original page crash
and phone fit-to-width readability finding. Report title and final-section
highlight are also corrected in inspected screenshots. Earlier selectors were
adapted to the renamed controls, personalized labels, compact phone Word action
and More views menu. The latest four-case run's source range is `f91f5f81` to
`127d111a`; all nine observations complete per pair. Earlier records attributed
an unclassed SMALL element to the minute pill and counted closed-menu layout
bounds as visible; those findings are superseded. The journey now opens More
report actions for its font screenshot and excludes closed native-details
content. The explicit 11.5px rule is in A's `acquisition-studio.module.css`;
B's `report-header.module.css` class does not win that cascade.

The font audit checks native element visibility, text ranges and ancestor
transform scaling. A read-only center-point hit test checks the open menu's
Copy link action without changing the clipboard or invoking a download.
Decorative aria-hidden avatar initials with a separate full name do not count
as readable labels. Receipts omit cookies, request bodies and customer text.
No traces or storage-state files are produced.

Ruff passes, all 16 cases collect, and the no-server invocation skips all 16
without contacting a live server. The required `uv run python -c
"import ac_platform.http"` check passes. The v0.40 visual verdict awaits the
font cascade/menu overlap repairs and their focused readback. No authenticated browser
session has been supplied to this QA session.

External screenshots/JSON: `/home/acdev/strikes/1694/shots/`:
- `2026-10-11-workbench-verified/`: all four Coaching and Document passes.
- `2026-10-11-workbench-report-final/`: all eight connected Report steps per pair.
- `2026-10-11-workbench-1400/`: complete 16-case matrix, before final selector calibration.
- `2026-10-11-workbench-final-check/`: final phone run with More views, compact
  Word label and all eight completed steps; font failure recorded above.
- `2026-10-11-workbench-menu-audit/`: latest four-pair, nine-step Report run;
  explicit open-menu screenshots, JSON receipts and start/end source pins.

Strike NOTES records current verdicts, commits and exact owning INBOX handoffs.
Two queued checks ended 143; those incomplete runs do not establish acceptance.
