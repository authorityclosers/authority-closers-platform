# PostgreSQL restore-drill runbook

This harness is an opt-in evidence tool for a custom-format PostgreSQL dump.
It never connects to staging or production. It restores only into a newly
created PostgreSQL 18 container with:

- a generated Docker-managed state volume;
- a generated internal Docker network with no egress; and
- a generated database and role identity.

The backup is mounted read-only. The target has no public or loopback-published
port; the application-image probe reaches it only across the generated
internal Docker network.
Generated resources are removed in a `finally` cleanup path. If cleanup fails,
the run is failed and the exact generated resource names are reported for
operator inspection; no unresolved or broad path is removed.

## Preconditions

1. Use a reviewed custom-format `pg_dump` from the named environment. A plain
   SQL dump is rejected by `pg_restore --list`.
2. Supply the exact paired JSON metadata produced by `ac-postgres-backup`.
   The harness verifies its environment, release, byte count, SHA-256, source
   row-count parity manifest, and capture timestamp against the dump; file
   modification time is never used. The backup writer obtains the dump and
   every source parity count from one bounded repeatable-read exported
   PostgreSQL snapshot. Off-site proof additionally compares the restored row
   counts with that source manifest.
3. Run the stdlib-only host script from the exact reviewed application release
   with Python 3.12/3.13 and Docker. Supply the immutable local API image ID
   recorded by that release; the application dependencies execute only there.
   A source-checkout run is accepted only when the backup release ID, Git HEAD,
   exact application-image release marker, checked-in migration head, and the
   image's single Alembic head all agree. Source mode additionally requires the
   exact Git worktree root to contain no staged, unstaged, or untracked files
   before and after identity resolution. A stripped release applies the same
   binding through `RELEASE-COMMIT` and sealed `release-images.env` identities.
4. Keep `AC_EXTERNAL_SIDE_EFFECTS_HOLD=true` in any application environment.
   The harness itself does not start the application API or worker.

The `--environment` value labels the evidence and is intentionally not a
connection selector. There is no source DSN argument. The harness cannot
mutate staging or production data because it never opens a connection to
either environment.

## Default dry-run

Dry-run validates the backup/metadata pair, evidence path, embedded migration
head, immutable image identity syntax, and reconciliation acknowledgement rules. It hashes the backup for
evidence planning but does not create Docker resources or write evidence:

```bash
python3 infra/application/scripts/restore-drill.py \
  --environment staging \
  --backup /absolute/path/to/staging-postgres.dump \
  --backup-metadata /absolute/path/to/staging-postgres.json \
  --evidence-dir /absolute/path/to/new/restore-drill-evidence \
  --application-image sha256:<64-lowercase-hex-characters>
```

## Execute the drill

Executed runs copy the already validated dump and metadata into a generated,
root-owned `0700` directory below
`/var/lib/authority-closers/restore-drill-inputs`. The no-follow, exclusive
metadata copy is root-only `0600`. The root-owned dump is `0640` inside the
root-only `0700` parent; the isolated PostgreSQL container receives exactly the
dump's numeric group as a supplemental read group and the bind mount remains
read-only. Device, inode, size, modification time, and change time must remain
stable throughout each source read. Both initial SHA-256 identities must match
the copied pair before it is revalidated and Docker can consume it. Signals are
held through cleanup; the generated files are removed whether the drill passes
or fails. This closes the gap in which a caller could replace or mutate an input
after validation.

Only add the two explicit opt-in flags after reviewing the dry-run output:

```bash
python3 infra/application/scripts/restore-drill.py \
  --environment staging \
  --backup /absolute/path/to/staging-postgres.dump \
  --backup-metadata /absolute/path/to/staging-postgres.json \
  --evidence-dir /absolute/path/to/new/restore-drill-evidence \
  --application-image sha256:<64-lowercase-hex-characters> \
  --execute \
  --acknowledge-isolated-target
```

The evidence directory must be new. The harness refuses repository/workspace
paths, filesystem roots, an existing evidence directory in execute mode, and
an existing generated Docker resource name.

The run performs these checks in order:

1. PostgreSQL server version and target database/role identity are verified.
2. `pg_restore --list` validates the custom format, then the dump is restored
   with `--no-owner --no-acl` into the empty target.
3. The Alembic version and canonical table set are checked.
4. Safe representative row counts and durable job/outbox/recovery invariants
   are collected without selecting payloads, addresses, tokens, or receipts.
5. `ac_platform.outbox.mark_database_restore()` is called. This is the
   sanctioned recovery boundary: it advances the generation and atomically
   holds pending outbox intents and uncertain external-effect jobs.
6. The worker is prepared with a recording provider that raises if called.
   The held durable state must make `prepare()` false and `run_once()` reject;
   provider calls must remain zero.
7. Optional reconciliation may release exactly the IDs supplied on the
   command line. No command releases all held work.
8. The evidence records observed RPO age and restore-to-proof RTO in seconds,
   alongside the 15-minute and 1-hour target comparisons.

## Selected reconciliation

Reconciliation is disabled unless at least one job or outbox ID is named,
actor and tenant UUIDs are supplied, and the explicit acknowledgement is
present. The repository's `reconcile_operations()` boundary performs the
same-transaction audit and tenant checks. Example shape (use only IDs from
this drill's restored evidence and review each one):

```bash
python3 infra/application/scripts/restore-drill.py \
  --environment staging \
  --backup /absolute/path/to/staging-postgres.dump \
  --backup-metadata /absolute/path/to/staging-postgres.json \
  --evidence-dir /absolute/path/to/new/restore-drill-evidence \
  --application-image sha256:<64-lowercase-hex-characters> \
  --execute \
  --acknowledge-isolated-target \
  --reconcile-job-id 00000000-0000-0000-0000-000000000000 \
  --reconcile-actor-person-id 00000000-0000-0000-0000-000000000000 \
  --reconcile-tenant-id 00000000-0000-0000-0000-000000000000 \
  --reconcile-reason "reviewed restore-drill selected set" \
  --acknowledge-reconciliation
```

The all-zero values above are placeholders and must not be used. If the
selected record is absent, not held, or outside the selected tenant, the
transaction fails closed. Unselected held records remain held and the global
recovery state remains held.

## Evidence and objective assessment

Use `docs/evidence/POSTGRES_RESTORE_DRILL_EVIDENCE.md` as the human review
cover sheet and retain the generated JSON beside it. The JSON contains no
secret values. Review:

- `rpo_observed_seconds = drill start time - metadata-backed backup_captured_at`;
- `rto_observed_seconds = drill completion time - restore start`; and
- whether each observed value is within the 900-second RPO and 3,600-second
  RTO targets.

RPO is not proven by a successful restore alone: the paired metadata and the
off-host snapshot identity must be independently reviewed. A failed or
missing cleanup result is an operational failure even when database checks
pass.
