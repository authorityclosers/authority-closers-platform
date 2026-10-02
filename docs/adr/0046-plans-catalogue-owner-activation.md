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
