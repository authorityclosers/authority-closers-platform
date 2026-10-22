# AUT-2203 — PostgreSQL restart recovery source; extension allocation pending

22 October 2026. Assigned source/test child of [AUT-2202](/AUT/issues/AUT-2202). Starting source includes parent `d6c1b9bce2179765c2fde039bb89e6598d54da1d`. This is an incremental implementation output, **not the completed, reviewed release prerequisite**. No live Postgres/service/schema/role/secret/settings operation, ship or release has been performed.

## Implemented recovery

`install-application-release.sh` now drains applications and fences writers against the existing release, then takes a custom-format `ac_backup` snapshot and verifies its archive listing before it restarts an existing PostgreSQL. The dump and append-only digest/source receipt are root-owned mode 0600; the dump is synced before the receipt is published, and the receipt directory is synced before restart. A publication/sync failure stops the restart. A published verified backup remains retained even if directory sync fails. First installation, which has no previous service, takes its snapshot after bootstrap and before schema changes.

Before write exposure, rollback restarts the previous release's PostgreSQL service/configuration with `--no-deps` before any SQL or snapshot restore. Database operations explicitly select the recovered release. A startup-only failure keeps the verified backup without restoring unchanged application data. A later pre-exposure schema failure checks the backup SHA256 again before restoring. Failure to recover old PostgreSQL or a changed checksum keeps access closed. Previous application services restart only after the database, release selector and edge route recover.

The existing post-write branch remains forward-only: contain ingress/services/writers and append `FORWARD_RECOVERY_REQUIRED`; do not restore the old database/application. Existing prepared/committed audit rows are retained, with new snapshot receipt/digest references. Existing production-metrics `compose_for` content is byte-for-byte unchanged.

## Privileged extension draft — deliberately not wired

`migrate-pg-stat-statements.sh` accepts no arguments, SQL filenames or extension names. It uses the existing PostgreSQL container's injected `POSTGRES_PASSWORD`, passed to libpq only inside that container. Fixed `psql -X --no-password --single-transaction` SQL requires the pinned PostgreSQL 18.6, preloaded library, `ac_owner`/`ac_platform`, and all three restricted roles. It creates only `public.pg_stat_statements` version 1.12, then verifies version/schema/owner even when already installed. No role creation, grants, role alteration, general migration execution, representative query reads or secret output.

The installer does **not invoke this draft**. No Alembic revision or number has been invented, and no bootstrap-without-versioned-migration activation is enabled. Existing Orchestrator 2 / Align 3 must return the migration number/down_revision and exact source-selection receipt. Final integration must include the versioned migration, this one fixed privileged pre-step before ordinary `ac_migrator` Alembic, normal migration/recovery policy compatibility and required SHA-bound CTO review/CEO admission. The migration-safety classifier currently treats raw SQL as unproven; it must retain its fail-closed behavior. No generic privileged or migration-safety bypass is supplied here.

## Executed verification

Command from shared dev/live:

```sh
uv run pytest -q tests/infra/test_postgres_release_recovery.py tests/infra/test_pg_stat_statements_migration.py tests/infra/test_application_release.py tests/infra/test_application_release_archive.py tests/infra/test_application_release_guards.py tests/infra/test_production_metrics_release.py
```

**220 passed, 3 skipped, exit 0, 25.39s.** Two new pinned-image extension tests were intentionally skipped without Root opt-in; one pre-existing Docker contract was skipped because the Docker daemon is unavailable to this seat. Ruff format/check, Python HTTP import, Bash/sh syntax and owned whitespace checks passed. These are fictional local/source proofs, not live PostgreSQL or production acceptance.

The executed shell failures cover dump/list/receipt failure before restart, published receipt sync failure, new-PG startup failure and old-config recovery, failed old-PG recovery, verified pre-exposure snapshot restore, checksum corruption refusal and post-write row preservation/append-only forward recovery. Updated existing rollback contracts distinguish PostgreSQL recovery from later application startup; their original refusal/ordering assertions remain.

Earlier run: 212 passed/8 failed/3 skipped because the existing archive harness lacked the new phase flags and assumed all prior-release `up` commands were application restarts; the corrected harness asserts old-PG recovery before SQL and all existing refusal branches. An initial new-test harness classified runtime grants as fencing because it matched the whole embedded command; corrected to inspect its access-mode argument. These adverse logs are retained, not silently discarded.

## Actual pinned-image proof still required

A single read-only image inspect returned Docker socket permission denied for this Platform seat. No socket permission/settings changes, root impersonation or repeated access attempts were made. The new opt-in fixture uses only the existing pinned image, network none, fictional roles/data and no host mounts; it removes its own container. Root must run the exact committed test file through its authorized wrapper, retain complete exit/output and return the source/digests on this child (or its concrete fictional-proof child). The test proves absent/already-installed extension, unchanged role flags/memberships, ordinary migrator refusal (42501), least-privilege already-installed passage, denied ownership/drop and wrong-existing-owner refusal.

```sh
AC_POSTGRES_LAUNCH_DOCKER_TEST=1 uv run pytest -q /home/acdev/src/dev-live/authority-closers-platform/tests/infra/test_pg_stat_statements_migration.py
```

Pinned image: `postgres@sha256:1c59e2c3c818eaa0f0628f695b36e7c9e362d6b219b36a54a32df645cbd7e1af`.

## Coordinator custody and remaining prerequisite

Exact request was appended to `/home/acdev/strikes/2122/INBOX.md` before editing the nonoverlapping installer recovery hunks. Its historical claim covers production-metrics selection in `compose_for` only; that function is unchanged. Source allocation/receiving request was appended to `/home/acdev/strikes/coord/INBOX.md` for existing Orchestrator 2 / Align 3. **Dispatch is recorded; receiving acknowledgment, migration allocation, final source selection, CTO review and CEO admission have not been returned.** No claim of acceptance or release readiness is made.

Root remains the sole host/release executor on the parent; no parent mutation is needed to read this source output. Parent must not restart live PostgreSQL on the strength of this partial receipt. Final extension/recovery source selection and review remain required. No indexes or billing/provider/account/HELD/timer changes.

Retained evidence: `/home/acdev/strikes/2203/evidence/`. Temporary test files are run-owned under `PAPERCLIP_RUN_SCRATCH_DIR`.

Initial source SHA256 (commit `aaf81fb5821c376ad3f544e5b653aaca9a4dd54c`):
- `infra/application/scripts/install-application-release.sh`: `62a33eca57f5f410cde9d02ce38e4ce18b27bd518f74f022c9e540f360b16f62`
- `infra/application/scripts/migrate-pg-stat-statements.sh`: `27943140d082aa5a9028394996326f6dacc7d31845283391b2f62a46212fee6e`
- `tests/infra/test_postgres_release_recovery.py`: `2881f007b9c10b329fe3aecb2949c9585262c9e900860ce4d054a6fb25855e18`
- `tests/infra/test_pg_stat_statements_migration.py`: `79d20c8601e628f1bb4662000389ea53b8894abea45969060a537a91989f348a`
- `tests/infra/test_application_release_archive.py`: `f27ba084426489da56a40e9397aa72eda4afaa3369a0c963d3c93122543ca560`

PostgreSQL primary references: [CREATE EXTENSION privileges, IF NOT EXISTS caveat and explicit version/schema](https://www.postgresql.org/docs/18/sql-createextension.html); [preload and per-database SQL objects](https://www.postgresql.org/docs/18/pgstatstatements.html). Actual final extension tests remain pending; documentation is not execution evidence.

## CTO wake: close an authentication-proof gap

The CTO's comment `0e99e4ab-6299-44fc-ad00-74c77a82e08a` correctly withholds approval. The coordinator and Platform inboxes still contain no migration allocation, receiving/source-selection acknowledgment or authorized extension-image result. The shared head at inspection was the initial source commit above. No final numbered integration or release PR is claimed; workbench rules reserve release PR creation to the authorized release owner.

The extension fixture previously used trust authentication, which could accept an incorrect owner password. The two pending Docker tests now set a fictional owner password, require SCRAM for that owner's IPv4 connection **inside the disposable container only**, observe incorrect-password refusal, and then invoke the fixed migration script with its injected password. During asynchronous configuration reload, the refusal probe executes only `SELECT 1`, preserving the absent-extension case. Existing restricted-role and wrong-extension-owner assertions remain. This fixture correction has not been executed against Docker by Platform and must be included in the authorized executor's final proof.

Executed local checks: `uv run pytest -q tests/infra/test_pg_stat_statements_migration.py tests/infra/test_postgres_release_recovery.py` — **15 passed, 2 skipped, exit 0, 1.80s**. This includes new missing/empty-password refusal before connection and inherited-shell-trace protection. Both isolated-image tests remain skipped, not passed. Ruff format/check, HTTP import and owned whitespace checks pass. Retained receipt: `/home/acdev/strikes/2203/evidence/cto-wake-verification.json`.

Updated extension test SHA256: `ea73dbe587f9a7eb4d288e4fe56b347181fee898ba00ac32b662b11ca4a759c0`. Installer and privileged-script bytes are unchanged from the initial source hashes. The existing coordinator must supply the allocated revision/down_revision and receiving/source selection; the authorized isolated-image executor must return the final test result. Platform then integrates and submits the complete exact source for CTO review and CEO admission. Root remains the sole live restart/release executor on [AUT-2202](/AUT/issues/AUT-2202).
