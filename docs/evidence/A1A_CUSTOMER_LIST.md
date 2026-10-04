# A1a customer directory implementation evidence

Task: [AUT-652](/AUT/issues/AUT-652). Contract: AUT-560 plan revision 9
`d3daabe0-54f7-4052-bd30-83bb129ef7b7`, C2 and common C1 rules, copied into
AUT-652 plan revision `51686cad-4224-4132-a853-ed4db5f5a65d`.
Source base: `ef492fa5cf554858f0804708b5f02dafa6516c52`.

## Implemented boundary

`GET /v1/admin/customers` requires the configured Admin host, a real account
session, and a fresh canonical `platform_tenants_read` grant. Revocation takes
effect on the next read; an operations owner role alone does not grant access.
All success, validation, permission, authentication, and unavailable responses
carry `Cache-Control: no-store` and use the existing problem handlers.

The only query keys are `q`, `kind`, `status`, `cursor`, `limit`. Defaults are
all kinds, all person statuses, and 25 rows. Limits are 1–50. Empty `q` means no
search; other searches are 2–120 characters, case-insensitive literal email
prefix or display-name substring. Unknown/repeated keys and malformed cursors
return 422 `validation_failed`. Cursors encode the complete UTC timestamp and
UUID and use descending `(created_at, id)` keyset pagination.

Membership in the configured public learner tenant or a registered organisation
selects customers. Operations-only staff and unregistered tenants are excluded.
EXISTS selects each person once. Existing inactive membership rows still identify
customers; their membership state never becomes the canonical person's status.
Organisation summaries preserve canonical tenant names and roles. Missing
canonical identity text and session activity stay null.

Personal reads reuse `BillingLedger.project_person(..., mirror=False)`, the
projection used by AUT-417's acquisition allowance, with the configured trial
policy and operations grant provenance. Thirty-day committed use reuses its
`person_uses`: settled charges, pending reservations, claimed guests, and legacy
reservations. Other people, unclaimed visitors, and other tenants are excluded.
Org-only Personal is null. No target actor is fabricated; no `/me` endpoint is
called on another person's behalf. Missing configuration or an invalid canonical
projection returns 503 `customer_read_unavailable`; it never supplies a fake zero
or plan. SQL capture proves reads use SELECT only and create no billing accounts
or ledger entries.

Only the card's five files change. The source model/adapter is about 300 lines;
the complete receipt exceeds the original all-files estimate to include the
fictional PostgreSQL fixtures, acceptance checks, and exact A1b response.

## Verification

- `uv run pytest tests/integration/test_admin_customers_http_postgresql.py -q`
  — 3 passed; real disposable loopback PostgreSQL with fresh migrated schemas.
- `uv run ruff format --check packages/python tests` — 965 files formatted.
- `uv run ruff check packages/python tests` — passed.
- `uv run mypy packages/python` — 400 source files passed.
- Auth transactions/routes, platform access/organisations, operations routes
  and AUT-417 unit regressions — 193 passed.
- Existing AUT-417 and platform organisation PostgreSQL regressions — 4 passed.
- `ac-gate check` — passed for `task/platform/652-admin-customers`.
- CI and post-merge dev verification remain release/review checks. This receipt
  does not claim a merge or deployment.

Before implementation, unauthenticated `/health/live` and the directory route
on `https://admin-dev.authorityclosers.com` both returned edge 403 / error 1010,
with no application release header. No deployed SHA or authenticated customer
read could be verified. No credentials or real customer data were read. Once
merged to dev, check the release header against the merged SHA and repeat these
fictional fixtures with a permitted staff session, filtering kinds/status/search
and paging without duplicates. Browser/edge access is a follow-up, not merge
approval evidence.

## Source reads

Required source reads used exact IDs from the controlled source manifest, in
order: Master Index; BRD; AC-IMP-00/01/03/04/05. Then PRD, IA, UX Research,
UX States, UI System, SRS, Data/Tenancy, API/MCP, Security, QA, DevOps, Admin,
Telemetry, ADR/Risk and AC-UXA-01. They were read on 2026-10-04; the fetched
baseline documents retain their August 2026 revision dates. The newer pinned
C2 card supplies this task's field and authority contract. No raw founder
material or provider state supplies customer/access semantics.

## Exact fictional A1b parser fixture

Regenerated from the passing HTTP test's `a1b_customer_list_fixture` property.
This is the server response, with no fixture-only response fields.
Fixture file SHA-256: `bc56c4d36d5d5e14ca0194331f995b451744fb37b59698dc02e225b57b682272`.

```json
{
  "items": [
    {
      "created_at": "2026-10-01T12:00:00Z",
      "email": null,
      "last_active_at": null,
      "name": null,
      "organisations": [],
      "person_id": "00000000-0000-0000-0000-000000000006",
      "personal": {
        "available_seconds": 3600,
        "plan_key": "trial",
        "used_seconds_30d": 0
      },
      "status": "deleted"
    },
    {
      "created_at": "2026-10-01T12:00:00Z",
      "email": "suspended@example.test",
      "last_active_at": null,
      "name": "Fictional Suspended",
      "organisations": [],
      "person_id": "00000000-0000-0000-0000-000000000005",
      "personal": {
        "available_seconds": 3600,
        "plan_key": "trial",
        "used_seconds_30d": 0
      },
      "status": "suspended"
    },
    {
      "created_at": "2026-10-01T12:00:00Z",
      "email": "dual@example.test",
      "last_active_at": null,
      "name": "Fictional Dual",
      "organisations": [
        {
          "name": "Fictional Organisation",
          "role": "member",
          "tenant_id": "00000000-0000-0000-0000-000000000067"
        }
      ],
      "person_id": "00000000-0000-0000-0000-000000000003",
      "personal": {
        "available_seconds": 3600,
        "plan_key": "trial",
        "used_seconds_30d": 0
      },
      "status": "active"
    },
    {
      "created_at": "2026-10-01T12:00:00Z",
      "email": "organisation@example.test",
      "last_active_at": null,
      "name": "Fictional Organisation",
      "organisations": [
        {
          "name": "Fictional Organisation",
          "role": "member",
          "tenant_id": "00000000-0000-0000-0000-000000000067"
        }
      ],
      "person_id": "00000000-0000-0000-0000-000000000002",
      "personal": null,
      "status": "active"
    },
    {
      "created_at": "2026-10-01T12:00:00Z",
      "email": "personal@example.test",
      "last_active_at": "2026-10-01T12:01:00Z",
      "name": "Fictional Personal",
      "organisations": [],
      "person_id": "00000000-0000-0000-0000-000000000001",
      "personal": {
        "available_seconds": 3600,
        "plan_key": "trial",
        "used_seconds_30d": 0
      },
      "status": "active"
    }
  ],
  "next_cursor": null
}
```
