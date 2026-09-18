# Provider activation restore parity

Migration `20260914_0039` adds the append-only
`conversation_provider_activations` table. The application restore drill,
foundation PostgreSQL backup, and Restic restore-proof helpers now share the
reviewed `ac-postgres-parity-v19` contract: the 0039 table is appended to the
0038 table set, giving the release 94 canonical row-count tables.

The explicit migration rehearsal is `20260914_0038` to `20260914_0039`. It
accepts no source derivations and requires the new table to be empty in the
isolated target before the migration runs. Unknown heads and unreviewed
transitions remain rejected.

Validation on 2026-09-14:

- `tests/infra/test_capability_backup_parity.py tests/infra/test_restore_drill.py` — **1087 passed, 2 skipped**.
- `tests/infra/test_database_runtime_privileges_postgresql.py::test_backup_role_can_read_all_migrator_tables_and_sequences` — skipped because `AC_TEST_DATABASE_URL` is not configured.
- `tests/infra/test_application_release.py::test_release_is_built_off_host_and_installed_with_backup_and_rollback` — passed.
- `git diff --check` — passed.

The privilege check is source-backed: both PostgreSQL bootstrap paths grant
`ac_backup` default `SELECT` on tables and `USAGE, SELECT` on sequences, so a
new Alembic table created by `ac_migrator` inherits read access. No live
database, provider, deployment, or runtime mutation was performed here.
