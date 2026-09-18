# Sales Xray minute and budget ledger kernel

2026-09-13. Pure deterministic implementation with scoped execution receipts.
No provider runtime is activated.

## Boundaries implemented

`entitlements.py` supplies frozen snapshots and pure transitions. The AC application
authorizes actors and references, locks current PostgreSQL rows, persists both snapshots
and appends immutable journal command facts. This module does not grant access from a
payment webhook, mint implicit minutes, call a provider, read credentials or purchase credit.

`MinuteAccount(tenant_id, account_id)` starts with zero seconds. Only `MinuteGrant` with
an explicit authorization reference, actor and reason adds allowance. Replayed grants
are idempotent; conflicting reuse of a grant ID fails. No default course allowance,
expiry policy or protected billing multiplier is invented.

`BudgetAccount(scope_id, cap_paise, cap_approval)` is the shared project cap rather than a
per-user cap. Its initial approval may authorize at most the normal INR1500 (150000 paise)
limit. A cap increase requires a distinct owner approval bound to the previous snapshot
and exact new amount. Above INR2000 (200000 paise) additionally requires an explicit new
above-ceiling authorization. Budget capacity never substitutes for a per-execution quote
and recording/provider/privacy permission.

`Quote` binds the source tenant/recording/hash/revision, minute account, project budget,
provider/model, recipe, operation, exact input hash, privacy revision, permission,
provider terms, retention, professional gate, pricing evidence, maximum integer paise,
explicit entitlement seconds, creation and expiry. `ExecutionPermission` binds the
complete quote fingerprint and expires independently. These references must resolve
through server-loaded AC authorization; fingerprints or caller booleans are not authority.

Seconds are supplied for the exact operation. `metered_seconds(duration_ms)` rounds a
chosen recording duration upward once, but is never called implicitly by reservation.
An approved profile-only replay can quote zero extra seconds. Zero-priced offline work
still requires an explicit quote/permission and uses the quoted minute reservation.

## Transition interface

- `grant_minutes(account, grant) -> MinuteAccount`
- `revise_budget_cap(budget, new_cap_paise, approval) -> BudgetAccount`
- `reserve(minutes, budget, reservation_id, quote, permission, now_epoch)`
- `mark_dispatched(minutes, budget, reservation_id, attempt_id, now_epoch)`
- `mark_uncertain(minutes, budget, reservation_id, evidence_ref)`
- `settle(minutes, budget, reservation_id, receipt)`
- `release(minutes, budget, reservation_id, reason_ref, no_charge_receipt=None)`

Paired operations return `LedgerTransition(minutes, budget, reservation, changed)`.
Only a newly committed dispatch transition can authorize its one outbound attempt.
An idempotent `changed=False` response never authorizes another provider call. A quote
can have only one reservation in its tenant; retry with its original reservation ID.
A fresh independent execution needs a fresh quote and exact permission.

Cancellation before dispatch releases once. Dispatched or uncertain work remains
reserved until an exact provider/attempt no-execution-and-no-charge receipt permits
release, or an actual-usage receipt settles it. An ambiguous timeout is not evidence of
zero cost. Settlement returns unused hold; repeated identical settlement/release is a
no-op and conflicting repeats fail. Settled spend cannot be released as if it never
happened.

Overrun receipts are preserved as `reconciliation_required`; actual usage is never
clipped to the quote. Committed amounts expose the greater of the original hold and
observed actual usage, including a negative available balance when appropriate. The
hold blocks all new project spend and cannot be silently settled or released. An owner-
approved overrun resolution command is intentionally not invented in this pure slice.

All persisted models expose strict `as_dict()` / `from_dict()` with versioned schemas.
Extra or missing fields, floats/booleans for integer amounts, malformed nested bindings,
counterfeit released dispatches, mismatched permissions and invalid state/receipt pairs
are rejected. Deserialization validates structure and invariants, not actor authorization
or provider authenticity. Persist journal facts outside replaceable balance snapshots so
every superseded state and command reason remains auditable.

## Required PostgreSQL integration and concurrency proof

Use one transaction with a consistent lock order on the **shared budget row first**, then
the exact tenant/person minute row. Reload both rows after locking. Validate the expected
row revisions, execute the pure transition, update both snapshots and revisions, and append
the immutable journal and transactional outbox fact atomically. Enforce unique reservation
IDs, tenant/quote IDs, minute grant IDs and journal command idempotency keys in PostgreSQL.
Locking only a learner row permits two users to overspend the same project cap.

The dispatcher must recheck current permission/revocation and provider gate evidence at
dispatch, because a snapshot fingerprint does not detect later revocation. Commit the
stable provider attempt ID before sending. Deliveries need provider idempotency where
supported; a crash or ambiguous acceptance is reconciled, not blindly retried. A recovery
worker must never auto-release an unknown accepted call. Actual charged receipts and
minute usage decisions require server verification; provider input cannot grant minutes.

The coordinator must test real PostgreSQL contention: simultaneous reservations across
two minute accounts on one budget; same-command replay; quote reuse; rollback between
snapshot writes; crash after dispatch; unknown outcome reconciliation; guessed tenant
IDs; and revoked permission before dispatch. The pure serialized transition tests do
**not** establish database isolation or deployed concurrency behavior.

## Validation status

Authored targeted tests for integer metering, explicit grants, paired rollback, shared cap,
recording/provider/privacy fingerprints, expiry, idempotent reserve/settle/release, no double
dispatch, zero-price offline/profile replay, uncertain outcome holds, actual overrun visibility,
new owner cap approval, strict JSON round trips and malformed snapshot rejection.

Final post-format run: **32 passed in 0.23 seconds**, exit 0. Scoped Ruff passed for
`entitlements.py` and `test_entitlements.py`; scoped mypy with `--follow-imports=silent`
passed for `entitlements.py`. Initial formatting findings were corrected before the
final checks and pytest run. The shared finite slot was returned to the coordinator.

```powershell
$env:PYTHONPATH='D:/Projects/authority-closers-platform-sales-xray/packages/python'
& 'D:/Projects/authority-closers-platform/.venv/Scripts/python.exe' -m pytest `
  tests/unit/conversation_intelligence/test_entitlements.py `
  --junitxml='D:/Projects/authority-closers-release-transfer/2026-09-13-sales-xray/receipts/entitlements.xml'
```

Receipts under `D:/Projects/authority-closers-release-transfer/2026-09-13-sales-xray/receipts/`:

| Receipt | SHA256 |
| --- | --- |
| `entitlements.xml` | `322967eadd355b9b5759a9ef331065d2ea5d94a4d398c0f23610d61cacd1a241` |
| `entitlements.stdout.txt` | `d716c92b29b621c881df94aa27b6c635b283155d3bac9f7826c7ce5ee95e2a50` |
| `entitlements.ruff.txt` | `a4443afdcfb6d7363adb285762515ccf7cf50473b1a05c20c1a50f6bed4d26b0` |
| `entitlements.mypy.txt` | `8e63ae22e8213e327a5e9cbd584067681681bd8ef7f25c869877887ccdcfc4ff` |

Provider-tested: no. Staged: no. Production-published: no. Secrets read/copied: none.
Cash spent: zero. Real PostgreSQL contention and transaction-boundary tests remain
the coordinator's integration responsibility.
