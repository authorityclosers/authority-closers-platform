# Restore parity for migration 0053

Migration `20260930_0053` adds `person_google_profiles`. The three separately
packaged PostgreSQL backup, restic restore-proof, and application restore-drill
catalogs now recognize exact head `20260930_0053` as
`ac-postgres-parity-v33`, extending the 0052 inventory by that table.

Local evidence on 2026-09-30:

- PostgreSQL Google sign-in and profile erasure integration tests: **3 passed**.
- Restore-drill, release-head, and identity-tenancy suite: **203 passed**;
  two existing Docker/opt-in restore checks skipped.
- Versioned migration/parity catalog assertion passed for all known heads,
  including exact migration table detection and equality across all three
  catalogs. The 0053 inventory contains **105 tables**.
- The root-only `test_capability_backup_parity.py` pytest suite was skipped in
  this non-root checkout. The root control-plane CI gate must run that suite.

This is code-level parity evidence only. No host backup or live restore drill
was run for 0053.
