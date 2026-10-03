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
