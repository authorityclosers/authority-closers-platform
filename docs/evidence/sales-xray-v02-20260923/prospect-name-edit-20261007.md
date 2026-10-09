# AUT-1504: person-entered prospect name edit

Source: `956f5a42389595b1bd4389d296f691bb74cfd1b6`; branch `task/sx-prospects/1504-prospect-name-edit`. AUT-1506 repaired the generated checkout drift; the checkout was clean and latest-main gate reported sx-prospects FREE/main green before start. Start and check passed.

Size decision: keep the single endpoint and its required admission, concurrency, rollback and query-count proof together (about 500 lines); the implementation is about 100 lines and the exact four-file scope is unchanged.

`PATCH /v1/conversation/prospects/{UUID}` uses the configured host, safe Origin, authenticated transaction and session-selected served workspace. Both request keys are required, extra keys/query parameters are rejected, and JSON is bounded to 2048 bytes/5 seconds. Name: strict string, 1–160 input characters, trim edges, reject blank. Revision: strict positive integer. Errors/success are private/no-store and vary by Cookie, including malformed UUID errors.

The existing authorised query is restricted to the current owner and locks/refetches the prospect row. Revision is checked before no-op handling. Changed names increment revision once, update the existing clock timestamp and atomically append `conversation.prospect_name_changed`. Audit contains only `field`, `previous_revision`, `current_revision`; revisions are strings. Identity, sources, historical events and memberships stay intact. An audit failure rolls back the edit. Missing/foreign/read-only targets share 404; stale saves return 409: “The prospect changed. Reload before saving again.”

Request and exact success shape (fictional illustration):

```json
{ "display_name": "Mehta Example Updated", "expected_revision": 1 }
```

```json
{
  "schema": "ac.sales-xray.prospect-name/1",
  "prospect": {
    "prospect_id": "22222222-2222-4222-8222-222222222222",
    "name": "Mehta Example Updated",
    "revision": 2
  }
}
```

Use existing detail `prospect.revision` before saving, then refresh list/detail/search. No UI edit control is delivered here; the UI Maker owns wiring.

Validation: all **18 tests passed** in 253.45 seconds across `test_prospect_profile_edit_postgresql.py`, `test_prospect_store_postgresql.py`, `test_prospect_library_postgresql.py` and `test_prospect_confirmation_postgresql.py`, using the explicit disposable loopback PostgreSQL test URL without printing it. Successful authenticated edits execute **23 SQL statements with both 1 and 25 memberships**, including auth/admission/audit. A separate row-lock proof preloads a stale ORM row, observes the competing transaction blocked in PostgreSQL, then requires 409 after the winning commit. Full Python Ruff format/check pass; mypy passes for 434 source files. Latest-main `ac-gate check`, `git diff --check` and evidence Prettier check pass. GitHub CI is separate and must pass before merge.

Runtime baseline, 7 October: public dev `/prospects` returns 302 to Cloudflare Access. An authenticated journey/serving web release SHA cannot be verified in this builder run. Read-only local API `/health/live` with configured dev Host reports `ce753781ba69f9b2e74b9300619473173bab2be1`; this loopback API is not the public dev API upstream. Active Caddy configuration on :3016 and the sx-prospects preview configuration explicitly proxy `/v1/*` to `https://salesxray-staging.authorityclosers.com`, preserving its Host. The staging API release SHA is not available without protected access. The lane web source pin is the source SHA above, not proof of the public serving release. No runtime write was attempted on this unverified upstream.

After governed merge and normal delivery, Chief of Staff routes verification to the authorised fictional runtime operator: record web/API build SHAs and actual environment; use an owned retained fictional call's explicit create path if needed; read revision; PATCH; refresh list/detail and literal search; verify stale save 409 and cross-person/workspace denial. Repeat on staging after that same merged build deploys. Record sanitized status/JSON and audit evidence. Disposable loopback tests are not dev/staging acceptance; authenticated runtime checks and merged delivery remain outstanding.
