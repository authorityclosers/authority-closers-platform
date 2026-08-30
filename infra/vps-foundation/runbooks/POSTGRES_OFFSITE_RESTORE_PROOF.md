# Off-site logical PostgreSQL restore proof

`ac-restic-postgres-restore-proof@.service` proves one environment's newest
off-site logical PostgreSQL snapshot. It is read-only with respect to Restic
and never opens a connection to staging or production. The only database it
creates is the exact disposable target owned and cleaned by the immutable
application release's `scripts/restore-drill.py`.

The proof helper fails closed unless the Restic query returns exactly one
newest, fresh snapshot carrying `authority-closers-postgres-logical` and
`environment=<staging|production>`. It lists the snapshot before restoring and
accepts exactly one capture directory containing only `backup.dump` and
`metadata.json`. The pair is restored with two exact `--include` paths into a
root-owned bounded temporary tree, then copied through a private no-follow
stable staging path as the restore drill's exact `backup.dump` + `backup.json`
sidecar contract before Docker receives it. Metadata capture time must be
within the same 15-minute RPO as the proof clock; the Restic snapshot cannot
predate capture beyond clock skew or arrive implausibly late. Symlinks,
unexpected files, duplicate paths, unsafe metadata, digest mismatches, stale
timestamps, missing source row-count parity, timeouts, dirty cleanup, and
missing or unverified current immutable application releases are failures.

The helper verifies the metadata contract, dump digest, and custom-format
header, then invokes the existing restore drill. That drill performs the
authoritative `pg_restore --list`, restore, PostgreSQL identity, schema and
Alembic checks, representative data/invariant checks, recovery-hold transition,
worker/provider side-effect fence, RPO/RTO gates, and exact labeled cleanup.
Only a passed drill evidence JSON is accepted. The proof record beside it
contains the selected full Restic snapshot ID, exact pair paths, digests,
current application release ID, and drill evidence filename. No passwords,
DSNs, payloads, snapshot output, or child stderr is emitted by the proof
wrapper.

## Review and enablement

The template is installed but not enabled by this repository change. After an
immutable foundation release containing these files is installed and the
current application release and local immutable images are present, review the
unit and enable each environment explicitly:

```bash
sudo systemd-analyze verify /etc/systemd/system/ac-restic-postgres-restore-proof@.service
sudo systemd-analyze verify /etc/systemd/system/ac-restic-postgres-restore-proof@.timer
sudo systemctl enable --now ac-restic-postgres-restore-proof@staging.timer
sudo systemctl enable --now ac-restic-postgres-restore-proof@production.timer
```

Run evidence is retained below:

```text
/srv/authority-closers/recovery-evidence/postgres-logical/<environment>-*/restore-drill-<run-id>.json
```

The temporary Restic extraction tree is below
`/srv/authority-closers/recovery-tmp/postgres-logical` and must be empty after a
successful or failed run. The helper gives a timed-out restore drill SIGTERM
and a bounded 30-second cleanup grace period; the drill reconciles and removes
only the exact Docker resources carrying that invocation's label. A hard kill,
label mismatch, or cleanup/evidence failure fails closed and requires operator
attention. Do not remove a broad directory or run a live database restore.
