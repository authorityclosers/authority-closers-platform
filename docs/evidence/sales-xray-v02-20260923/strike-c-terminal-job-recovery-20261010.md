# Strike C: reconcile terminal worker jobs

[AUT-1676](/AUT/issues/AUT-1676), continuing `f9464b04ef1e2c4f6b3e5919bb2e295cb49642c1` on [PR
#421](https://github.com/authorityclosers/authority-closers-platform/pull/421). The exact-ID controlled intake and UXA/GOV-AUD
receipt remain in [the original evidence](strike-c-provider-failure-evidence-20261010.md). The [CTO
decision](/AUT/issues/AUT-1676#document-decision), revision `70a2f290-4847-430b-8a5f-ea4951c7f4b9`, separates customer
settlement from provider cost.

## Change

After claim applies its existing database-clock lease and claim-budget expiry, the provider worker reconciles at most one
dead-lettered job's active task/run. Previously a process crash could leave that task running after job quarantine; the
processing coordinator could keep waiting for a result that would never arrive. The exact tenant, job, run, person, recording
and task-generation joins bind the update. Current recovery generation, row locks and SKIP LOCKED fence concurrent work.
Completed/cancelled/erased tasks, checkpoints, validated receipts and live leases are preserved. Scheduled backoff remains
governed by existing claim logic.

A dispatched job becomes internally uncertain, with its run failed. An exhausted undispatched job becomes failed. This gives
the existing coordinator a terminal task to observe; its current held-plan behavior still needs the terminal UI change. No
dispatch evidence, receipt, attempt count or minute snapshot is cleared. No provider send or restitution occurs. Original
observations remain append-only.

The same transaction appends `conversation.provider_job_recovery_required`; an audit error rolls back the update. A completed
reconciliation leaves no active candidate, so repeated passes emit no duplicate signal. This durable signal is not yet
delivery of an alarm to Root; alarm routing remains unfinished.

## Contract

The internal audit payload has schema `ac.sales_xray.provider_job_recovery/1`:

```json
{
  "schema": "ac.sales_xray.provider_job_recovery/1",
  "run_id": "01234567-89ab-4cde-8f01-23456789abcd",
  "stage": "C5",
  "claim_count": 1,
  "claim_limit": 3,
  "recovery_generation": 1,
  "dispatch_started": true,
  "task_state": "uncertain",
  "run_state": "failed"
}
```

Public response shapes remain unchanged; use the original evidence's example. This event cannot
authorize UI claims of automatic retry or returned minutes. Customer release/capture and successor
retry require the separately reviewed canonical ledger interface. Ownership-scoped public reads are
unchanged.

## Verification and remaining delivery

All **19 PostgreSQL cases passed** on disposable loopback `ac_test_lane_sx-billing` (77.33 seconds), including 9 recovery
cases: expiry/exhaustion, live lease, erasure, cancellation, generation, validated receipt, concurrent lock and audit
rollback. They also prove repeat safety, stale-worker fencing, no second broker send, unchanged customer minutes and
audit-chain integrity. **70 focused unit tests** passed; Ruff lint/format, package mypy (**438 files**) and diff checks
passed. Initial local database fixture errors violated existing erasure/dead-letter guards; fixtures were corrected without
changing those guards or any schema. Public dev/staging HEAD requests returned 403. Authenticated staging inventory, fault
proof, CI success and deployed behavior are not claimed. No host/provider activation, production change, historical recovery
or minute mutation occurred. Automatic redispatch, terminal settlement/UI, Root alarm delivery, staging proof and the original
`0373c8f4` report remain open. Watchdog owns merges; ledger changes retain separate CTO/CEO sign-off and production retains
owner ship-it through CEO.

Dev: <https://salesxray-dev.authorityclosers.com>. Rollback is a reviewed code revert through the normal release path;
previously appended evidence stays intact.

Follow-on verification: **2 targeted PostgreSQL cases passed** (19 deselected, 31.29 seconds). An exhausted provisional
receipt retains dispatch/receipt evidence and fails internally as uncertain; future retry backoff remains scheduled, even at
the claim ceiling. Minutes stay unchanged in both cases. Ruff lint/format, package mypy (**438 files**) and diff checks
passed. Earlier receipts above remain separate runs; this is no staging or alarm-delivery claim. Evidence prose was rewrapped
to keep the strike within its size limit; every prior word was verified unchanged.
Completion-time follow-on: reproduced a failed recovered run with null `completed_at` (1 failed case before the fix).
Recovery now records completion time atomically with the audit event; ordinary failure records it once.
**11 recovery cases passed** (70.20s); **10 failure-observation cases passed** (90.20s), in separate local runs.
Tests prove timestamp equality with recovery audit, rollback, unchanged live/backoff states and repeat safety. Ruff and mypy passed.
The [fresh staging snapshot](/AUT/issues/AUT-1730#document-inventory) found 10 failures across 7 sources, 6,643 seconds reserved.
It observed API release `b6033ad3`; authenticated read-back was unavailable (401). This patch is not deployed proof.
