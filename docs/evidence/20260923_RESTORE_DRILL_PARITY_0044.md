# Restore-drill parity contract for migration 0044

Migration `20260923_0044` adds `c5_coaching_prompt_revision` and
`report_language_default` to `conversation_analysis_settings` and adds check
constraints on those values. It does not add or remove a table, so it does not
change the set of tables whose row counts the restore drill compares.

The restore drill now recognizes this head with the next versioned contract,
`ac-postgres-parity-v24`, using the exact table set already reviewed for
`20260915_0043`. The canonical PostgreSQL backup writer and restore-proof
controller carry the same v24 mapping. The cross-module contract test asserts
all three mappings are identical and migration 0044 retains the 98-table set.
The contracts for `0042` and `0043` remain unchanged. This keeps parity
fail-closed for unknown heads while allowing backup and restore validation for
the current migration.

The restore-only regression failed before the mapping was added with
`migration head has no reviewed row-count parity contract`. The shared
backup/proof catalogue regression also failed before both canonical mappings
were synchronized. After the fix, the control-plane parity, backup, restore
proof, and restore-drill suites passed together: 1,498 passed, 9 skipped.
Ruff checks passed for the changed Python scripts and infra tests. The skips
are platform-specific checks, an unavailable pinned PostgreSQL image, and the
restore-drill integration test that requires explicit opt-in with an approved
dump.
