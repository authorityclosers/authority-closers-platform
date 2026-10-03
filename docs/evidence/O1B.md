# O1b: organisation create, rename and usage (AUT-651)

Contract: C2 in the AUT-560 plan (CTO amendment 2). Source base: `main` at `ee819d0`.
All data in the tests is fictional. No migration, capability or web change.

## Routes

| Route | Who | Result |
|---|---|---|
| `POST /v1/organisations` `{"name"}` | any signed-in account (sign-in needs an active person with a verified email) | 201 `{"tenant_id","name","role":"owner"}`; replay of the same key and body 200 with the same body |
| `PATCH /v1/organisation` `{"name"}` | owner of the selected organisation | 200 `{"tenant_id","name","role":"owner"}`, audit `organisation.renamed` with before and after |
| `GET /v1/organisation/usage?days=30\|90` | owner and admin: every active member; member: own row and own totals | 200 `{"since","total_seconds","total_calls","members":[{"person_id","name","seconds","calls","last_call_at"}],"pool":null}` |

Example usage response (fictional):

```json
{
  "since": "2026-09-03T07:40:00.123456Z",
  "total_seconds": 180,
  "total_calls": 4,
  "members": [
    {"person_id": "5b0c…", "name": "Fictional Rep", "seconds": 150, "calls": 3, "last_call_at": "2026-10-03T06:40:00Z"},
    {"person_id": "9a1d…", "name": "rep@example.test", "seconds": 30, "calls": 1, "last_call_at": "2026-10-01T07:40:00Z"}
  ],
  "pool": null
}
```

Refusals are `application/problem+json` with a `code`:

- 409 `organisation_limit`: the caller already owns three organisations.
- 409 `idempotency_conflict`: the `Idempotency-Key` was used with a different name.
- 422 `validation_failed`: name outside 2–80 characters, unknown body field, or a query other than `days=30` / `days=90`.
- 404 "No organisation selected." (rename, usage): Personal, operations, no selection or not a member, as in O1a.
- 403 `authorization_denied`: rename by an admin or member. 403 `request_origin_denied`: write without an allowed `Origin`.

## Choices made in this change

- `Idempotency-Key` is a canonical UUIDv4, as on the O1a member routes in the same file; the service keys commands by UUID.
- Usage `name` is the display name, or the email when the person has no display name, so it is always a string.
- Usage rows are the organisation's active members. Usage by a person who has since been removed is not in the rows or the totals.
- `last_call_at` comes from O1a `member_usage` and is the member's latest call in this organisation, also when it is older than the window.
- Seconds are the settled charged seconds, else the reserved seconds; a no-work settlement counts 0 seconds and 1 call.
- The three-organisation limit counts active owner memberships in registered organisations, under the person's row lock that write sign-in already holds. Operator creates (CLI, Platform Admin) pass no limit.
- A new organisation gets no minutes and no trial; eligibility is what AUT-436 gives every registered organisation.

## Tests

- `tests/unit/organisations/test_http.py`: create (exact body, replay, changed intent, one owner, context selection, fourth refused), invalid bodies on both writes, origin/session/key refusals, rename (audit, replay, admin 403, Personal 404), usage (exact schema, 30 and 90 days, settled/reserved/no-work, other tenant excluded, admin and member scope, unsupported queries), window boundary instant.
- `tests/unit/organisations/test_service.py`: owned limit with replay and operator create; rename owner-only, replay, conflict, protected tenants.
- `tests/integration/test_organisation_http_postgresql.py`: five sessions of one person race five creates on PostgreSQL (three 201, two 409 `organisation_limit`); select, rename with replay, usage; the new owner signs in by email code; audit chains valid.
- No web parser exists yet for these three routes (`apps/sales-xray-web/app/organisation/organisation-api.ts` has none), so there is no parser fixture to match.

Commands and results are in the pull request. Dev check after deploy: a fictional verified owner creates, selects and renames an organisation, then owner/admin and member read usage; record the deployed SHA and redacted responses on AUT-651.
