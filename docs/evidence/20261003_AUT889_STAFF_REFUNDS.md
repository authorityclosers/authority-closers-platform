# AUT-889: platform staff refunds

Source: `main` at `2924b3231192d57c87b4902477022d181b7d219f`.
Task: AUT-889, implementing the CTO decision recorded in its description.
Lane: billing. No migration, catalogue/settings change or real provider request.

`POST /v1/platform/billing/payments/{payment_id}/refund` is restricted to the
configured Admin host, a safe Origin and a fresh `platform_billing_manage`
projection. The command service also reads fresh authority before looking up
the payment; a caller's selected tenant or membership role grants no authority.
The reason is required, nonblank and at most 500 characters. The existing
customer route and `CheckoutService.account_by_id` ownership rule are preserved.

Both commands share the same eligibility, hold, idempotency, provider submission
and settlement implementation. Staff preparation writes the hash-chained
`billing.staff_refund_requested` audit, refund event and ledger holds in the
authenticated request transaction. It commits that intent before provider
submission; subsequent result events use the existing independent transaction.
This avoids foreign-key inserts waiting on the same request's fresh Person and
Session locks. Ledger holds reference the audit event. Refund events carry the
staff person id and supplied reason.

## API contract

Request: `Origin: <configured Admin origin>`, `Idempotency-Key: <command key>`
and `{"reason":"Fictional customer requested refund through support"}`.

Accepted example (202; 200 when the returned state is no longer pending):

```json
{
  "refund": {
    "payment_id": "fake_payment_fixture",
    "refundable_until": "2026-10-08T09:00:00Z",
    "state": "pending",
    "reason_code": null
  }
}
```

The response model is the customer's `RefundCommandResponse`. Existing refusal
codes remain `refund_window_closed` (422) and `payment_used` (409). Missing
idempotency key is 428; missing/revoked capability is 403; a non-owner still gets
404 from the customer route. Replaying an accepted request preserves its original
pending response even after settlement, and does not resubmit to the provider.

## Reproduced checks

- `ac-gate status`: billing FREE; `ac-gate done` cleared the closed AUT-739
  checkout; `ac-gate start billing 889-staff-refund`: claimed from current main.
- `ac-gate check`: pass.
- `uv run ruff format --check packages/python tests`: pass (896 files).
- `uv run ruff check packages/python tests`: pass.
- `uv run mypy packages/python`: pass (377 source files).
- `uv run pytest tests/unit/http/test_billing_routes.py tests/unit/http/test_staff_refund_routes.py tests/database/test_staff_refunds_postgresql.py tests/database/test_billing_refund_safety_postgresql.py tests/database/test_billing_settlement_postgresql.py -q`:
  73 passed, before adding the processed-receipt parameter below.
- `uv run pytest tests/unit/http/test_staff_refund_routes.py tests/database/test_staff_refunds_postgresql.py -q`:
  final staff suite: 16 passed. Includes processed and ambiguous provider outcomes,
  another account, real identity transaction locks, audit/hold durability before
  the provider call, replay/conflict, missing/revoked authority, direct command
  authority, and identical staff/customer window/use refusals.
- `git diff --check`: pass.

Tests use fictional accounts and a random migrated schema on the supplied
disposable loopback PostgreSQL database. Only the fake provider is called.

## Dev verification

Run the two staff suites above from the dev checkout: the database suite drives
the HTTP route through real identity resolution, capability projection, ledger
and audit transactions. After merge and the Admin follow-up switches its refund
button to this path, use a fictional TEST payment in Admin → Billing and verify
Refund sent / Refunded plus the named staff actor in the audit trail. That
deployed browser journey is pending the Admin follow-up, not claimed by this
local API proof. CTO review and CEO approval precede merge; completion requires
merge and the dev check.
