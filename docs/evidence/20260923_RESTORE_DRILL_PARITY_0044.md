# Restore-drill parity contract for migration 0044

Migration `20260923_0044` adds `c5_coaching_prompt_revision` and
`report_language_default` to `conversation_analysis_settings` and adds check
constraints on those values. It does not add or remove a table, so it does not
change the set of tables whose row counts the restore drill compares.

The restore drill now recognizes this head with the next versioned contract,
`ac-postgres-parity-v24`, using the exact table set already reviewed for
`20260915_0043`. The contracts for `0042` and `0043` remain unchanged. This
keeps parity fail-closed for unknown heads while allowing restore validation
for the current migration.

The new regression failed before the mapping was added with
`migration head has no reviewed row-count parity contract`. After the fix:

- `tests/infra/test_restore_drill.py`: 87 passed, 2 skipped.
- `ruff check` on the restore-drill script and infra tests: passed.
- The two skips require either the pinned PostgreSQL image or an explicit
  restore-drill integration opt-in with an approved dump.
