# Restore parity for migration 0062

Migration `20261001_0064` adds `billing_accounts` and `billing_ledger_entries`
(ADR 0052, billing slice S1a). Both tables carry `BEFORE UPDATE OR DELETE`
triggers, so a restored copy must hold exactly the rows the source held. The
three separately packaged PostgreSQL backup, restic restore-proof, and
application restore-drill catalogs now recognize exact head `20261001_0064` as
`ac-postgres-parity-v36`, extending the 0060 inventory (108 tables, contract
v34) by those two tables to **119 tables**. Contracts v2–v34 and their
inventories are unchanged; unknown heads stay fail-closed.

Local evidence on 2026-10-01 (WSL Ubuntu, run as root, loopback PostgreSQL
test database, fictional data):

- `tests/infra/test_capability_backup_parity.py`: **2312 passed**, 1 skipped.
  The root gate was satisfied, so the metadata and restore-parity checks ran;
  the one skip is the historical controller Git object absent from a fresh
  clone. The versioned-catalog assertion inspects the checked-in 0062
  migration for its created tables and confirms equality across all three
  catalogs for every head from 0018 to 0062.
- `tests/infra/test_ac_release.py`: **89 passed**. The release engine accepts
  a bundle at head `20261001_0064` once the foundation backup tool knows it
  and refuses it before then.
- `tests/database/test_model_registry.py`: **6 passed**; the model registry
  matches every migrated table including the two billing tables.
- `ruff format --check` and `ruff check` pass for the six changed Python files
  and `ruff check` passes for all of `infra` and `tests/infra`. Three untouched
  files under `infra/` already fail `ruff format --check` on the base branch
  (`install-sales-xray-native.py`, `install-sales-xray-startup-recovery.py`,
  `media-safety/manage.py`); the CI ruff gate covers `packages/python` and
  `tests`, and those files are outside both this change and that gate.

This is code-level parity evidence only. No host backup, live restore drill,
or migration rehearsal pair was run for 0062. The PR must say that this
migration changes the foundation backup tools (parity contract bump).

Migrations 0063 and 0064 (orders, payment events, provider settings, command idempotency, subscriptions, subscription events, periods, refund events) ship in the same change; the contract counts all eleven billing tables at head `20261001_0064`.
