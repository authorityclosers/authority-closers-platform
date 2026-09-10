# Optional Focus Run backend — local pilot

Scope: the existing single d2de tree; backend implementation only. No staging,
production, live identities, payments, official course progress, migration of
`ac_local_sandbox`, API restart, commit or push was performed by this task.

## Selected policy and implementation

- Explicit opt-in before the first answer, at most once per attempt, and one
  active Focus Run per tenant/person. All existing attempts remain standard.
- Three free Focus charges, cap three. Only a confirmed end after at least one
  feedback acknowledgment costs one charge. Ending before acknowledgment is free.
- Pausing, leaving the page, disconnecting, mistakes and ordinary standard
  practice have no deduction. Ending preserves the attempt and saved responses.
- Finishing the active Focus attempt restores one charge, capped at three, in
  the same transaction as host completion and the existing earned rewards.
- The next saved-timezone local day resets charges to three. Current balance
  reads are non-mutating; the next write journals a due reset. The existing
  next-ISO-week timezone policy is reused. A day high-water mark prevents a
  backward timezone/date shift from reissuing an already visited day. Historical
  event dates/timezones and earned credit/XP entries are never rewritten.

`practice/focus.py` composes the existing local/test-only PracticeApplication
admission and person fence. `practice/focus_models.py` adds a run lifecycle and
an append-only charge-event stream; there is no mutable balance authority.
Migration `20260908_0021` freezes both table definitions, enforces tenant/person
composite references, unique attempt activation, one active run, charge bounds,
contiguous balanced event history, forward-only resets, immutable events, and
deferred consistency between run state and its start/terminal events.

## HTTP contract

- `GET /v1/practice/focus`: policy version, charges, capacity, revision, current
  saved-timezone local day, timezone, and active run (or null).
- `POST /v1/practice/attempts/{attempt_id}/focus` and
  `POST /v1/practice/focus/runs/{run_id}/end`: both require Idempotency-Key and
  `{expected_revision, expected_attempt_revision}`; return `{summary, run}`.
- Run fields: id, attempt_id, pinned set_id, state, started_at, finished_at,
  exit_cost and completion_restore. Replays return current authoritative state,
  not a fabricated historical active state.
- Focus conflicts expose `detail.reason` plus a safe message: attempt_started,
  not_eligible, active_run_conflict, focus_empty, revision_conflict. Generic
  idempotency conflicts retain the existing string error contract.
- Normal session, selected tenant, active membership, exact preview gate, safe
  Origin, strict payloads and function-scoped transaction exit are retained.
  There are no client balance/time/completion inputs or unload/telemetry routes.

## Validation

- 50 unit/relational/HTTP cases passed in 14.61s: 15 Focus cases plus 35 existing
  practice-engine regressions. Includes zero-charge standard access, no reward
  loss, free pre-ack end, once-only end/replay, cap/refill, lazy day reset,
  scheduled timezone behavior, tenant/person/session denial, rollback and HTTP
  proof that a dependency commit failure emits no successful Focus response.
- Initial combined PostgreSQL run: 33 passed in 38.86s. Fresh random loopback
  schema only; migration 0019→0020→0021 preserves preexisting tenant data and
  matches canonical model metadata. Includes actual observed lock blocking for
  simultaneous starts, duplicate end, and completion/end in both lock orders.
- Independent review strengthened the negative PostgreSQL tests to assert exact
  trigger/CHECK/NOT NULL diagnostics. Incidental audit uniqueness and composite
  foreign-key failures can no longer mask missing history guards. The first
  corrected 13-case Focus PostgreSQL rerun passed in 21.64s. The final combined
  rerun after all diagnostic assertions passed all 33 cases in 39.66s.
- Ruff and format: nine scoped files clean; strict mypy: five changed production
  modules clean. Independent review is scoped to this slice, not alpha approval.

Runtime activation, frontend integration and real browser acceptance remain
parent-owned follow-up work. No deployment or public release is claimed.
