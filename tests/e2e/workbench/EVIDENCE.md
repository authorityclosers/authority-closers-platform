Workbench QA, AUT-1694 — 11 October 2026

Scope: the shared `dev/live` checkout, existing server on `127.0.0.1:3026`,
fictional review data. No product UI/API, database, credentials, deployment or
shipping changes. Browser checks run through `ac-heavy`; no server is started.

Implementation: 16 opt-in Playwright cases cover 1440/390 and light/dark. Report
checks follow Dipak's six sections, their required example blocks, eight skills,
progressive disclosure, saved URL, Document, DOCX bookmarks and return. Coaching
checks call/personal/team/sandbox views and all six personal-coaching pillars.
Visual receipts include overflow, loading, effective font size after transforms,
browser exceptions and server errors. The live-mode adapter uses existing product
routes and a private approved session supplied by the coordinator.

Static evidence: Ruff passes; all 16 cases collect. With no `WB_BASE_URL`, all
16 skip without contacting a live server. `uv run python -c "import ac_platform.http"`
passes. Ordinary CI remains independent of a live server.

Initial live-browser calibration reached all six Report sections at 1440/light
without browser exceptions, HTTP 500s or root overflow. Initial four-pair matrix:
6 passed / 10 failed. All four independent Document generation checks passed;
both phone Coaching journeys passed. Four dashboard failures are a missing
`/review-fixture/dashboard` (404), requested from the shell owner. Four Report
and two desktop Coaching failures exposed selector mistakes (a button changes its
name after expansion; headings include desktop-only counts); corrected before
the final focused run. These calibration failures are not product defects.

Screenshots were inspected at 1440/390 in light/dark. Product findings sent to
their owning INBOXes: final Deal section highlights Skills, fixture ReportHeader
says Untitled call, minute-pill label is 11.5px and joins the number on phones,
and fitted Document text is visually too small on phones. A missing populated
dashboard and lack of an approved authenticated session remain acceptance gaps.

External artifacts: `/home/acdev/strikes/1694/shots/2026-10-11-workbench/` and
the corrected run in `2026-10-11-workbench-final/`. Per-case JSON names match
journey/width/theme; screenshot names also identify the section. Strike NOTES
records final results and source pins. The observed source changed from
`27d679e0` to `13d5d694` while other builders worked; these are dev rendering
receipts, not production or authenticated-data acceptance.
