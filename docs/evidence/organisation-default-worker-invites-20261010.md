# Organisation invitations: actual default-worker repair

This supersedes the missing-worker-registration limitation in the earlier
invitation evidence. The reviewed base was
`7dfdfc1adb4aead0b11879031367d75161d77c5a`. The CEO's bounded ownership amendment
and Root's completed handoff receipt permit only this invitation integration.

The default worker now registers the exact invitation event and UUID-only
payload, its email dispatcher and preparation allowlist, and its deferred
canonical invitation resolver. The bounded telemetry vocabulary accepts the
same job kind. Existing recovery, provider-idempotency and dispatch fences run
on this path. No generic email route or new access rule was added.

The PostgreSQL journey no longer injects a custom route or calls the resolver
directly. HTTP creation and invitation enqueue work through `DurableWorker`,
the shipped registry and `build_default_dispatcher` with fictional mail. It
checks delivery, durable acknowledgement/provider key, command and worker replay,
pending invitation listing, explicit acceptance and workspace selection. Isolated
worker cases prove revoked, expired and wrong-tenant jobs dead-letter without
mail; retry does not send and the audit chain remains valid. Existing accept/revoke
and paid-seat races remain covered. No real mail or customer data is used.

Actual repository-tree checks, 10 October 2026:

- `ac-heavy uv run --offline pytest tests/database/test_organisation_invites_postgresql.py -q`:
  **7 passed in 174.61s**.
- `uv run --offline pytest tests/unit/worker/test_worker.py tests/unit/telemetry -q`:
  **61 passed in 16.61s**. The first broad run exposed a second exact allowed-kind
  assertion absent from the candidate patch; it was corrected before this pass.
- Ruff check and format check pass for all four changed Python files.
- Targeted mypy passes for the worker and telemetry source files.
- The existing api gate permits continuation; the initial working tree was clean,
  local HEAD matched PR #426, and both direct strike services had no running PID.

Tested-file SHA-256 values:

| File | SHA-256 |
| --- | --- |
| `packages/python/ac_platform/worker/__init__.py` | `d11fd00920b8b361392ea75b2c137514f1bdcba284b5f0a676db2176a5677330` |
| `packages/python/ac_platform/telemetry/models.py` | `9ce0ad4163cc5a960cb4d4ee8df74414885c642f303bfee4039c0fe31ab780f2` |
| `tests/unit/worker/test_worker.py` | `e1fd490f184f6578eafc059a43976f0bdeabcffb073c4a77ba846b6dcd852123` |
| `tests/database/test_organisation_invites_postgresql.py` | `030eec38aedc4943e9c16748590f1f7f95fe83e1e1dacf4a6a4de34a4945b518` |

Dev entry: <https://salesxray-dev.authorityclosers.com/organisation>. The public
entry returned 302 to Access; this is reachability, not authenticated journey
evidence. Paperclip has no managed execution preview attached to this issue.
Final-head CI and authorised authenticated dev proof are still required before
CTO re-review and CEO approval. The merge hold remains.

API shapes are unchanged by this repair. Join-screen wiring, default processing
admission and call-placement/read/prospect integration remain separate pending
strike work. No move endpoint, staging call movement, live provider activation,
host/service change, migration, merge or release is claimed here.
