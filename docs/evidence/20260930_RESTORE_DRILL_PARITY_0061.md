# Restore parity for migration 0061

Migration `20260930_0061` follows `20260930_0060` (0055–0059 stay reserved).
It adds one nullable JSON column, `jobs.failure_detail`, that the inference
worker writes in the same transaction as the job failure record (schema
`ac.job-failure-detail/1`: stage, failure code, inner code, validator revision,
rule site and pydantic field paths; never call, transcript or report content).
Downgrade raises `forward-only`; the model builds on SQLite and PostgreSQL.

The three separately packaged PostgreSQL backup, restic restore-proof and
application restore-drill catalogs now recognize exact head `20260930_0061` as
`ac-postgres-parity-v35`. The migration adds no table, so the inventory is the
0060/0054 set of **108 representative tables**; row-count parity is unchanged
and the new column rides along in the same `jobs` dump. Exact migration
identity remains mandatory: an older-head snapshot cannot prove head 0061.

Local evidence on 2026-09-30 (sales-xray lane checkout, fictional data only):

- Failure-detail builder, diagnostics and stage-routing unit tests, the
  versioned parity catalog assertions, model registry and release-head tests:
  see the pull request for the pytest counts.
- The PostgreSQL worker tests (`tests/database/test_conversation_failure_detail_postgresql.py`)
  and the migration regression (`tests/integration/test_job_failure_detail_migration_postgresql.py`)
  need a disposable loopback database with schema-create rights. Neither the
  sandbox runtime nor the migrator role may create schemas, so those run in the
  CI PostgreSQL service only.
- The root-only `test_capability_backup_parity.py` restore drills were skipped
  in this non-root checkout; the control-plane CI gate runs them.

This is code-level parity evidence only. No host backup or live restore drill
was run for 0061.
