# ADR 0046: Plans catalogue with owner activation

- Status: accepted for the C1 catalogue foundation (AUT-418), 2026-10-02
- Scope: the `plans` table and model, its three coming-soon seeds, backup parity

## Context

The Sales Xray account card will show Personal, Organisation and Enterprise
plans. The owner has not activated any plan, prices are confirmed later (C3),
the platform must not invent a number, and billing sells by minutes only.

## Decision

1. One `plans` row per commercial plan: UUID id, unique key
   (`^[a-z][a-z0-9_]{1,39}$`), name, audience, status in `draft`,
   `coming_soon`, `active`, `retired`, revision, sort order, timestamps.
2. Every commercial or limit field is nullable and NULL means "not set":
   paise and cents prices (minor units, never negative), included minutes,
   seat minimum and maximum, longest call, retention days, rollover months.
   `per_seat` is a non-null boolean, false by default.
3. Feature keys are a JSON list of strings. Top-up packs are a JSON list of
   `{key, minutes, validity_rule, price_paise, price_cents}` with unique keys,
   strictly positive integer minutes and `validity_rule` exactly
   `billing_year_end`; any other rule or a `validity_days` field is refused.
4. Migration `20261002_0065` seeds `personal`, `organisation` and `enterprise`
   as `coming_soon`, revision 1, NULL prices and limits, empty lists. No
   Company, Trial or credit-unit row. The migration is forward-only.
5. Activation is an owner decision made later through Admin, never by code or
   seed. No route reads the catalogue in this slice.

## Alternatives

Seed confirmed prices now (values not owner-confirmed); a credit-unit table
(owner chose minutes only); JSON shape checks in SQL (not portable, so the
model validates in Python and the scalar rules are database checks).

## Consequences

Backup parity contract `ac-postgres-parity-v39` at head `20261002_0065` adds
`plans` (120 tables). C2 adds the public read, C3 the confirmed values.

## Reversal cost / Evidence / Owner / Supersedes / Trigger to revisit

- Reversal: low until activation, the table is unread; afterwards retiring a
  plan is a status change, never a delete.
- Evidence: `docs/evidence/20261002_PLANS_FOUNDATION.md`,
  `tests/unit/plans/test_models.py`, `tests/database/test_plans_postgresql.py`.
- Owner: CTO. Supersedes the combined AUT-418 scope (0061 reservation, credit
  units, offline contracts). Revisit when a second currency or a non-annual
  top-up validity is sold.

## C3 amendment (AUT-739, owner decisions relayed by CEO, 2026-10-03)

Migration `20261003_0068` advances only the exact untouched 0065 seeds to
revision 2, keeping `coming_soon`. It locks and checks all fixed seed fields;
an edited or missing seed raises `inactive catalogue seed changed; review required`
and rolls back. Applied migrations and order/subscription copies remain intact.

| Plan | Monthly / yearly paise | Minutes | Seats | Call minutes | GST included |
|---|---|---|---|---|---|
| Personal | 249900 / 2699000 | 800 | 1–1 | 90 | yes |
| Organisation | 1000000 / 10800000 per seat | 1000 per seat, pooled | 2–49 | 90 | no |
| Enterprise | 1000000 / 10800000 per seat | 1000 per seat, pooled | 50–NULL | 120 | no |

Personal stores `topup_100` (100 minutes, 29900 paise); the other plans store
`topup_500` (500 minutes, 129900 paise), all with `billing_year_end` validity.
Packs follow the plan's new `prices_include_gst` flag. All cents, retention and
rollover fields remain NULL. Only Enterprise has feature keys:
`long_calls_120`, `priority_support`, `onboarding_session`.
The public catalogue still hides inactive plan and pack prices. Tax calculation,
checkout totals and invoices belong to AUT-878; activation belongs to AUT-882.
Backup/restore parity adds the exact 0068 head with the same v40 inventory
(121 tables). Evidence: `docs/evidence/20261003_INACTIVE_PLAN_VALUES.md`.

## Admin price editor amendment (owner, 2026-10-29)

The owner judged ₹10,000 per seat "too harsh" and asked for a price per
salesperson based on our real costs, about ₹2k. He approved ₹1,999 per seat a
month and ₹19,990 a year for Organisation; Personal stays at ₹2,499 and
₹26,990. He chose to set prices himself in Admin ("Admin price editor") over a
data migration, so no migration changes a price.

- Admin → Economics → Plan prices shows each plan's current price and revision
  for that Admin's own environment. Each environment keeps its own prices.
- Only the owner can change a price. The allowlist is the AI budget ceiling's
  (`CEILING_OWNER_EMAILS`, verified email). The change goes through
  `PUT /v1/admin/plan-prices/{key}` with the revision read and a reason, after a
  confirm step that shows old and new.
- A change supersedes and never overwrites. The `plans` row takes the new
  monthly and yearly paise under a new revision. Checkout, `/v1/plans` and
  `/v1/me/plan` read it at once. Orders keep the price they copied, and
  provider plans are keyed by revision and amount.
- Each change also writes an append-only `plan_price_changes` row (migration
  `20261029_0143`) and a `plans.price_changed` audit event, both holding old
  and new prices, who and why. The ORM refuses updates and deletes.
- Only plans on sale or coming soon take a new price. Top-up prices, seats and
  GST are not edited here.
- Backup parity is `ac-postgres-parity-v110` at 0143: 0142's tables plus
  `plan_price_changes`.
- The Sales Xray display catalogue, which /plans shows while nothing is on
  sale, carries the approved Organisation price (₹1,999 / ₹19,990).
- Production takes the new price only when the owner sets it in production
  Admin after the release.

Evidence: `tests/database/test_plan_prices_postgresql.py`,
`tests/unit/http/test_plan_prices_route.py`,
`tests/infra/test_plan_price_changes_backup_parity.py`,
`apps/admin-web/app/economics/plan-prices.test.tsx`.
`scripts/billing/dev_purchase_journey.py` checks on dev that checkout charges
the catalogue's per-seat price.
