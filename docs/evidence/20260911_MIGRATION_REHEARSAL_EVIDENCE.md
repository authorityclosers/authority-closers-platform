# Prior-head migration rehearsal evidence — 2026-09-11

Status: **prepared; no migration rehearsal has been executed**. This document
records the release-gate contract implemented for the reviewed
`20260910_0027` → `20260910_0029` transition. It is not evidence of a passed
restore, and it does not supersede the existing 0027 restore evidence.

## Invocation contract

The paired custom-format dump and metadata must describe the same immutable
backup at migration head `20260910_0027` (`ac-postgres-parity-v7`). The source
application image must independently attest the backup release and that exact
head. The candidate application image must independently attest the selected
workspace release and migration head `20260910_0029` (`ac-postgres-parity-v9`).
The source release is not relabeled as the candidate release.

Dry-run shape:

```text
python3 infra/application/scripts/restore-drill.py \
  --environment staging \
  --backup /absolute/path/to/staging-postgres-0027.dump \
  --backup-metadata /absolute/path/to/staging-postgres-0027.json \
  --evidence-dir /absolute/path/to/new/migration-rehearsal-evidence \
  --application-image sha256:<candidate-image-id> \
  --source-application-image sha256:<prior-0027-image-id> \
  --source-migration-head 20260910_0027
```

Execute only after reviewing the dry-run output and confirming that the
candidate image and both backup artifacts are locally available:

```text
<same command> --execute --acknowledge-isolated-target
```

The command has no source DSN and opens no connection to staging or
production. Reconciliation arguments are invalid in rehearsal mode.

## Required generated-evidence checks

- New PostgreSQL 18 target, generated database/role, internal-only network,
  no published ports, and exact-label cleanup completed.
- Source schema has exactly the reviewed 0027 canonical table set and its
  restored row counts match the paired metadata.
- Source hold uses the sanctioned recovery boundary. The preservation
  baseline is collected **after** the hold transition; this permits the
  intentional job/outbox/audit state changes caused by holding work.
- Source row counts remain unchanged across the candidate migration.
- `20260910_0028` derivations are checked from restored source data: one
  `community_public_profiles` row per distinct `person_id` and one
  `academy_leaderboard_preferences` row per legacy academy profile.
- `20260910_0029` creates an empty `app_update_read_receipts` table; no
  reconciliation is run.
- Target Alembic identity is exactly `20260910_0029`, recovery state remains
  held at the same generation, and the candidate `prove-held` worker proof
  reports `worker_ready=false`, `run_once_rejected=true`, and
  `provider_calls=0`.
- `external_connections` is empty, `operation_gate.status` is `passed`, and
  both cleanup and RPO/RTO objective results are recorded.

## Implementation/test evidence

The bounded mode is implemented only in:

- `infra/application/scripts/restore-drill.py`
- `packages/python/ac_platform/recovery/restore_drill_probe.py`
- `tests/infra/test_restore_drill.py`
- `tests/unit/recovery/test_restore_drill_probe.py`
- `tests/integration/test_migration_rehearsal_postgresql.py`

The mode runs the candidate's exact Alembic entrypoint only inside the
disposable target and retains the ordinary single-image restore-drill
contract unchanged. The opt-in PostgreSQL regression test is intentionally
separate and must use a dedicated disposable local test database; it must
never receive an API database URL.

Read-only validation in this preparation pass: Ruff check and format check
passed; the owned restore/probe suite passed (`63 passed, 2 deselected`, with
the Docker/live opt-ins excluded); the dedicated PostgreSQL regression was
skipped because `AC_MIGRATION_REHEARSAL_POSTGRES_TEST_URL` was not configured.
No Docker daemon, live fixture, SSH session, API, package install, or remote
write was used.

## Review record

- Rehearsal run ID: `<not run>`
- Source backup SHA-256: `<record only after approved run>`
- Source metadata SHA-256: `<record only after approved run>`
- Source release ID: `<record only after approved run>`
- Candidate release ID: `<record only after approved run>`
- Generated evidence JSON: `<record only after approved run>`
- Cleanup: `<not run>`
- Objective assessment: `insufficient — rehearsal not executed`
