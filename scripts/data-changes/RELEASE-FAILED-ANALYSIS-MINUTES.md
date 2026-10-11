# Failed analysis recovery: AUT-1801

This tool is prepared for review. It has not been applied to staging or production.
Claude/Root is the operator; Strike H keeps both environments read-only.

First run `scripts/sales-xray-analysis-audit.py` in each approved injected runtime.
Inspect the five historical held plans and their latest minute events. A held
plan can correctly remain held after #421 while its customer minutes are released.
The scheduler already calls `ReportMinutes.settle_terminal_plan()`; do not use
this tool when that recovery has already succeeded.

For an exact failed-plan list still missing its release, run
`release-failed-analysis-minutes.py` without `--apply`, naming each `--plan-id`,
the environment and a fresh `--run-reference` UUID. The default transaction is
read-only. It prints identifiers, states, before/after and a preview fingerprint.

After CTO review, show that preview to the owner. Obtain the recorded exact
"approve data change: release the failed analysis reservations for <plan list>,
<environment>" permission. Take the production database snapshot and record its
reference before applying. In the approved injected runtime, rerun the exact
list with `--apply`, `--expected-fingerprint`, `--approver`,
`--approval-reference`, `--operator-reference` and `--snapshot-reference` (UUID
references to the recorded receipts, never credentials). The environment and
before state are bound to the fingerprint; changed state requires a new preview.

One transaction calls the existing app `ReportMinutes.release_plan()` for the
explicit targets and appends attribution audit events. An already released or
delivered reservation is a no-op. App lineage locks preserve a successor's
reservation, and the app's journal fences late workers and duplicate delivery.
No provider work, plan acceptance, budget balance adjustment, expiry extension,
audit rewriting or SQL update is performed. If any target is invalid, the whole
transaction rolls back. Existing scheduler and Admin/owner retry paths cover
the result without permanent hand-made state.

Read back through the app/API and the audit export, then post IDs/counts,
before/after, run reference, operator and approver on AUT-1801. If a report is
still needed, use the existing owner retry or retained-C5 recovery path with
its consent, retention and provider reconciliation gates. This tool releases
failed customer reservations; it does not claim to recover a missing report.

Focused PostgreSQL evidence covers a read-only preview, one journal release and
attributed audit event, an idempotent replay, invalid exact lists/stale state,
and rollback of the first release and audit when the second target fails.
Existing report-minute tests also cover release versus delivery races, successor
reservation fences and capture once on an explicit retry. No live application
state was changed to obtain this evidence.
