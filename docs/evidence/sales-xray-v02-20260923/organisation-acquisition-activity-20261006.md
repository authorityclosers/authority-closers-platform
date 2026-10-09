# AUT-1392: organisation completed-analysis activity

Source main: `fb42844f9214748dd26847788f696a64702e2dd2`.
Contract: AUT-1391 plan revision `e3cf7141-bf97-435a-9755-341d847e3c4d` and CTO comment `30e3181a-2f20-4b91-a514-66b9cafb7d36`.
Implementation/test commit: `aca854fd4901966483632c942f63531d222bc076`.
Branch: `task/api/1392-organisation-activity`. Final PR/head and CI state are recorded on AUT-1392; no merged or released SHA exists yet.

`GET /v1/conversation/acquisition/organisation/activity` reuses read-only sign-in, the session-selected served workspace, account admission with shared identity locks, and the existing live owner/admin boundary. One grouped settlement/usage/tenant-bound claim/person query returns IST current/previous 30-day receipt totals. Counts survive recording deletion, exclude canaries and unattributed guests, use charged seconds, and preserve former owners. Names follow display-name/masked-email policy and name/ID ordering. Personal activity and retained-call `/v1/organisation/activity` are separate, unchanged contracts.

Size choice under the current Act/Unjam instruction: keep this single receipt endpoint and its specified acceptance coverage together, approximately 430 changed code/test lines in the four approved files; no second implementation area or scope expansion.

## Verification on 6 October 2026

- `ac-gate status`: main green, API FREE. Started through `ac-gate start api 1392-organisation-activity`; `ac-gate check` passed before edits. The API checkout was clean. Open PRs #366, #363, #361, #360, #356 and #348 had no overlaps with the five allowed paths.
- Focused command below: **7 passed, 0 skipped, 25.99 seconds**. Both PostgreSQL modules actually ran against injected loopback disposable test URLs; their harnesses created/migrated/removed unique schemas. Credentials were never printed.
- Organisation proof: owner/admin equality, member/former-member/Personal/operations/foreign-session denials, previously loaded admin membership demoted with the same identity/session; completed versus no-work/unsettled/unclaimed/canary receipts; no recording dependency; reserved seconds deliberately exceed charged seconds; IST midnight/lower/upper boundaries, 30 ordered zero-filled days and empty output; previous-only former/masked owners; equal name/ID sort ties with different volumes; daily/person/organisation sum equality and tenant isolation.
- SQL capture measures six admission/live-authority SELECTs, then exactly one grouped receipt SELECT. Empty and larger people/day datasets retain the same count; all captured statements are SELECTs. HTTP composition uses the existing read-only authentication dependency; its auth-query overhead is owned by that existing dependency.
- HTTP checks on both hosts cover exact top-level fields, session-selected organisation passed to ownership, shared identity locks, private/no-store and Cookie headers, 401/403 mapping, unsupported query rejection and 405 for POST. Existing personal HTTP/database and retained organisation database regressions pass.
- `uv run ruff format --check packages/python tests`: **1038 files already formatted**.
- `uv run ruff check packages/python tests`: **All checks passed**.
- `uv run mypy packages/python`: **Success, 429 source files**.
- Initial attempts exposed an invalid async-generator mock, a missing fictional cross-tenant membership, and a dev-URL override passed to the regression harness. Corrected the mock/fixture and used the run's injected disposable URLs. The dev database schema-create attempt was denied; no application data was changed. Only the final passing results above count as acceptance.

```bash
uv run pytest tests/database/test_conversation_acquisition_activity_postgresql.py tests/unit/http/test_conversation_acquisition_activity_route.py tests/integration/test_organisation_activity_postgresql.py -q
uv run ruff format --check packages/python tests
uv run ruff check packages/python tests
uv run mypy packages/python
ac-gate check
```

## Dev and staging

Before edits, `https://salesxray-dev.authorityclosers.com/v1/conversation/acquisition/activity` returned HTTP 302 without a fictional session. No approved authenticated owner/admin/member sessions were available to this run. Authenticated before/after dev behavior, known-fixture live totals and live demotion are **not verified**; disposable PostgreSQL and ASGI proofs are recorded separately. No session, membership or application data was manually changed on dev/staging.

After the governed merge/release, check the above dev origin and `https://salesxray-staging.authorityclosers.com`: sign in with the approved fictional owner/admin session, select its organisation, GET the new route and compare with known completed receipts; repeat as member/ex-admin for 403; GET personal `/activity` to confirm its existing shape. Record the actual released SHA. Staging verification is pending the existing release flow. No deployment, migration, billing or runtime setting changes are part of this PR.

## Complete fictional response from the passing PostgreSQL test

Fixture clock: `2026-09-29T12:00:00Z`. The response below is captured from the production function after exact assertions; these are disposable fictional identities, not deployed organisation data. Current totals: 6 analyses, 320 charged seconds; previous total: 4. `days` always has 30 entries; `people` can be empty and otherwise has only owners represented by receipts in either window.

```json
{
  "timezone": "Asia/Kolkata",
  "days": [
    {"date": "2026-08-31", "analysed": 1, "analysed_seconds": 45},
    {"date": "2026-09-01", "analysed": 0, "analysed_seconds": 0},
    {"date": "2026-09-02", "analysed": 0, "analysed_seconds": 0},
    {"date": "2026-09-03", "analysed": 0, "analysed_seconds": 0},
    {"date": "2026-09-04", "analysed": 0, "analysed_seconds": 0},
    {"date": "2026-09-05", "analysed": 0, "analysed_seconds": 0},
    {"date": "2026-09-06", "analysed": 0, "analysed_seconds": 0},
    {"date": "2026-09-07", "analysed": 0, "analysed_seconds": 0},
    {"date": "2026-09-08", "analysed": 0, "analysed_seconds": 0},
    {"date": "2026-09-09", "analysed": 0, "analysed_seconds": 0},
    {"date": "2026-09-10", "analysed": 0, "analysed_seconds": 0},
    {"date": "2026-09-11", "analysed": 0, "analysed_seconds": 0},
    {"date": "2026-09-12", "analysed": 0, "analysed_seconds": 0},
    {"date": "2026-09-13", "analysed": 0, "analysed_seconds": 0},
    {"date": "2026-09-14", "analysed": 0, "analysed_seconds": 0},
    {"date": "2026-09-15", "analysed": 0, "analysed_seconds": 0},
    {"date": "2026-09-16", "analysed": 0, "analysed_seconds": 0},
    {"date": "2026-09-17", "analysed": 0, "analysed_seconds": 0},
    {"date": "2026-09-18", "analysed": 0, "analysed_seconds": 0},
    {"date": "2026-09-19", "analysed": 0, "analysed_seconds": 0},
    {"date": "2026-09-20", "analysed": 0, "analysed_seconds": 0},
    {"date": "2026-09-21", "analysed": 0, "analysed_seconds": 0},
    {"date": "2026-09-22", "analysed": 0, "analysed_seconds": 0},
    {"date": "2026-09-23", "analysed": 0, "analysed_seconds": 0},
    {"date": "2026-09-24", "analysed": 0, "analysed_seconds": 0},
    {"date": "2026-09-25", "analysed": 0, "analysed_seconds": 0},
    {"date": "2026-09-26", "analysed": 0, "analysed_seconds": 0},
    {"date": "2026-09-27", "analysed": 1, "analysed_seconds": 90},
    {"date": "2026-09-28", "analysed": 1, "analysed_seconds": 120},
    {"date": "2026-09-29", "analysed": 3, "analysed_seconds": 65}
  ],
  "analysed_last_30_days": 6,
  "analysed_previous_30_days": 4,
  "people": [
    {"person_id": "024f088d-0a56-4a14-9b20-8030bca6df9a", "name": "Alex", "analysed_last_30_days": 1, "analysed_seconds_last_30_days": 15, "analysed_previous_30_days": 0},
    {"person_id": "86d585ee-3ff7-4761-b7eb-fbb425a7bef3", "name": "Alex", "analysed_last_30_days": 0, "analysed_seconds_last_30_days": 0, "analysed_previous_30_days": 1},
    {"person_id": "017e41d8-11bc-4e5e-8fb0-9f054b6faded", "name": "Zoe", "analysed_last_30_days": 5, "analysed_seconds_last_30_days": 305, "analysed_previous_30_days": 2},
    {"person_id": "38c9fb71-e1a5-4c8b-9201-3c7a6dbef259", "name": "m***@example.test", "analysed_last_30_days": 0, "analysed_seconds_last_30_days": 0, "analysed_previous_30_days": 1}
  ]
}
```
