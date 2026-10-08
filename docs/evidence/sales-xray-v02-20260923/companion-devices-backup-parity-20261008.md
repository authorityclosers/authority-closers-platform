# Companion device storage and backup parity — AUT-1557

Source baseline: `df769bac0ddb5d70880a0db382834503fb4c149e` (merged prospect
tags, PR #399), approved ADR 0055 (PR #402).

| Migration head | Predecessor | Contract | Tables |
| --- | --- | --- | --- |
| `20261008_0078` | `20261007_0077` | `ac-postgres-parity-v49` | 137 |

The four additional tables store device membership bindings, hashed pairing
attempts, refresh families and hashed access/refresh/web-session credentials.
Database checks reject plaintext credentials and invalid expiry bounds; a trigger
preserves credential payloads and spent-token timestamps across rotation. The
submission capture-source column is nullable and has no default or backfill.
It is mapped on `ConversationGuestSubmission`; card 6 owns its writers. The ORM
mapping was moved to the owning model in the CTO-requested revision below.

All three separately packaged backup/restore catalogues recognise the new head
and retain historical mappings, including prospect tags (v48, 133 tables).
These contracts attest table inventories and row counts, not individual values
or a live restore. Install foundation tools from this reviewed source before
applying the migration through the release train in deployed environments.

Verification on 2026-10-08:

- Database migration/registry and release-tool/prospect-tag catalogue tests:
  214 passed. The database tests use disposable PostgreSQL schemas and include
  full registry drift, exact constraint rejections, immutable credential
  rotation history and legacy NULLs.
- Root-owned backup parity tests were skipped, not passed (4,118 skips in the
  initial collection). Three pure assertions from that module were then run
  directly after reconciling the full historical inventory expectations:
  `test_three_separately_packaged_helpers_have_identical_versioned_contracts`,
  `test_compatibility_head_catalogue_contains_only_actual_checked_in_revisions`,
  and `test_versioned_contracts_match_all_new_migration_tables_exactly`.
  All passed: v49, 137 tables, one checked-in linear migration head.
- Required Python formatting, lint and mypy checks passed; migration and
  foundation-tool formatting/lint passed. No screen files changed.
- Using `~/.config/acdev/database.env`, `uv run alembic upgrade head` applied
  `0076 -> 0077 -> 0078` to the fictional loopback local dev database. Readback
  confirmed `20261008_0078`, all four companion tables and nullable capture
  source without a default.
- FastAPI's real lifespan started from this branch against that local dev DB;
  `/health/ready` returned HTTP 200 with
  `{"status":"ready","release_id":"local-unreleased"}` through TestClient.
  This is branch startup evidence, not a deployed release claim.
- The shared dev API on `127.0.0.1:8100`, using the dev application Host,
  remains ready on release `ce753781ba69f9b2e74b9300619473173bab2be1`.
  The hosted `https://salesxray-dev.authorityclosers.com/health/ready` request
  encountered Cloudflare Access (302). After merge/release, verify the hosted
  dev API serves the merged build and migration head; this remains pending.

Reproduce focused checks from the API lane:

```sh
uv run pytest -q tests/database/test_companion_devices_postgresql.py tests/database/test_model_registry.py tests/infra/test_ac_release.py tests/infra/test_prospect_tags_backup_parity.py
uv run ruff format --check packages/python tests
uv run ruff check packages/python tests
uv run mypy packages/python
uv run python - <<'PY'
from tests.infra import test_capability_backup_parity as parity
parity.test_three_separately_packaged_helpers_have_identical_versioned_contracts()
parity.test_compatibility_head_catalogue_contains_only_actual_checked_in_revisions()
parity.test_versioned_contracts_match_all_new_migration_tables_exactly()
PY
```

Supply the explicit disposable loopback `AC_TEST_DATABASE_URL` for database
checks without printing its value. Sensitive review requires CTO review followed
by CEO approval; the watchdog owns merge. Native routes, capture-source writers,
activation flags and staging/production changes remain outside this card.

CTO delta verification on 2026-10-08 (after review of `95cf0c4`):

- PostgreSQL regex and interval constraints in the registry now use
  `.ddl_if(dialect="postgresql")`. Portable hash length checks still apply on
  both dialects. The PostgreSQL migration SQL remains unchanged. Its regex
  checks already enforce exact length; the registry drift proof allows exactly
  the three redundant metadata length constraints and rejects any other drift.
- `capture_source` and its allowed-value CHECK now belong to the mapped
  `ConversationGuestSubmission` class. Registry mutation was removed. SQLite
  ORM readback covers NULL and `chrome_tab`, and rejects `inferred`.
- SQLite registry, database certificates, certificate services and certificate
  HTTP tests: 34 passed. This exercises full registry creation, including all
  four companion tables, and verifies rejection of short hashes.
- Disposable PostgreSQL companion storage tests: 8 passed. Release-tool and
  prospect-tag parity tests: 199 passed. Three pure catalogue assertions passed
  again. Formatting, lint and mypy passed. Root-owned/live restore proofs were
  not repeated or claimed.
- Branch FastAPI lifespan and `/health/ready` were checked again against the
  existing fictional loopback database: HTTP 200, `status: ready`, release
  `local-unreleased`; readback remains `20261008_0078`. No migration was applied
  again. The TestClient used the allowed loopback Host. Hosted merged-head
  verification still requires the reviewed release.
- The credential DELETE-history concern was recorded separately in Intake
  Ledger AUT-1618 for a later card, as the CTO directed. The existing UPDATE
  trigger and migration are unchanged by this revision.

Reproduce the SQLite regression checks:

```sh
uv run pytest -q tests/database/test_model_registry.py tests/database/test_certificates.py tests/unit/certificates/test_services.py tests/unit/http/test_certificate_routes.py
```
