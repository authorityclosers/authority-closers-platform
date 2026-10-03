# Sales Xray visual advisory (D2 A)

AUT-1016 implements the [AUT-1008 CTO brief](/AUT/issues/AUT-1008#document-brief),
revision `6caf749e-c869-4871-bdcc-7672475468ba`. All visual differences and browser
counts are advisory. This workflow has no automatic date-based blocking switch,
release mutation, required-check change, PR comment write or deployment action.
UI Guard owns the visual verdict. The workflow requires CTO review, CEO merge
approval and watchdog merge.

The dedicated `sales-xray-visual.yml` runs on each PR, each main push and manual
dispatch. PRs select changed Sales Xray component families plus the shell; main
and dispatch render the complete fictional catalogue to supply baselines. Broad
or unfamiliar Sales Xray/UI component changes select the complete catalogue.
Backend-only PRs render the shell. Tests alone do not expand the selection.
The catalogue reuses the repository's development-only shell/report/document,
plans/billing and acquisition fixtures. Those are display evidence, with no
canonical account, payment, call or provider operation. This is not D2 B's real
staging journey proof. Screens without a fictional state need a catalogue
extension; the complete catalogue is conservative component coverage, not proof
of every authenticated route or feature state.

The renderer launches a temporary Next development process on `127.0.0.1:18216`,
with a 1024 MiB JavaScript heap limit, no configured upstream API, and an explicit
environment allow-list. A fresh, nonpersistent Chromium context per capture has
no cookies or sign-in state. Browser requests allow only GETs for the selected
fictional routes and local static assets. APIs, review-observation APIs, external
hosts, writes, WebSockets, service workers and downloads are refused. No env
files, database, provider SDK, real audio or host service is needed.

Playwright is exactly `1.58.2` from the frozen Node lockfile. Axe is the already
locked `4.13.0` transitive dependency of the Next accessibility lint package;
Pillow is the existing Python pin `12.3.0`. There is no new dependency/lockfile.
Date is fixed to `2026-10-03T12:00:00Z`, with UTC, en-GB, light theme, reduced
motion, disabled CSS animation/transition/caret, local fonts and network-idle
navigation. Each capture is bounded; the renderer has a four-minute deadline.
The job has an eight-minute safety timeout, with a target below six minutes.
`elapsed_seconds` measures rendering separately from Actions setup/run times.
Compare hosted Actions duration before claiming the target is met.

Baselines are the most recent successful main **push** visual run whose exact SHA
also has successful main **push** Application validation. The current visual run
is excluded. Search is bounded to 30 successful runs of each workflow. Missing,
expired, unreadable, unmatched or absent screenshots are **unavailable**, never a
zero difference. The first main run intentionally has no baseline. No baseline
image is checked into Git. The read-only Actions token is scoped to the baseline
step and is not passed to Next or written into artifacts.

Baseline archives are size bounded and reject duplicate names, path traversal,
symlinks, wrong SHA and wrong image dimensions. Only fixed-viewport PNGs named in
measured receipt rows are decoded and re-encoded. Downloaded scripts/HTML/traces
are never executed or republished. Pixel differences count pixels whose maximum
RGB channel change exceeds 20, with a pink overlay; this threshold is advisory.

The artifact `sales-xray-visual-<source-sha>-<attempt>` expires after **three days**.
It contains only `receipt.json`, `report.md`, the contact sheet and fixed-viewport
screenshots/diffs. Actions summary links the artifact; Markdown links in its
report resolve after download. Console text, exception text, axe DOM excerpts,
request/response bodies, browser storage, cookies, traces, videos and server logs
are not stored. Report receipts contain counts, fixed fixture routes and safe
failure-stage labels, rather than raw diagnostics.

`receipt.json` uses schema `ac-sales-xray-visual/1`:

| Field                                                    | Meaning                                                                                                                 |
| -------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------- |
| `source_sha`, `run_id`                                   | Exact tested checkout and Actions run; local runs have a null run ID                                                    |
| `advisory`                                               | Always true in A                                                                                                        |
| `playwright_version`, `browser_version`, `axe_version`   | Tool versions actually loaded                                                                                           |
| `renderer_status`, `elapsed_seconds`                     | Measured, partial or unavailable; actual render duration                                                                |
| `baseline.status`, `run_id`, `source_sha`                | Availability and provenance of last eligible green-main artifact                                                        |
| `rows[].id`, `route`, `state`, `viewport`                | Fixture state at 1440×900 or 390×844                                                                                    |
| `rows[].screenshot`                                      | Relative screenshot link, or null                                                                                       |
| `rows[].overflow_px`, `overflow_count`                   | Root horizontal scroll excess and visible outlying element count; clipped internal panels do not count as page overflow |
| `rows[].console_error_count`, `uncaught_exception_count` | Observed error events, including browser/harness-generated errors                                                       |
| `rows[].axe_critical_count`, `axe_incomplete_count`      | Number of critical violation rules and incomplete rules; zero critical does not mean a full accessibility pass          |
| `rows[].diff.status`, `changed_pixels`, `ratio`, `image` | Available pixel difference and relative overlay link, or null measurements                                              |
| `contact_sheet`                                          | Relative contact sheet link                                                                                             |

Unavailable captures retain null counts. Failed axe measurements retain a null
critical count even if the screenshot succeeds. Setup failure produces an
explicit unavailable receipt with no inferred rows. Consumers in D2 B must keep
these unavailable values; they must not coerce null/missing into zero or green.

Local verification (no host service or credentials):

```bash
node --test scripts/ci/sales_xray_visual.test.mjs
uv run python -m unittest discover -s scripts/ci -p sales_xray_visual_report_test.py
uv run ruff check scripts/ci/sales_xray_visual_report.py scripts/ci/sales_xray_visual_report_test.py
```

Use the Paperclip run scratch directory for local selection, baseline and output
files. Create a selection JSON with `source_sha`, `run_id`, `all` and `paths`, then
run `node scripts/ci/sales_xray_visual.mjs <output-dir> <selection.json>`. The
Python helper's `baseline` command records unavailable without GitHub authority;
its `report` command assembles the evidence. Never point this renderer at a
deployed API or reuse a signed-in browser context.

After watchdog merge, verify the first main advisory artifact and record its
UTC start time, exact source SHA, duration and link on AUT-1016. Verify the merged
commit on dev then staging using the existing release receipt; no laptop deploy.
D2 head collects seven days of false-positive evidence for card D: run/state,
viewport, count/diff, UI Guard verdict, explanation, owner and resolution. Retain
only evidence linked from a scorecard. Expiry alone is not permission to block;
D requires its own reviewed change. Visual rejection returns to the builder,
then the Sol pod lead on the second failure, then CTO on the third with a contact
sheet (`Escalation: rule 3`).

Implementation references: [Playwright fixed clock](https://playwright.dev/docs/clock),
[Actions artifact API](https://docs.github.com/en/rest/actions/artifacts),
[axe API](https://github.com/dequelabs/axe-core/blob/develop/doc/API.md).
