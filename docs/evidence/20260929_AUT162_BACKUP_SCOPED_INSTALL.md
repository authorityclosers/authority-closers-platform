# AUT-162 backup scoped installer evidence

- Added the reviewed backup/R2 target list and `AC_INSTALL_SCOPE=backup` install path. The path preserves `current`, records the scoped release, and rolls back installed files and the record together.
- Full installs retain their existing activation path and clear the backup scope record inside the transaction.
- Backup policy selection follows the scope record. Restore verification checks scoped targets against that immutable release and all other managed targets against `current`.
- `bash tests/infra/test-release-install.sh`: PASS.
- `bash tests/infra/test-security-invariants.sh`: PASS.
- `bash tests/infra/test-r2-usage-evaluate.sh`: PASS.
- `uv run --offline --locked --group dev pytest tests/infra/test_postgres_backup.py tests/infra/test_backup_orchestration_posix.py -q`: 77 passed, 12 subtests passed.
- `uv run --offline --locked --group dev ruff check infra/vps-foundation/scripts/ac-postgres-backup.py tests/infra/test_postgres_backup.py`: PASS.
- No host install was run; the task's host-only check follows both task merges.
