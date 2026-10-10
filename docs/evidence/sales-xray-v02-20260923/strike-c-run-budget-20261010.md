# AUT-1676: bounded plan recovery and overdue inventory

Source pin: d38f39a18578f8550c6dc7f9b9f0a0df58d3280d. Controlled source intake and relevant
UXA/GOV-AUD receipt are in strike-c-provider-failure-evidence-20261010.md. The owner
AUT-1701 strike instruction governs scope and the customer report-delivery rule.

Quoted and active plans now expire into a durable held failure with the bounded
`processing_budget_expired` code. The scheduler selects expired plans even when
next_check_at is in the future, and handles expiry without attempting execution
admission. The immutable original plan, acceptance, provider records and minutes
remain intact. Live passes retain the existing admission-before-plan-lock order.
Competing expiry locks are skipped; repeated recovery finds no active candidate.
Profile holds and normal polling cannot schedule a check past the plan's expiry.

A coordinator pass has a 30-second timeout. Its nested transaction rolls back
partial planning/enqueue work before recording a content-free terminal failure.
Unexpected ordinary exceptions are recorded as `processing_coordinator_failed`;
timeouts use `processing_coordinator_timeout`. Cancellation still propagates.
Existing authorization/input errors retain their previous bounded failure code.

`overdue_processing_plans(database, limit=100)` is a read-only watchdog inventory:
IDs, budget expiry, state, owner and truncation only. It uses the database clock;
its alarm vocabulary cannot claim a provider retry, returned minutes or report.
Watchdog invocation/delivery, pre-plan/local-run expiry, customer settlement and
safe retry UI remain work in progress. No deployment or staging proof is claimed.

Verification: 48 focused processing-plan unit cases passed. Four disposable
sx-billing PostgreSQL cases passed (18.90s): expired quoted/accepted plans, expiry
winning over future polling, read-only alarming, concurrent lock skip, repeat
recovery, exception/timeout rollback and preserved immutable plan evidence.
Targeted mypy passed for both source files. Ruff lint/format and diff checks pass.

Dev: https://salesxray-dev.authorityclosers.com. After the normal authorized release,
leave a fictional plan quoted beyond its expiry, or interrupt an accepted plan;
the scheduler must stop it at its original expiry. Read back the bounded failure
code and verify that the overdue inventory clears on the next recovery pass.
This slice alone does not complete the no-charge-without-report journey.
