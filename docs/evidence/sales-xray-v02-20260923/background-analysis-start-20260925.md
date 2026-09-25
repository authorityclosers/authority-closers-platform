# Analysis start survives navigation

The intentional Analyse click now hands the saved source and its fixed language,
source digest and consent policy to the root upload session. Moving to Calls no
longer destroys the component that must wait for native checks and start the
analysis. The embedded learner keeps its existing flow.

The controller adopts work already progressing on the server. Otherwise it quotes
once and accepts once with stable idempotency keys. A lost or timed-out acceptance
response causes one bounded owner-plan read; it never repeats the acceptance POST.
Native checks have a 120-second total deadline. Quote and acceptance each have a
30-second timeout; reconciliation is also bounded. An unresolved outcome preserves
the call and shows an action. Account changes cancel the start and discard late
results. The activity indicator distinguishes checking, starting, accepted and
needs-action states.

The recent-calls preview now waits until acquisition entry is confirmed enabled.
This avoids a premature acquisition-history request on the account-only fallback,
which the standalone browser CI detected as an aborted request. The browser test
allowlist has not been weakened. A formatting-only change fixes the existing C5
benchmark database-test formatting gate.

Validation: 109 focused tests passed across analysis-start, upload-session and
acquisition-studio after adding stalled-check, stalled-quote and acceptance-timeout
regressions. TypeScript and changed-file ESLint passed after review corrections.
Independent review identified the original unbounded wait; the corrected deadline
and single-read reconciliation passed re-review. Final integration checks run in CI.

Limitations: recovering a lost upload response still uses the mounted recovery
flow. This patch does not implement durable server-side authorization across a full
browser close, and does not prove provider output quality or hosted acceptance.
No providers, budget grants or stored reports were changed by these checks.

Claude Code supplied the initial bounded patch through its included subscription
(2% to 13% five-hour usage; Fast disabled). Root review fixed type, lint, deadline
and premature-preview defects before integration. AGY's separate source review was
advisory; neither external review received customer report content.
