# Plans C1: catalogue foundation evidence (migration 0065)

Migration `20261002_0065` adds the `plans` table (ADR 0046) and seeds
`personal`, `organisation` and `enterprise` as `coming_soon`, revision 1, with
every price and limit NULL, empty feature and pack lists and `per_seat` false.
No route reads the table yet (C2); no values are confirmed yet (C3). The three
separately packaged backup, restic restore-proof and application restore-drill
catalogues recognise exact head `20261002_0065` as `ac-postgres-parity-v39`,
extending the 0064 inventory (119 tables, v38) by `plans` to **120 tables**.
Earlier contracts and inventories are unchanged; unknown heads stay fail-closed.

| Head | Contract | Tables |
|---|---|---|
| `20261001_0064` | `ac-postgres-parity-v38` | 119 |
| `20261002_0065` | `ac-postgres-parity-v39` | 120 (adds `plans`) |

Local evidence on 2026-10-02 (api lane checkout, loopback PostgreSQL test
database, fictional data only):

- `uv run pytest -q tests/unit/plans/test_models.py tests/database/test_plans_postgresql.py tests/database/test_model_registry.py tests/infra/test_ac_release.py`: **134 passed**.
  SQLite proves the model round trip, the key, pack and feature-key validators
  and every scalar CHECK; PostgreSQL proves 0065 follows 0064 and is the head,
  no model drift, the three seeds, the PostgreSQL key regex and the other
  checks on raw inserts, and that `downgrade()` raises `forward-only`.
- `tests/infra/test_capability_backup_parity.py`: all 2731 cases skip for a
  non-root user by design; the root CI gate runs them. The two versioned
  contract assertions were executed directly in Python and pass for head
  `20261002_0065` (120 tables, `ac-postgres-parity-v39`).
- `uv run ruff format --check`, `uv run ruff check` on `packages/python`,
  `tests`, the migration and the three infra scripts: clean.
  `uv run mypy packages/python`: no issues in 365 source files.
- Dev sandbox: `uv run alembic upgrade head` moved the dev database from
  `20260930_0061` to `20261002_0065` (0062 to 0064 were main's pending billing
  migrations). Read-back shows the three seeds with NULL prices and limits.

This is code-level parity evidence only. No host backup, live restore drill or
migration rehearsal pair was run for 0065. The PR must say that this migration
changes the foundation backup tools (parity contract bump).
