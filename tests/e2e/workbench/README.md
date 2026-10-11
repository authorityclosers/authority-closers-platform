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

The version 0.40 chunk covers Report, Document, DOCX and Coaching (12 cases).
Dashboard is outside this chunk, per the coordinator's 11 October scope order.
Its four cases remain available for a later populated, approved-session run by
omitting `-k 'not dashboard'`. `/review-fixture/dashboard` does not exist;
the retained dashboard journey requires a populated `WB_DASHBOARD_PATH` or live
mode. A missing fixture does not prove the protected product route is broken.

The other default routes are `/review-fixture/report/story`,
`/review-fixture/document`, `/review-fixture/coaching`. They contain labelled
fictional content and are development-only.

For coordinator-run staging smoke, set `WB_MODE=live`, `WB_BASE_URL` to the
approved staging origin, `WB_STORAGE_STATE` to an existing private Playwright
session file, and `WB_REPORT_PATH` to a retained populated report for that user.
Team requires a user with the existing team-read permission. Optional route
overrides are `WB_DASHBOARD_PATH`, `WB_COACHING_PATH`, `WB_TEAM_PATH`. No credentials
go into this directory, Git, commands or test output. Live mode uses real product
routes; it never tries to enable development-only fixtures on staging.

Screenshots and compact JSON receipts go outside Git via `WB_SHOTS_DIR` (default
`~/.cache/ac-workbench-qa`). Receipts omit cookies, request bodies and customer text.
Use a fresh output directory for each readback to preserve earlier evidence.
Navigation and Fast Refresh counts help identify live-edit interruptions;
console messages are never retained. Recheck an interrupted case before treating
it as a persistent product defect or claiming a complete PASS.
Coaching also follows both call and personal "See the mission" links, checks
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
