# AUT-1016 Sales Xray visual advisory implementation receipt

Implementation evidence only. CTO review, hosted CI, CEO approval, watchdog merge, dev and staging verification remain required. No deployed proof is claimed.

Binding brief: AUT-1008 revision `6caf749e-c869-4871-bdcc-7672475468ba`. The change adds a dedicated report-only workflow, fictional frame renderer, baseline reader, contact sheet, pixel diff and count contract. It makes no blocking flip, release write or required-check change.

Validation: four Node tests, four Python helper tests and four Next config tests passed. The browser regression measures intentionally introduced overflow, console/uncaught errors and critical axe violations; it also proves that the health flag is mocked without a server request, API writes/reads are blocked, and external WebSockets are refused. Prettier, Ruff check/format and the lane check passed.

The catalogue was exercised in two pinned local batches with two low-priority contexts on an existing owned fixture server. This does not establish the hosted job runtime or a complete one-SHA CI run. Normal local renderer use is serial; only hosted Actions uses two concurrent contexts.

Batch A: source `3de37ba0318b08f4b583e27e24781e4088e6fece`, UTC `2026-10-03T16:52:16.719Z`, 254 seconds, 24/36 screenshots measured, renderer `partial`.

Batch B: source `09e4d3650da86b31454b3f771589c14107eff247`, UTC `2026-10-03T17:00:06.515Z`, 68 seconds, 12/12 screenshots measured, renderer `measured`.

Batch A was a partial 36-frame attempt before the acquisition health mock: 24 screenshots succeeded and 12 remained unavailable. Batch B verifies those 12 acquisition screenshots after the fixed fictional mock. Both batches use Playwright 1.58.2, Chromium 145.0.7632.6 and axe 4.13.0.

Normal CLI verification: source `09e4d3650da86b31454b3f771589c14107eff247`, UTC `2026-10-03T17:02:39.112Z`, 30 seconds, 2/2 shell screenshots measured with `capture_concurrency=1`. This run exercised isolated startup, HTTP readiness, browser policy, atomic receipts and owned-server cleanup. It also produced a contact sheet and unavailable-baseline contract.

The tables preserve unavailable axe measurements. Console counts include errors caused by deliberate API refusal. They are advisory observations, not product failures or a visual verdict. UI Guard owns that verdict.

| Batch | State / viewport               | Overflow px / count | Console / uncaught | Axe critical / incomplete |
| ----- | ------------------------------ | ------------------- | ------------------ | ------------------------- |
| A     | shell-1440x900                 | 0 / 0               | 3 / 0              | 0 / 3                     |
| A     | shell-390x844                  | 0 / 0               | 3 / 0              | 0 / 1                     |
| A     | report-moments-1440x900        | 0 / 0               | 3 / 0              | 0 / 2                     |
| A     | report-moments-390x844         | 0 / 0               | 3 / 0              | 0 / 2                     |
| A     | report-prospect-1440x900       | 0 / 0               | 3 / 0              | 0 / 2                     |
| A     | report-prospect-390x844        | 0 / 0               | 3 / 0              | 0 / 2                     |
| A     | report-next-call-plan-1440x900 | 0 / 0               | 3 / 0              | 0 / 2                     |
| A     | report-next-call-plan-390x844  | 0 / 0               | 3 / 0              | 0 / 2                     |
| A     | report-sales-skills-1440x900   | 0 / 0               | 3 / 0              | 0 / 2                     |
| A     | report-sales-skills-390x844    | 0 / 0               | 3 / 0              | 0 / 2                     |
| A     | report-call-signals-1440x900   | 0 / 0               | 3 / 0              | 0 / 2                     |
| A     | report-call-signals-390x844    | 0 / 0               | 3 / 0              | 0 / 0                     |
| A     | report-transcript-1440x900     | 0 / 0               | 3 / 0              | 0 / 2                     |
| A     | report-transcript-390x844      | 0 / 0               | 3 / 0              | 0 / 0                     |
| A     | report-raw-data-1440x900       | 0 / 0               | 3 / 0              | 0 / 2                     |
| A     | report-raw-data-390x844        | 0 / 0               | 3 / 0              | 0 / 0                     |
| A     | report-overview-1440x900       | 0 / 0               | 0 / 0              | unavailable / unavailable |
| A     | report-overview-390x844        | 0 / 0               | 0 / 0              | unavailable / unavailable |
| A     | document-1440x900              | 0 / 0               | 0 / 0              | 0 / 1                     |
| A     | document-390x844               | 0 / 0               | 0 / 0              | 0 / 1                     |
| A     | plans-1440x900                 | 0 / 0               | 4 / 0              | 0 / 2                     |
| A     | plans-390x844                  | 0 / 0               | 4 / 0              | 0 / 1                     |
| A     | billing-1440x900               | 0 / 0               | 4 / 0              | 0 / 1                     |
| A     | billing-390x844                | 0 / 0               | 4 / 0              | 0 / 2                     |
| B     | auth-email-1440x900            | 0 / 0               | 0 / 0              | 0 / 1                     |
| B     | auth-email-390x844             | 0 / 0               | 0 / 0              | 0 / 1                     |
| B     | auth-code-1440x900             | 0 / 0               | 0 / 0              | 0 / 1                     |
| B     | auth-code-390x844              | 0 / 0               | 0 / 0              | 0 / 1                     |
| B     | auth-error-1440x900            | 0 / 0               | 0 / 0              | 0 / 1                     |
| B     | auth-error-390x844             | 0 / 0               | 0 / 0              | 0 / 1                     |
| B     | upload-selected-1440x900       | 0 / 0               | 0 / 0              | 0 / 2                     |
| B     | upload-selected-390x844        | 0 / 0               | 0 / 0              | 0 / 1                     |
| B     | processing-report-1440x900     | 0 / 0               | 0 / 0              | 0 / 1                     |
| B     | processing-report-390x844      | 0 / 0               | 0 / 0              | 0 / 0                     |
| B     | processing-failed-1440x900     | 0 / 0               | 0 / 0              | 0 / 1                     |
| B     | processing-failed-390x844      | 0 / 0               | 0 / 0              | 0 / 0                     |

Both report-helper outputs produced contact sheets and a count-only receipt. Last-green-main baseline lookup returned unavailable because the workflow has no eligible main artifact yet. Every diff remains unavailable with null pixel counts and ratios. The one-pixel helper regression proves the available-diff calculation separately; it is not a CI baseline.

Local screenshots and diffs are temporary and are not checked into Git or retained on the board. Hosted evidence will be `sales-xray-visual-<sha>-<attempt>` with three-day retention. Its receipt links each screenshot, route, viewport, baseline run/SHA and diff availability. See [the runbook](../runbooks/SALES_XRAY_VISUAL_ADVISORY.md) for the contract and post-merge seven-day false-positive collection.

Delivery gate at handoff: main is green and the devenv branch may continue, but shared-file PR #251 (AUT-428 migration) occupies the shared slot. Opening this workflow PR concurrently would fail `single-track`. No lane/dependency blocker is invented for that sequencing constraint. Review the pushed branch now; open the PR when the gate permits, then verify hosted full-catalogue coverage and runtime before CEO approval.
