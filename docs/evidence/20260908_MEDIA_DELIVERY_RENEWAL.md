# Delivery-only renewal — local implementation evidence

Normal authenticated `GET /v1/activities/{id}` remains the descriptor boundary.
The DTO is unchanged. A grant is reused only while expiry is later than
`now + min(30 seconds, configured TTL / 5)`; otherwise a new same-scope grant is
appended with the unchanged configured TTL. Prior grant rows and original URL
expiry remain unchanged. All derivatives share their grant's original window.

Issuance locks the persisted identity session before resolving approved media
and requerying grants. The public descriptor resolver now accepts the existing
AsyncSession, performs domain work through `run_sync`, and appends the canonical
`media.activity_delivery_granted` audit in the same transaction. Audit payloads
contain scope identifiers and predecessor ID, never tokens or signed URLs.
Only the exact activity GET dependency is function-scoped so failed commit
cannot expose a usable-looking successful descriptor. Other learning routes and
watch-evidence semantics are unchanged.

## Verification

- `uv run pytest -q tests/unit/media tests/unit/http/test_learning_routes.py tests/unit/http/test_app_composition.py`: **460 passed**.
- `uv run pytest -q tests/unit/learning tests/unit/http/test_learning_routes.py tests/unit/media/test_activity_delivery_authorization.py`: **82 passed**.
- `uv run pytest -q tests/integration/test_media_delivery_renewal_postgresql.py`: **2 passed**, actual loopback PostgreSQL, fresh random test schema, migrated and cleaned up by the fixture. Existing owner role used; no role grants or public-schema mutation.
- `uv run mypy packages/python/ac_platform`: **156 source files clean**.
- Scoped Ruff lint/format and diff whitespace checks passed.
- Independent scoped backend review reported no Critical/Important finding;
  the reviewer inspected source and tests without rerunning these suites.

PostgreSQL acceptance observes actual transaction blocking before the second
request reuses one committed renewal, then checks unchanged predecessor, stable
scope/TTL, shared caption grant, and the canonical audit chain. A separate
explicit TEST-only evidence policy proves delivery rotation leaves an existing
watch session, expiry, intervals, and coverage unchanged; that same session then
accepts the next legitimate heartbeat sequence. SQLite HTTP acceptance proves
audit rollback and deferred commit failure do not expose a success response.

Earlier runtime and migrator role attempts correctly lacked CREATE SCHEMA and
stopped before schema creation. No privileges were modified. A preliminary
SQLite continuity fixture encountered SQLite's naive timestamp round trip and
was replaced by the actual PostgreSQL proof, without changing evidence code.

No server restart, deployment, browser acceptance, live long-film playback,
provider activation, or local film evidence-policy activation is claimed here.
