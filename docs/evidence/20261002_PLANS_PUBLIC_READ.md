# Plans C2: public catalogue read evidence (AUT-738)

`GET /v1/plans` reads the `plans` table (ADR 0046, migration 0065) with no
actor. It lists only `coming_soon` and `active` rows, ordered by `sort_order`
then `key`. `prices` is null unless the plan is `active`, and then carries
`monthly_paise`, `yearly_paise`, `monthly_cents`, `yearly_cents`. Top-up packs
of a non-active plan lose their `price_paise` and `price_cents` keys, even when
a stored price is set. `draft` and `retired` rows, ids and timestamps never
appear. Strict response models forbid extra fields. The response carries
`Cache-Control: public, max-age=60`, and the `public-plans-catalogue` rule
limits it like `public-program-catalog` (300 per 60 s). No schema, seed,
provider, order or access state is read or changed.

Local evidence on 2026-10-02 (billing lane checkout, loopback PostgreSQL test
database, fictional rows only):

- `uv run pytest -q tests/unit/plans/test_public_catalogue.py tests/integration/test_plans_public_postgresql.py`:
  **10 passed**. Unit tests cover redaction of stored prices and pack price
  keys, active prices (set and unset), refusal of `draft` and `retired`, the
  extra-field ban, the SQL filter and order, the empty list, the cache header
  and the rate-limit rule. PostgreSQL covers the three migrated seeds, an empty
  public set, every status, coming-soon rows with stored prices and priced
  packs, a `sort_order` tie broken by `key`, and the revision, all read without
  a cookie or header.
- `uv run pytest -q tests/security/test_rate_limits.py tests/security/test_community_rate_limits.py tests/unit/http/test_app_composition.py tests/unit/plans`:
  **74 passed**.
- `uv run ruff format --check packages/python tests`, `uv run ruff check packages/python tests`:
  clean. `uv run mypy packages/python`: no issues in 367 source files.
- Full stack: a fresh schema migrated to head, the real `create_app` under
  uvicorn, an anonymous `GET /v1/plans` answered HTTP 200,
  `cache-control: public, max-age=60`, and the three coming-soon seeds with
  `prices: null`. The schema was dropped afterwards.

Not claimed: no dev deployment check before merge (dev serves `main`), and no
visual QA; Cloudflare Access fronts the dev hosts, so the anonymous dev read is
checked after merge with an Access-authorised client.

Web contract gap: `apps/sales-xray-web/app/billing/contract.ts` refuses
unknown fields and its `PLAN_KEYS` list does not name `per_seat`, which this
card requires. The screen needs a one-line contract change (UI lane) before
it can parse the live response.
