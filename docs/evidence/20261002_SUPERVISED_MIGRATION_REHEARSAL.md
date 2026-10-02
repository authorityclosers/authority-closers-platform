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

## Root result and fixture correction

The first Root run at source/test pin `94ffa3358d07e1b90d612c0fb07cc4520ecb5848` returned eight migration setup errors and 2840 passed / 5 failed / 1 skipped source tests. The failures were four synthetic cache probes that relied on mode 0500 preventing root writes and one stable-dump fixture that rejected Paperclip's acdev-owned scratch ancestor. Neither namespace catalogue could be read because disposable fixture authentication was absent; cleanup acceptance remains unverified. The sole source skip was intentionally disabled approved-dump integration. [Root receipt and sanitized logs](/api/attachments/7b4ea560-a420-4b27-8b44-0670cfc4743c/content?download=1).

Fixture correction commit: `0ee47344366325050b408e06a75772b93ca7c754`, on the existing owning branch. This supersedes the earlier test pin for the next Root run; candidate migration/application pin remains `7dc2a0af6d1c4864a6729021f3ef115a6be4f8cc`.

- Cache refusal now supplies a failing synthetic `mktemp` executable only for the unwritable-cache case. All four copied entrypoints must refuse before any repository request, independent of test UID.
- The root Docker permission fixture exempts only the outer ancestors of its pytest fixture directory from ownership checks. Generated directories and files keep real ownership checks; their root ownership is asserted whenever execution is actually root. A regression proves that the outer exception does not admit a generated directory with the wrong owner. Operational restore ownership policy is unchanged.
- Test-only scope extends to `tests/infra/test_postgres_backup.py` and `tests/infra/test_restore_drill.py` to resolve the five reported fixture failures. No migration, operational helper, host, service, authentication-policy or credential change was made.

Correction validation, as acdev with AC/PG variables excluded, TMPDIR set to PAPERCLIP_RUN_SCRATCH_DIR, PYTHONDONTWRITEBYTECODE=1, PYTEST_ADDOPTS='-p no:cacheprovider' and UV_NO_SYNC=1:

- `uv run ruff check tests/infra/test_postgres_backup.py tests/infra/test_restore_drill.py` and `git diff --check`: exit 0.
- `uv run pytest -q tests/infra/test_postgres_backup.py::TestResticCacheAndRetention tests/infra/test_restore_drill.py::test_permission_fixture_still_rejects_non_root_owned_generated_inputs tests/infra/test_restore_drill.py::test_executed_restore_uses_private_immutable_input_copies`: exit 0, 40 passed / 0 skipped on the final corrected test source.
- Before adding the ownership regression, the exact four-module source command above returned exit 0, 198 passed / 2648 skipped. Root-bound modules were skipped, as was the Docker permission proof because this acdev runtime cannot reach its daemon; approved-dump integration remained disabled. This does not replace privileged acceptance evidence.

[AUT-758](/AUT/issues/AUT-758) retains the authenticated Root execution and schema-cleanup prerequisite. The CEO owns approved disposable fixture authentication usable by the exact password-free URL and Alembic after AC/PG scrubbing. No additional execution authority is implied by these fixture corrections; the two exact contained commands still need successful receipts at the new pin before this draft can enter review.
