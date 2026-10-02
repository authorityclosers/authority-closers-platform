# AUT-756 pinned fictional migration rehearsal — 2026-10-02

Preparation evidence; privileged non-skip execution is pending. Candidate: `7dc2a0af6d1c4864a6729021f3ef115a6be4f8cc`; historical installed engine: `f051cb828dc0d19a2f09d7ce472a84a7e81a6d49`; task base: `b60b1836fef4d11846057ffa4d89f684ca784efd`; test Git blob: `5a27bc7a040685ec4cf55ba6c7397f852291b2b7`.

The new case extracts candidate migration/application source with `git archive` into pytest scratch and uses the existing random-schema harness. At 0053 it seeds six example.test persons, all five existing roles, all 15 existing platform/tenant/program grants with fictional audit rows, a program, tenant and job. After each explicit revision it compares every existing row, count and column shape. Only three empty organisation tables and nullable `jobs.failure_detail=NULL` are allowed. Savepoints test named constraints and preserve fixtures; invite uniqueness and direct forward-only downgrade refusal are covered without an Alembic downgrade.

Pinned backup, off-host restore-proof and application restore-drill source getters were loaded from `git show <candidate>:<script>` in run scratch, without running those operators. All three independently returned:

| Revision | Contract | Tables |
| --- | --- | --- |
| 0053 | ac-postgres-parity-v33 | 105 |
| 0054 | ac-postgres-parity-v34 | 108 |
| 0060 | ac-postgres-parity-v34 | 108 |
| 0061 | ac-postgres-parity-v35 | 108 |

Commands run in the devenv tool checkout, with AC/PG variables removed before migration commands and TMPDIR set to PAPERCLIP_RUN_SCRATCH_DIR:

- `AC_REQUIRE_MIGRATION_REHEARSAL_POSTGRES_TEST=1 AC_MIGRATION_REHEARSAL_POSTGRES_TEST_URL=postgresql://127.0.0.1:55432/ac_migration_rehearsal_fictional uv run pytest -q tests/integration/test_migration_rehearsal_postgresql.py`: exit 1, eight setup errors; the existing dedicated listener requires authentication. No schema was created. No inherited API database was used; the injected lane database on 55433 was excluded.
- Same command with the URL unset: exit 1, eight setup errors, exact message `AC_MIGRATION_REHEARSAL_POSTGRES_TEST_URL is required but not configured` verified. A scratch pytest case forcing the new case's migration result to 1 produced AssertionError and exit 1 (1 failed); this is a failure-propagation check, not PostgreSQL evidence.
- `uv run pytest -q tests/infra/test_capability_backup_parity.py tests/infra/test_postgres_backup.py tests/infra/test_postgres_restore_proof.py tests/infra/test_restore_drill.py`: exit 0, 198 passed / 2648 skipped; root-bound suites did not execute, so this is incomplete acceptance evidence.
- `uv run ruff check tests/integration/test_migration_rehearsal_postgresql.py` and `git diff --check`: pass. Root Operator owns the contained non-skip rerun, schema cleanup verification and exact logs. No host restore/proof run, provider, staging or production action was performed. Source compatibility is not installed-host compatibility. Normal pipeline dev SHA remains pending merge.

Implementation/test commit: `94ffa3358d07e1b90d612c0fb07cc4520ecb5848`; non-skip verification is tracked by [AUT-758](/AUT/issues/AUT-758), assigned to Root Operator. Generated source/test scratch is inside PAPERCLIP_RUN_SCRATCH_DIR and removed by the run harness at exit; database schema cleanup still needs a successful authenticated run. [Draft PR #184](https://github.com/authorityclosers/authority-closers-platform/pull/184) is not ready for review.
