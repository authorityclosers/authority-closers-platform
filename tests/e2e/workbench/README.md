These opt-in Playwright journeys use an already running shared server. They do
not start a server, create accounts, seed a database, call providers, deploy,
send learner feedback or change sharing/billing. Run under the shared heavy slot.

```sh
WB_BASE_URL=http://127.0.0.1:3026 \
WB_SHOTS_DIR=/home/acdev/strikes/1694/shots/2026-10-11-workbench \
LD_LIBRARY_PATH=/home/acdev/.local/lib/playwright-deps \
ac-heavy uv run pytest tests/e2e/workbench/test_workbench_journeys.py -q --tb=short
```

Without `WB_BASE_URL` all browser cases skip, so ordinary test collection does
not contact a live server. There are four viewport/theme pairs: 1440/light,
1440/dark, 390/light and 390/dark. Each checks dashboard-to-report, six report
sections in Dipak's order, reload/Document/valid DOCX/return, independent Document,
and call/personal/team/sandbox Coaching. A sign-in or empty dashboard is a failure.

Default routes are `/review-fixture/dashboard`, `/review-fixture/report/story`,
`/review-fixture/document`, `/review-fixture/coaching`. These contain labelled
fictional content and are development-only. A missing fixture is an acceptance
gap, not proof that the protected product route is broken.

For coordinator-run staging smoke, set `WB_MODE=live`, `WB_BASE_URL` to the
approved staging origin, `WB_STORAGE_STATE` to an existing private Playwright
session file, and `WB_REPORT_PATH` to a retained populated report for that user.
Team requires a user with the existing team-read permission. Optional route
overrides are `WB_DASHBOARD_PATH`, `WB_COACHING_PATH`, `WB_TEAM_PATH`. No credentials
go into this directory, Git, commands or test output. Live mode uses real product
routes; it never tries to enable development-only fixtures on staging.

Screenshots and compact JSON receipts go outside Git via `WB_SHOTS_DIR` (default
`~/.cache/ac-workbench-qa`). Receipts omit cookies, request bodies and customer text.
No traces or storage-state files are generated. Read the screenshots yourself;
font floors, root overflow, cleared loading state, browser exceptions and HTTP
500s cannot establish visual quality alone. Document pages intentionally remain
paper-coloured in both application themes.

Run after builders' commits, at most every 15 minutes. Record the source SHA,
receipts, remaining gaps and screenshot findings in strike NOTES, and append
exact defects to the owning strike's INBOX. The coordinator owns any staging
run or shipping. These journeys never promote a version themselves.
