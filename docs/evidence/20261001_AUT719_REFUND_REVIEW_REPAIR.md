# AUT-719: PR #179 refund and C1 review repair

Source: CTO changes requested at `35936c1738a0c9e6d300ba08f51df83dd75930aa`,
comment `6e287643-fcd2-4bb9-b0ae-08a180b3eb0d` on [AUT-719](/AUT/issues/AUT-719).
Controlling sources: [AUT-560 plan](/AUT/issues/AUT-560#document-plan), revision `d3daabe0-54f7-4052-bd30-83bb129ef7b7`, with the CTO amendment and Contract C1 from
that document, plus [S2d-1](/AUT/issues/AUT-560#document-spec-cards) revision
`190c7a04-99d9-44af-b534-e082ca4c861f`, and ADR 0052. The source pin for this
repair is the commit containing this evidence, on the existing
`task/billing/560-billing-backend` branch. No new task branch or checkout.

## Result

1. Refund preparation uses a separate database transaction: account authority,
   admission lock, zero-use eligibility, all payment lots' holds, pending intent
   and account-scoped command response commit together before the provider call.
   The authenticated caller's rollback cannot undo them. A timeout, duplicate
   receipt error or crash leaves the intent pending; replay never sends the call
   again. Definite refusal releases capacity; a verified processed result closes
   it. Receipt and callback results append history under the admission lock.
2. Callback matching uses the provider and original accepted payment (a charge
   linked to a paid order event or period), then that payment's pending refund,
   its provider refund id, and its entire expected amount/currency. A mismatch is
   recorded for review with no ledger change. An unknown refund id after a lost
   response needs the signed receipt to match the deterministic command reference;
   an unrelated receipt cannot take its hold. Repeated events and distinct notices
   of the same settled refund produce no additional ledger rows.
3. Subscription callbacks resolve through the stored original payment; Razorpay's
   provider-generated payment order id need not equal the stored subscription id.
   Yearly refund settlement selects all twelve lots of that payment, including
   future months. Two pending period refunds on one subscription order remain
   independent.
4. Verify checks account-scoped command replay before the rate limit or provider
   read, and stores the exact Order result. Its successful-read rate window is
   persisted, including across service restart. Refund checks the key and exact
   reason before replay/provider work; a changed body conflicts. Same-key concurrent
   commands serialize through the shared admission lock.

All billing tables remain append-only. Access still reads only ledger and usage.
No migration, settings, prices, credentials, deployed service, production data or
real payment changed. `AC_BILLING_ENABLED` remains off.

## C1 responses

No public JSON field or route was added. A newly accepted refund saves and returns
its pending acceptance (202), even if the synchronous provider receipt has already
settled the hold by the time the response arrives. Replaying that key returns the
same acceptance, without a second money-moving call. `GET /v1/orders/{order_id}`
shows subsequent `refunded` or `refused` state; a new key on an already refunded
payment saves and returns `refunded` (200). Verify replays the exact first Order,
including its original timestamps, refund object and status.

Fictional example, using the shape validated by the HTTP tests:

```json
{
  "refund": {
    "payment_id": "pay_FICTIONAL719",
    "refundable_until": "2026-10-08T09:00:00Z",
    "state": "pending",
    "reason_code": null
  }
}
```

The Razorpay normalization adds only an internal signed `refund_reference` from
`refund.entity.receipt`; it is not a C1 field. The official
[refund webhook samples](https://razorpay.com/docs/webhooks/refunds/) include the
refund/payment ids, money and receipt, and do not include a subscription reference.
Those samples guided the signed fictional fixtures, not a live-provider claim.

## Verification on the server's isolated billing dev test database

All commands below exited 0 on the final implementation:

- `python3 scripts/ac_task.py check` — billing task free to continue. The initial
  status briefly saw AUT-663's checkpoint branch; the resume check and subsequent
  status confirmed that checkpoint had been released. No gate workaround.
- `uv run ruff format --check packages/python tests` — 840 files formatted.
- `uv run ruff check packages/python tests` — all checks passed.
- `uv run mypy packages/python` — 359 source files, no issues.
- `uv run pytest tests/unit/billing tests/unit/payments tests/unit/http/test_billing_routes.py -q`
  — 294 passed; one existing FastAPI/Starlette deprecation warning.
- `uv run pytest tests/database/test_billing_settlement_postgresql.py tests/database/test_billing_refund_safety_postgresql.py -q --tb=short`
  — 35 passed. Disposable loopback PostgreSQL, fictional accounts, fake provider
  or HTTP MockTransport, no provider network traffic. These are database/service
  regressions, not a real TEST-provider end-to-end proof.
- `git diff --check` — pass.

The 24 safety cases cover committed holds during an in-flight provider call,
caller rollback, timeout, crash, restart replay, changed refund reason, six kinds
of mismatch for both processed/failed callbacks, exact and distinct duplicates,
both reservation race orderings, verify replay/concurrency/restart/rate limiting,
definite refusal, signed monthly/yearly Razorpay refunds, a signed payment
mismatch preceding a real accepted charge, and multiple refunds on one
subscription order. The existing eleven settlement cases continue to pass.

Intermediate runs found the expected old assertions for immediate refund results
and nonmatching fixture refund ids (3 failures, 8 passes); those fixtures now check
immutable acceptance and the actual stored refund id. New Razorpay fixtures first
omitted their TEST mode, then their initial awaiting-payment event (4 failures in
each bounded run). Both fixture omissions were corrected; final 35-case run passes.
One strict mypy issue in SQLAlchemy's scalar typing was corrected with an explicit
model annotation; the final static gates pass.

## Dev reproduction and review

From this branch in the billing checkout, use the existing environment-injected
loopback disposable database URLs and run the two PostgreSQL test files above.
They build fresh isolated schemas, migrate them, seed fictional identities and
provider evidence, and exercise the real application/ledger with independent
connections. Never substitute a production URL or real recordings. Normal dev
billing remains disabled; no deployed application journey or real Razorpay TEST
charge was performed in this repair.

Return this head through CI, then obtain CTO review and CEO approval. The existing
merge hold remains until the corrected head passes review; the watchdog owns CI
completion/head events and the eventual approved merge. No CI polling timer or
permission task was created.
