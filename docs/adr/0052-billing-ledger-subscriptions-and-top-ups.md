# ADR 0052: Billing ledger, subscriptions and top-ups

- Status: accepted 30 Sep 2026 (CTO amendment on AUT-560, sections A–G and
  amendment 2 section L); implemented in slices S1–S6
- Date: 2026-10-01
- Scope: accounts, ledger, projection, periods, top-ups, refunds, provider

## Context

Sales Xray admits uploads from one shared quota (3,600 trial seconds plus
audited Admin grants, less reserved and settled use). The first paid user
needs monthly or yearly subscriptions and top-up packs for Personal and pooled
Organisation accounts, paid in INR through Razorpay. Only a verified provider
event may create paid seconds, and use already lives in append-only tables.

## Decision

1. Accounts. `billing_accounts` is Personal = (public learner tenant, person)
   or Organisation = (organisation tenant, no person); the operations tenant
   is refused and an unclaimed guest has no account, only the trial.
2. The ledger stores capacity, never use. Positive rows are lots
   (`period_grant`, `purchase`, `grant`, positive `correction`); negative rows
   are closings on one lot, never above its remainder (`expiry`, `refund_hold`,
   `refund`, negative `correction`); `refund_hold_release` reopens a hold. Each
   row carries signed `seconds`, `valid_from`, `expires_at` (NULL = never), a
   unique `source_ref`, actor, reason and audit event. Legacy audited grants
   are mirrored once as `grant` lots; new Admin grants write the lot in the
   same transaction as their audit event.
3. The trial is a derived lot, never a stored row: the trial policy gives the
   seconds and window; `valid_from` is the first reservation of the person or
   a visitor they claimed. Organisation accounts have no trial.
4. One pure FIFO projection serves admission, `/v1/me/usage`, Admin and
   reconciliation: uses in reservation order are allocated to lots valid at
   the use's time, earliest expiry first; unallocatable use is overdraft;
   `available(t)` is the unallocated capacity of lots valid at `t` less
   overdraft, floored at zero. Vectors: trial v1 3,600 + 600 grant − 120
   settled = 4,080; plus a 60 s pending reservation = 4,020; trial v2 = 6,480.
   Statement balance equals `available` once every due expiry is written.
5. An expiry job closes a lot past `expires_at` for its unallocated remainder
   once no reservation allocated to it is pending. Every capacity-lowering
   write, lot write and reservation takes the tenant admission lock. Times are
   UTC from the injected clock; month arithmetic uses the Asia/Kolkata calendar.
6. Periods. A verified monthly charge writes one `period_grant` lot of
   included minutes × seats × 60 for [start, end) (Organisation: end + one
   month rollover); a verified yearly charge writes twelve future-dated
   monthly lots at once, so access needs no scheduler. Copies never change
   with the catalogue. A failed renewal is a hard stop: no verified charge, no
   lot; a late retry writes that period's lot then. Cancel stops the next
   renewal at period end and leaves every lot untouched.
7. Top-ups need a valid `period_grant` lot and expire at the account's
   billing-year end, Personal and Organisation alike; they survive a cancel.
   Refund only within 7 days of verification and only with zero use allocated
   to the payment's lots: `refund_hold` closings under the lock, then the
   provider; a verified refund writes `refund` plus `refund_hold_release` and
   cancels renewal, a refused one the release only. Auto top-up is out of
   first-user scope. A recurring charge above ₹15,000 needs customer
   authentication each time (RBI e-mandate); the UI says so.
8. Plan in effect is the plan key of the latest valid `period_grant` lot,
   else `trial` while the trial lot is valid and unused, else none; it sets
   the per-call limit and features. Trial v2 (6,000 s or 14 days, 3,600 s per
   call) ships behind the `trial_policy` setting; v1 (3,600 s, 6,000 s per
   call) is the default and production stays on v1 until activation (S7).
9. Provider contract: `create_checkout`, `create_subscription`,
   `cancel_subscription`, `verify_event`, `fetch_payment`, `refund`; events
   `payment.captured`, `subscription.activated|charged|state`,
   `refund.processed|failed`. Only events whose amount, currency and plan match
   the copy create lots; a mismatch is `needs_review`. Money is integer paise.
10. Tenant authority: Personal, only the person; Organisation, only the owner
    role (admins and members read usage); staff act through
    `platform_billing_manage`, audited.
11. Accepted readings (L): an expired trial needs no stored closing, but the
    statement shows a derived "trial expired" line; a use stamped after the
    projection time still counts; refs `period:<id>`, `period:<id>:m<k>` (k =
    0–11), `order:<id>`, `legacy-grant:<audit_event_id>`; refundable while
    `now ≤ verified_at + 7 × 86,400 s`; calendar: fixed +05:30 (Asia/Kolkata).
12. Out of scope: auto top-up, seat changes and proration, plan upgrades,
    Enterprise self-serve, coupons, own GST invoices, other currencies, Stripe.

## Alternatives

- A stored `use` row, or access read from provider or order status: rejected;
  use would be counted twice and a redirect must never grant minutes.
- A scheduler for yearly periods, or grace minutes after a failed renewal:
  rejected in favour of future-dated lots and an honest hard stop.

## Consequences

- Migration 0062 (S1a) implements decisions 1–2: both tables with the kind
  and shape checks, the unique `source_ref` and `BEFORE UPDATE OR DELETE`
  triggers. The S1 code adds the projection (4), the derived trial and
  `trial_policy` setting (3, 8), the ledger service with legacy mirror and
  lock (2, 5), and admission reading the projection.
- Migration 0063 (S2a-1: orders, order and payment events, provider settings)
  completes `purchase` lots, refunds and the provider contract (7, 9); 0064
  (S2a-2: subscriptions, subscription events, periods) completes period lots,
  renewals and cancel (6, 8). S6 writes expiries (5); no live lot may expire
  before it ships. Contract C1 fixes the routes.

## Reversal cost

High. The ledger is financial and audit history under triggers that refuse
UPDATE and DELETE; a wrong row is superseded, never edited or removed.

## Evidence

[AUT-560](/AUT/issues/AUT-560); migration `20261001_0062`; `ac_platform/billing/`.

## Owner

Authority Closers product and platform security owners.

## Supersedes

The prepaid-only reservation of this number and the stored `use` entry of the
earlier AUT-560 brief. The plans catalogue ADR 0046 (AUT-418) is separate.

## Trigger to revisit

Revisit before auto top-up, seat changes, plan upgrades, a second currency, a
provider beyond Cashfree, or any change to what may create paid seconds.
