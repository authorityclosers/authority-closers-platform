# E9: Read all account notifications

Task: [AUT-1001](/AUT/issues/AUT-1001). Source pin:
`2be03e2a9e021a4fee0496df3546e30edf3743ea` (main, 6 October 2026).

Scope choice: implement the backend command required by E9's mark-all-done
control. The notification feed returns the latest 50 entries, including read
ones, but its unread count covers the full history. A client acknowledging only
returned IDs cannot clear older unread entries. This slice adds the full-account
command; [AUT-474](/AUT/issues/AUT-474) retains the shared client, store, bell,
What's new and corner-card UI ownership.

Allowed files: `packages/python/ac_platform/http/product_updates.py`,
`packages/python/ac_platform/product_updates/reading.py`,
`tests/unit/http/test_product_updates_http.py`,
`tests/unit/product_updates/test_reading.py`,
`tests/integration/test_product_updates_reading_postgresql.py`, and this evidence.
No open PR overlapped these files at the pre-edit check. The admin checkout was
clean, and the latest-main gate admitted `task/admin/1001-settings-notifications`.

## Contract and behavior

- `POST /v1/notifications/read-all` requires the explicit JSON body `{}` and
  returns `{"unread_count": <current count>}`. Missing bodies, recipient IDs,
  entry IDs and other fields receive 422. The existing selected-ID
  `/v1/notifications/read` command and four original contracts remain intact.
- Uses the existing signed-in actor, Sales Xray host check, safe-origin write
  guard, authenticated transaction and `private, no-store` response policy.
  A selected workspace is not required; the account owns these receipts.
- Marks all currently visible note lineages seen through conflict-safe,
  append-only receipts. Visibility uses the existing environment, audience,
  tester and feature rules, without the feed's 100-note or 50-entry limits.
- Sets `read_at` only on the actor's unread product events. Existing timestamps
  and notification contents are preserved. Repeated commands are idempotent.
  The response reads the current count; later activity can create unread entries.
- The command runs within the caller's existing transaction. A rollback
  restores both note receipts and event read state. It creates no delivery
  preference, compulsory category, event producer or external channel.

## Verification

`uv run --frozen pytest tests/unit/product_updates
tests/unit/http/test_product_updates_http.py
tests/unit/http/test_app_composition.py tests/unit/http/test_route_registry.py
tests/database/test_product_updates.py
tests/integration/test_product_updates_reading_postgresql.py -q`:
**213 passed**, including all **3 PostgreSQL integration tests** on the lane's
disposable database and isolated migrated schema.

Coverage includes more than 100 visible notes and 50 events, hidden audiences
and features, staging/development visibility, other accounts, another session,
repeat commands, preserved historical timestamps, later unread activity, and
transaction rollback. HTTP checks cover unauthenticated requests, wrong hosts,
forged forwarded hosts, unsafe origins, body validation, private headers and
application route discovery. All test people, events and reports are fictional.

- Repository Python Ruff lint: passed.
- Repository Python Ruff format check: passed (1,041 files).
- Repository Python mypy: passed (430 source files).
- `git diff --check` and latest-main `ac-gate check`: passed.
- PR admission and CI are recorded in the task handoff.

## Sources and deployed check

This continuation uses the E9 owner card, ADR 0054, the existing P2 service and
HTTP contracts, and [P2 evidence](AUT-469-product-updates-read-api.md). The first
E9 slice's [source intake](AUT-1001-settings-profile-first-slice.md) records the
completed controlled-source fetch. This is a bounded extension of that service.

Before editing, dev GET `/settings` returned HTTP 302 to Cloudflare Access.
Signed-in dev and staging acceptance remain unverified. No deployment or live
data change was made. The web's exact rewrite list and shared client do not yet
include the new path; their next UI wiring slice must add it before using the
command through the standalone web server.

After the backend release reaches dev, use a fictional account through its
existing authenticated QA API path. Create more than 50 fictional notifications
in a disposable fixture and record the full unread count. POST `{}` with the
actual safe Sales Xray Origin to `/v1/notifications/read-all`; the current count
should clear. Read back from a second session of that account and verify a
second fictional account remains unread. Repeat the command and verify original
read timestamps remain unchanged. New activity should appear unread afterward.
These are check instructions, not a request to seed a deployed database manually.

## Remaining E9 scope

This PR delivers the backend command only. Pane/client/rewrite wiring,
notification preferences and their compulsory delivery rules, photo upload,
E10 analytics entries, per-version email/Telegram delivery and signed-in dev
acceptance remain open. E9 is not complete; review this slice without closing
the epic.
