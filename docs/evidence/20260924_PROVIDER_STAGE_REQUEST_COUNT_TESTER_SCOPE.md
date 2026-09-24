# Named provider-stage request-count tester scope

## Change

The hash-pinned hosted approval bundle accepts a fourth named internal-tester
scope, `provider_stage_request_count`. It waives only the base
`StageApproval.max_requests` count for a currently active, email-verified human
account whose canonical email is explicitly listed in the bundle. For a worker
`ProcessingActor`, the authority resolves the human through the current lease,
immutable acquisition usage and submission, and current visitor claim before it
checks the named account. The shared processing identity itself never grants
this scope.

The authority resolves the scope during quote admission and again when the
worker validates the quote before dispatch. A missing, stale, expired, revoked,
unverified, inactive, or non-member identity fails closed. Existing route,
source, provider, model, consent, retention, per-request pricing and shared
budget checks remain in force. Reservations remain append-only and continue to
record every attempted request.

Exact `StageCallSupplement` limits are independent: the scope does not waive a
matched supplement's additional-request, aggregate-cost, per-request-cost, or
prepared-input bindings. A request outside a supplement may proceed only when
the base provider-stage approval and the named count scope independently admit
it. C5 repair-envelope attempt limits remain unchanged.
The scope also does not override idempotency or ambiguous-dispatch handling. A
different request after an uncertain task still requires explicit recovery;
the original idempotency key may return the existing task but cannot dispatch
the provider again.

## Verification

All provider effects in these tests use synthetic local brokers. No external
provider request or hosted approval mutation was performed.

- Unit tests: `test_activation_contract.py` and `test_internal_tester.py` — 37 passed.
- PostgreSQL tests on the disposable loopback database: base same-source count
  remains enforced for ordinary accounts; the named scope admits a second
  recording for its verified owner; an ordinary owner sharing the same
  processing principal remains denied; removing owner email verification
  revokes the exemption; a second logical request cannot redispatch an
  uncertain C2 task; money-budget exhaustion still denies admission; and both
  ordinary and named-owner C5 supplement cases preserve the finite matched
  supplement cap — 5 passed in 244.81 seconds. The named C5 case additionally
  asserts the first recording has reached the base C5 cap and retains both
  uncertain and completed C5 history before a different recording owned by
  the same verified human is admitted. The second request remains queued before
  dispatch, and the earlier C5 task state/checkpoint/input hashes are unchanged.
- Re-ran the named C5 PostgreSQL selector after adding those history assertions —
  1 passed in 54.98 seconds. The exact original key for an uncertain stage
  resolves to the retained task; a different key is rejected for explicit
  recovery, with no provider redispatch.
- Unit tests: 37 passed. Root independently ran 49 acquisition/hosted-runtime
  tests and full package mypy across 88 source files, all passing.
- Ruff lint and `ruff format --check` passed on all changed Python files;
  `git diff --check` passed.
