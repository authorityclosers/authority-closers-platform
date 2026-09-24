# Email acknowledgement migration backup coverage

Migration `20260924_0048` adds the email challenge's explicit age-acknowledgement
flag. The backup, restore-proof and application restore-drill tools now recognize
that exact schema head under `ac-postgres-parity-v28`.

The table catalogue remains the existing 100 tables because this migration adds
a column, not a table. Historical head mappings are preserved. These parity
checks compare the migration head and table row counts; they do not claim to
compare every column value or prove a live restore.

## Local validation

- `pytest tests/infra/test_capability_backup_parity.py tests/infra/test_restore_drill.py -q`:
  **1,703 passed, 2 skipped**, 112.54 seconds.
- The Docker restore test was skipped because the daemon is unavailable.
- The approved-dump integration test was not opted in.
- Ruff on the four changed Python files and `git diff --check` passed.

Release packaging must include the foundation tools from the same exact
successor source. Install them through the canonical foundation activation path
before applying migration 0048; the older foundation catalogue cannot attest
the new head. The migration's database behaviour still requires the exact-source
PostgreSQL CI suite and deployment acceptance. No production state was changed
by these local checks.
