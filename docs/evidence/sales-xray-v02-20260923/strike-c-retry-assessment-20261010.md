# Strike C: durable, bounded provider-refusal assessment

Task: [AUT-1676](/AUT/issues/AUT-1676). Continues the provider-failure evidence
slice at `19b88fa3e45d4f7f3aa5b29d6b806775c784a7eb` on
`task/sx-billing/1676-strike-p0`, [PR #421](https://github.com/authorityclosers/authority-closers-platform/pull/421).

The worker now commits a transport retry assessment after committing the original
sanitized observation and before failure cleanup. It binds the assessment to the
original event ID/hash, tenant, run, dispatch key/time, quote, provider route,
input digest, lease and recovery generation. Identical assessments are
idempotent; conflicting assessments cannot replace history. The observation and
assessment use separate transactions, so an assessment failure cannot erase the
original observation. Both use the existing append-only audit chain.

Only complete, empty 429/500/502/503/504 responses with the correct empty-body
digest qualify. Truncated/nonempty/inconsistent bodies require reconciliation.
Other statuses or configuration diagnostics do not qualify. A saved error string
cannot substitute for the original observation. Backoff uses the repository's
bounded exponential policy and deterministic positive jitter. Retry-After is a
minimum wait; a long server wait is never truncated to the local backoff cap.
The retry deadline must fit both the original quote and execution-permission
window. Exhausted worker claims do not reset to zero. Replay uses the original
event time, so it cannot slide the deadline.

## Authority boundary

Source inspection found `Reservation` records one provider attempt and
`mark_dispatched` refuses a second attempt. `max_attempts=3` in the job limits
worker claims, including acknowledgements; it is not permission or reserved
budget for three external sends. The assessment therefore always records
`dispatch_authorized: false` and provider cost as unresolved. It never clears a
dispatch marker, issues a success/no-charge receipt, schedules a job, settles
minutes or changes an approved provider/model. Generic Admin retry remains
guarded. Automatic redispatch requires the separate reviewed attempt/budget
ledger interface, with current consent/retention/source/identity/frozen-route
checks at dispatch.

This follows the [CTO refusal decision](/AUT/issues/AUT-1617#document-decision),
revision `23814a68-b4e1-429c-87d9-94bd1dc2dfa9`, and the later owner strike
directive. The completed exact-ID controlled intake and relevant UXA/GOV-AUD
assurance are recorded in [the preceding evidence](strike-c-provider-failure-evidence-20261010.md).
No scoring, real-call replay or provider activation is part of this slice.

## Internal shape and public API

New action: `conversation.provider_retry_assessed`, resource type `job`.
Payload schema: `ac.sales_xray.provider_retry_assessment/1`. It includes
`job_id`, `failure_event_id`, `failure_event_hash`, `claim_count`, `claim_limit`,
`recovery_generation`, and `assessment`. Fictional eligible assessment:

```json
{
  "state": "transport_retry_eligible",
  "not_before": "2026-10-10T02:00:12+00:00",
  "dispatch_authorized": false,
  "provider_charge_state": "unresolved"
}
```

Other assessment states are `reconciliation_required`, `non_retryable`,
`claim_limit_exhausted` and `authorization_window_exhausted`; their `not_before`
is null. These are internal assessments, not learner progress states.
The public API remains unchanged; the response example in the preceding evidence
still applies. UI wiring must not display automatic retry or returned minutes
from this internal event. Ownership-scoped public reads are unchanged.

## Verification

- Focused unit tests: **70 passed** across retry assessment, observation and
  worker-stage tests. Provider transport suite: **47 passed**.
- Package mypy: **438 files passed**. Changed Python files pass Ruff lint and
  format; `git diff --check` passes.
- The first **9 PostgreSQL cases passed** on the disposable loopback
  `ac_test_lane_sx-billing` (97.90 seconds). The final targeted missing-evidence
  case also **passed** (69.49 seconds; 9 deselected), verifying an error string
  cannot qualify. These are two local invocations, not a staging receipt.
- Database tests retain original evidence, audited chain integrity, no second
  broker send, no success/no-charge receipt, generic retry refusal, identical
  replay and lease/generation/binding rejection. They cover assessment and cleanup
  crashes, incomplete/nonempty responses, nonretryable status, claim exhaustion
  and authorization-window exhaustion. Synthetic media/checkpoints isolate this
  proof from native decoding and provider access.
- Public dev and staging HEAD requests returned **403**. No authenticated
  staging inventory/read-back, green CI or deployed behavior is claimed.

## Continuation and release

Automatic retries, stale-work recovery/alarming, terminal UI/minute lifecycle,
fresh staging fault proof/inventory, historical recovery and the original
`0373c8f4` report remain unfinished. Pipeline work stays in the strike; ledger
changes require the separate small CTO/CEO sign-off PR. Historical restitution
has no apply authority. Watchdog owns merges; production requires the owner's
ship-it through CEO. Rollback uses a code revert through the normal release
path and preserves previously appended audit evidence.

Dev: <https://salesxray-dev.authorityclosers.com>.
