# AUT-1741 item 1: migration-safety CI

Implementation baseline: `2e662a8538a31d3086076ba98dd6026bd3a2b20e`.
Architecture: Paperclip AUT-1741 `decision`, revision
`83bcefc8-8d1b-49f6-8099-77ca165fb682`.
Lane: platform. Tier: non-routine; this is the CEO's bounded end-to-end item 1.

## Delivered behavior

- The separate staging schema exporter reuses the backup tool's validated release,
  credential transport, exported snapshot, environment lock and bounded command.
  Its dump explicitly uses `--schema-only --no-owner --no-acl`; full backup code
  remains unchanged and is held by another open PR.
- Exported metadata binds the schema dump checksum, PostgreSQL version, exact
  snapshot Alembic revision, staging release SHA and UTC export time. Failed
  exports remove their partial pair. The operator command validates by default;
  `--apply` performs the read-only export.
- The gate requires a governed manifest SHA independently of the downloaded
  bundle, verifies both files, rejects exports older than 24 hours or dated in the
  future, and requires the staging revision to equal the PR base migration head.
  The candidate must extend one complete revision chain without editing history.
- A random disposable localhost PostgreSQL container uses the existing pinned
  repository image and fictional credentials. Archive inspection rejects row,
  sequence and materialized-view data, large objects and external database
  objects before restore. PostgreSQL major-version mismatch fails.
  The three application role names from the local fixture contract exist only as
  NOLOGIN aliases in the disposable database, for schema policy references.
- The restored schema receives only its manifest Alembic version row. The gate
  upgrades, downgrades, compares schema, and upgrades again. It also compares the
  two upgraded schemas. Normalization removes only paired outer pg_dump random
  tokens; it preserves function text, comments and whitespace.
- Missing downgrades fail. Added columns with server defaults and ordinary or
  implicit index builds on pre-existing tables fail conservatively. Indexes on
  newly created empty tables and explicit concurrent index builds are accepted.
  Raw SQL and unsupported upgrade helpers fail because their lock safety cannot
  be established from empty schema evidence.
- Migration connections have 2-second lock and 30-second statement timeouts;
  subprocesses and container readiness are also bounded. Cleanup removes only
  the random container created by this run.
- The workflow always emits the named `migration-safety` result and a one-line
  summary. Unrelated PRs pass without reading a staging artifact. Its real Docker
  tests use fictional schemas, including a failing no-op downgrade and a full
  backup rejected before restore.

## Verification in the platform checkout

```sh
uv run --frozen pytest tests/infra/test_migration_schema_gate.py tests/infra/test_postgres_schema_export.py tests/unit/test_migration_safety.py
uv run --frozen ruff check scripts/ci/migration_schema_gate.py infra/vps-foundation/scripts/ac-postgres-schema-export.py tests/infra/test_migration_schema_gate.py tests/infra/test_postgres_schema_export.py
uv run --frozen python scripts/ci/migration_schema_gate.py --base-ref origin/main
pnpm exec prettier --check .github/workflows/migration-safety.yml
ac-gate check
```

The local pytest receipt is **85 passed, 3 skipped**. The three real PostgreSQL
cases require Docker, whose socket is denied to the local lane operator. The
workflow requires those cases with `AC_REQUIRE_SCHEMA_GATE_DOCKER_TEST=1`, so
they cannot silently skip in the named CI job. The CLI's irrelevant-PR receipt is
`migration-safety: PASS (no migration changes)`. CI receipts are attached to the
PR; local test results do not certify CI, installed settings or deployed state.

## Governed artifact and activation handoff

Root remains the operator through AUT-63. From the reviewed source, Root runs
the schema exporter against the exact staging release, then publishes only
`schema.dump` and `manifest.json` at the root of a repository Actions artifact.
No staging credential or full backup is supplied to a PR runner.

```sh
python3 infra/vps-foundation/scripts/ac-postgres-schema-export.py --output <new-absolute-export-directory>
python3 infra/vps-foundation/scripts/ac-postgres-schema-export.py --output <new-absolute-export-directory> --apply
```

Root records the artifact ID and SHA-256 of `manifest.json` in governed repository
variables `AC_MIGRATION_SCHEMA_ARTIFACT_ID` and
`AC_MIGRATION_SCHEMA_MANIFEST_SHA256`. The workflow resolves the source run from
the exact unexpired artifact ID before downloading, as required by the pinned
[download action](https://github.com/actions/download-artifact/blob/d3f86a106a0bac45b974a628896c90dbdf5c8093/action.yml).
Refresh after a staging migration-head
change and within the 24-hour evidence window. Missing, expired or inaccessible
artifacts fail relevant PRs. A staging head behind current main needs a refreshed
staging artifact; it cannot be substituted by a generated main schema.

Before merging/activating this workflow, Root must provide the artifact route so
new migration pushes do not fail main on missing evidence. Required-check
installation/read-back and positive/negative staging-artifact receipts remain
governed operations, not claims made by this implementation PR. No host,
GitHub setting, release, staging or production operation was performed here.

Items 2–4 and overall delivery remain open. This PR changes neither authorization
expectations nor watchdog policy and does not make a check required through
repository settings. Policy relaxation still waits for both required checks,
exact-head demonstrations, installed policy and deployed version receipts.
