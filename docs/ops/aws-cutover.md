# AWS production cutover kit

**Scripts, tests and fictional rehearsal only. No production or staging execution is authorised by this task.** Cloudflare routing remains an owner action. The actual move belongs to the named operator/coordinator through the authorised release/data-change process, not a builder deployment.

Kit: `infra/aws/cutover/`. Evidence: `/home/acdev/scratch/aws-cutover-20261029/REPORT.md`. Read the live `/home/acdev/scratch/aws-rehearsal-20261029/REPORT.md` before using the shared box. The first fictional attempt overlapped its measurement window and was interrupted on its exclusive-hold request; it is diagnostic only. Use the completed later run's receipts for kit acceptance.

## What the scripts do

- `cutover.py presync`: resumable, bandwidth-limited, low-priority rsync over SSH. It copies files without deleting anything, preserves permissions/hardlinks/numeric ownership when run by the admitted privileged endpoints, and records total files/bytes and elapsed time. Roots are an explicit inventory, with no guessed scratch exclusions. Bulk presync has a separate four-hour timeout; it does not inherit the final ten-minute freeze budget. Interrupted copies retain rsync partials and can be resumed before the window.
- `freeze-and-move`: hold source, drain, fence every source writer, custom-format pg_dump, transactional restore, final rsync, compare all user-table counts plus sequences/schema head/columns/constraints/extensions/app-role flags/grants/RLS policies, compare durable file SHA-256/size/mode (UID/GID when `--ownership` is configured), then start nonwriting target services behind its hold.
- `switch`: never edits Cloudflare. Requires `--routes-confirmed`, probes the held target, opens its API/consumers once, then runs the public canary **from ac**. A canary/start failure re-holds, drains and fences the target. Source stays held.
- `rollback`: holds/drains/fences AWS and ac; saves a safety dump of old ac; takes a **full current AWS dump**, restores it on ac in one transaction, reverse-syncs durable files/spool, compares counts/sequences/catalog/files, starts only nonwriting source services behind the hold. Return routes only after this verification. Full-dump replacement avoids inventing an application-specific SQL delta or losing AWS window writes.
- `resume-source`: only after verified rollback or safe pre-open abort and owner route confirmation; opens ac, then public canary. AWS remains held/fenced.
- `abort-before-open`: only before AWS could accept writes. Fences the target and prepares the unchanged source behind its hold; then owner confirms ac routes and runs `resume-source`. Never use this after a switch attempt; use full rollback.
- `endpoint.py`: password-free argv adapter for Docker PostgreSQL and file inventories. Credentials expand inside the DB container. Destructive real-DB restore needs `--permit-production-restore` as well as driver approval. Restore uses `--single-transaction --exit-on-error`; no schema migration runs. `restore-admission.py` requires reviewed populated/reverse-restore proof matching both engines’ exact version/lock/connection settings and current source schema, before either origin is held. A fresh-DB restore alone is insufficient.
- `host.py`: explicit reviewed lifecycle profile. Sends SIGTERM and waits/inspects clean exit; never uses a timed Docker stop that escalates to SIGKILL. It disables each inventoried writer’s restart policy during fencing and restores only that origin’s reviewed policy on open. Missing inventory/probes or unclean exit refuses progress. Held services must exclude every DB/file writer, including API spool consumers.

All driver commands default to a plan. `--execute` is required. Nonfictional execution also needs a JSON record with `config_sha256`, exact `action`, and `owner_record` pointing to the actual owner-approved window/data-change record. This records approval; it does not confer it. Never label real data `fictional`. Do not put passwords, tokens, authenticated URLs or customer contents in these profiles or receipts. Hooks are reviewed command arrays, not environment dumps. Serialize all operations under one named operator, one config and one evidence directory. The driver locks that evidence directory and refuses configuration drift.

## Existing production backup and operations evidence

Repository sources and readable installed unit schedules were inspected; privileged installed scripts and live Docker mounts on ac were inaccessible to this seat. Root Operator was asked for sanitized deployed metadata in `strikes/coord/INBOX.md`. Do not mistake source configuration for a verified live inventory.

- `infra/vps-foundation/scripts/ac-postgres-backup.py`, its shell wrapper and `ac-postgres-backup.service/timer`: installed every five minutes, randomized by 30 seconds. It resolves immutable environment releases, uses an exported PostgreSQL snapshot for dump/count parity, local bounded rings and encrypted Restic logical snapshots. Retention is policy-driven (`R2_POSTGRES_LOGICAL_RETENTION_POINTS_PER_ENVIRONMENT`), not an invented fixed number. Local root: `/srv/authority-closers/backups/application/<environment>/logical`.
- `scripts/ops/ac-db-snapshot` delegates to the bounded Drive helper with explicit execution; installed `ac-db-snapshot@production.timer` is hourly, staging `00/6:20`. Installed service description is a full snapshot to Google Drive. Exact installed helper/destination/retention requires Root's confirmation; no snapshot was executed tonight.
- `ac-restic-backup.timer`: daily 02:15 UTC with up to five minutes jitter. Restic encrypts to R2, backs up ac's host state, excludes secrets, application logical dumps from the general tree, intake spool, and proven scratch/rebuildable paths. The separate logical-backup path protects DB dumps. Weekly restore checks/proofs have separate units. **Keep all existing ac Restic configuration and timers unchanged.** Do not repoint it to AWS or count the old DB's backup as protection of AWS writes.

| Consumer on ac    | Connection today, from inspected source                                                                                                                                                                                       | Smallest reviewed re-point                                                                                                                                                                                                                                                                                                                                                              |
| ----------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `ac-bugs`         | `AC_BUGS_KEY`: public Admin HTTPS; otherwise Docker exec into `ac-application-production-sales-xray-worker-1`, own module and `/run/ac-sales-xray/database-url`. Supports `AC_BUGS_RUNNER`.                                   | Prefer existing scoped public Admin API for keyed operations. For full CLI/released behavior, an SSH wrapper executes the same admitted CLI on AWS. Keep staging/dev local.                                                                                                                                                                                                             |
| costq `q.sh`      | Repository references pin `~suyash/costq/q.sh` (`/home/suyash/costq/q.sh`), logged `QUERY-LOG.txt`, forced read-only. Directory is inaccessible to acdev; exact current host/port vs Docker exec is **unverified**.           | Root must inspect sanitized connection argv. If it uses TCP, retain its logging/read-only role and change only production host/port to ac loopback `15439`; if Docker exec, route only that production branch over SSH. No blanket address or Docker replacement.                                                                                                                       |
| `ac-bug-alerts`   | Every-minute production instance invokes `/usr/local/bin/ac-bugs`; keeps cursor/task state on ac.                                                                                                                             | Point `AC_BUG_ALERTS_AC_BUGS` to the environment-aware AWS CLI wrapper, or inject the existing scoped API key. Keep cursor/state on ac to avoid duplicate alerts.                                                                                                                                                                                                                       |
| `ac-bugs-release` | Reads `/var/log/ac-ship.log`, then calls `ac-bugs released`; state `/var/lib/ac-bugs-release/state.json`.                                                                                                                     | Keep log/state and release observer on ac, set `AC_BUGS_RELEASE_AC_BUGS` to wrapper. Ensure future authorised AWS release receipts still create the canonical live line on ac.                                                                                                                                                                                                          |
| Play hook         | `ac-play-after-release` reads ac's ship log and GitHub workflow state; no production DB connection.                                                                                                                           | No DB tunnel/re-point. Preserve release log receipts and existing closed-testing approval policy. Never dispatch it as a cutover test.                                                                                                                                                                                                                                                  |
| Admin metrics     | `infra/metrics/ac-metrics-collect`: Docker exec into each env PostgreSQL, read-only SQL, atomic `/srv/authority-closers/metrics/<env>/usage.json`; API has read-only metrics-store mount. Installed timer every five minutes. | Run only production export on AWS with the same SQL; retain dev/staging export on ac. Copy their aggregate JSON atomically into AWS's metrics store for the one production Admin; retain intended production-data segregation. `ops-repoint metrics` executes export remotely but does not copy other environments or install timers.                                                   |
| Telemetry jobs    | `ac-telemetry-friction@production` runs the worker's `friction_cli` via Docker and URL-file, weekly Monday 01:30 UTC; retains reports/cursors on ac. App telemetry/retention follows API/worker DB configuration.             | `AC_TELEMETRY_FRICTION_RUNNER` can use an `ops-repoint friction-runner --execute -- ...` wrapper for only production module execution over SSH, preserving report output/state on ac. Move app consumers with the stack; do not leave an old retention writer running. Check `ac-bug-board`, bug radar and any newly installed lake-export timers in the deployed writer inventory too. |

`ops-repoint` prints its SSH command by default. `tunnel --execute` opens **only** `127.0.0.1:15439 -> SSH -> AWS 127.0.0.1:15432`, with forwarding-failure and keepalive checks. AWS PostgreSQL must be published only on loopback by the admitted stack, or use an approved private DB relay. Never publish 5432 publicly. A tunnel cannot redirect hard-coded Docker exec clients or a Docker Unix socket. Use a dedicated admitted ops/operator SSH identity; the [remote release executor](aws-production-executor.md) key deliberately forbids arbitrary shell and port forwarding and must not be reused for these operations. Do not remap a whole old production container address that dev/staging might share.

```bash
python3 infra/aws/cutover/ops-repoint tunnel \
  --identity ~/.ssh/ac-rehearsal.pem --local-port 15439 --remote-port 15432
# Operator only, once reviewed:
python3 infra/aws/cutover/ops-repoint tunnel \
  --identity /etc/authority-closers/secrets/aws-cutover-ssh \
  --local-port 15439 --remote-port 15432 --execute
python3 infra/aws/cutover/ops-repoint bugs \
  --identity /etc/authority-closers/secrets/aws-cutover-ssh --execute -- --env production list --json
```

The CLI wrapper is a building block, not an installed global redirect: each existing consumer passes different environment/module arguments. Preserve those interfaces in its per-consumer wrapper and validate read-only queries before enabling timers. Use existing runtime secret injection; do not copy DB URLs into wrapper scripts.

## Morning preflight — named operator and owner

1. Read the final cutover and capacity reports. **Do not proceed while the shared-box rehearsal is active or its capacity/admission gates fail.** The current t3.small report already records sustained-load errors/steal and missing real-provider throughput proof. Successful fictional data transfer does not admit that host for production.
2. Record the exact production data-change approval, operator, quiet window, source release/image tuple, PostgreSQL major, schema head, rollback decision-maker and retained recovery artifacts. Owner's outside-India/AWS approval covers residency, not execution of this window or unrelated deletion. No product or migration upgrade in the move.
3. Root supplies actual bind mounts and aggregate counts/bytes for recordings, media/video, spool and required native artifacts/checkpoints. Split production/staging; never copy their shared parent or assume the aggregate 15 GB is production. Include all active upload/job dependencies; exclude scratch only with proof. Resolve symlinks, UID/GID, disk/inode capacity, source/target PG major and PG17's nested `/var/lib/postgresql/data` volume. No blind parent-volume assumption.
4. Admit the existing exact release tuple and kit through the authorised release mechanism. On AWS provision isolated production-only Infisical identity, preserved signing/session/encryption keys and application DB roles. No real provider activation from rehearsal credentials. Keep destination external effects and ingress held. Prepare DB/PgBouncer and stopped application containers; do not reuse the `ac-rehearsal` project or its database. Installer owns production container/image/network creation; this kit does not guess a Compose invocation.
5. Populate root-controlled `production.example.json`, `host.example.json` on both origins, `backup.example.json`, and public canary profile into `/etc/authority-closers/`. **Examples deliberately contain refusal placeholders.** Pin actual mounts, immutable route selectors, Caddy socket validation/reload argv, all writer containers/units/native imports, a no-active-writes/leases probe and read-only origin readiness probes. Set inventory review record. Held-services lists may contain only verified nonwriters; API starts at open because its spool consumer can write behind maintenance. Pin each writer’s deployed restart policy; automatic restarts stay disabled on the retired origin.
6. Existing release hold (`infra/application/edge-routes/production-hold.caddy`) still accepts capture posts into intake spool. Admit `freeze-production.caddy` as a full production-only hold through the release-owned immutable edge projection, validate complete Caddy config and preserve staging selector/hash. No intake exception during the final dump/delta. Test source/target held probes locally before window; retain old selectors. Do not edit staging or production Caddy by hand tonight.
7. Prove both fresh and **populated** transactional restore plus full reverse restore with the exact admitted PostgreSQL settings/schema before the window. The default lean PG17 setup (60 connections, 64 locks per transaction) failed populated restore with `out of shared memory`; do not weaken atomicity or discover this after freezing. The bounded fictional repeat uses 512 locks/transaction and 20 connections in a separate 192 MiB engine. Production needs its own matching proof (candidate bootstrap lock setting 512, subject to memory/admission review); this task never restarts the shared engine. Pin a reviewed `cutover-restore-proof.json` for `restore_admission`, including owner record, production environment, both passed flags, source/target capacity objects and source catalog SHA-256.
8. Finish backup admission below before allowing AWS writes. Verify a fresh decrypt/restore in an isolated DB, backup key recovery and timers. Orchestrator owns the new prefix IAM policy and S3 lifecycle; a denied upload is a cutover blocker, never a reason to weaken existing archive permissions.
9. Pause new analysis claims and gracefully pre-drain outside the timed freeze if needed, preserving accepted work. Hosted graceful allowance is 960 seconds and uploads may last 900 seconds. Inventory/fence all scheduled/native/webhook writers; maintenance alone is insufficient. Preserve queued DB jobs, spool files and upload leases; never kill work to meet ten minutes.
10. Run plan commands, pin config SHA, retain per-action owner approval JSON. Execute under one operator and one evidence directory, at low priority. Public canary profile must use exact admitted paths/status/body/header expectations; examples are unauthenticated smoke only. Add approved authenticated upload/playback/range/tenant-denial probes through private credential injection and validate job ownership, TLS, sessions, Android/API and release headers. Never feed real calls into AI as a migration canary.

```bash
# On ac. Paths below are the admitted installation, not an instruction to install tonight.
CUTOVER_CONFIG=/etc/authority-closers/cutover.json
CUTOVER_EVIDENCE=/srv/authority-closers/backups/cutover/OWNER_WINDOW_ID
nice -n 19 ionice -c 3 python3 /usr/local/lib/ac-cutover/cutover.py presync \
  --config "$CUTOVER_CONFIG" --evidence "$CUTOVER_EVIDENCE"
# Save reported config_sha256 with the actual owner record and exact action.
# Repeat approval filenames by action; never reuse a different config's approval.
nice -n 19 ionice -c 3 python3 /usr/local/lib/ac-cutover/cutover.py presync \
  --config "$CUTOVER_CONFIG" --evidence "$CUTOVER_EVIDENCE" \
  --execute --approval-record /etc/authority-closers/cutover-approve-presync.json
nice -n 19 ionice -c 3 python3 /usr/local/lib/ac-cutover/cutover.py freeze-and-move \
  --config "$CUTOVER_CONFIG" --evidence "$CUTOVER_EVIDENCE" \
  --execute --approval-record /etc/authority-closers/cutover-approve-freeze.json
```

Budget: final hold/fence verification 30–60 s; dump/transfer 30–90 s; restore/catalog/counts 30–120 s; delta/checks/owner switch/canary 2–5 min. These are planning allocations, **not production measurements**. Target total write freeze <600 s includes owner routing and canary. Driver separately records movement duration and hold-to-open duration; owner waiting/DNS convergence also counts. At a failed step or budget overrun keep both origins held. Never auto-unfreeze, rerun a half-completed restore blindly or force-kill a drain. Before AWS writes, `abort-before-open` can prepare the unchanged source; after any exposure, full verified rollback is required. Retain failed receipts and safety dump; interrupted reverse restore needs explicit operator reconciliation, not automatic routing.

## Owner switch checklist

1. Confirm source hold, all source writers fenced, zero active write transactions/claims and matching DB/file receipts. Target is still held and background writers are stopped. Confirm admitted backups and recovery key. Keep old ac origin held through convergence and the rollback window.
2. In **Cloudflare**, owner moves only the production hostname routes from tunnel **`ac-kvm4-prod`** to **`ac-aws-prod`**. Reconcile both published-hostname configuration and DNS CNAME to the new tunnel ID; no simultaneous ingress forwarding to both. Hostnames: `app`, `learner`, `admin`, `coach`, `api`, `salesxray` under `authorityclosers.com`. Inventory any additional production/native/artifact names before execution. Staging/dev targets remain unchanged. Record before/after and timestamp; scripts never call Cloudflare.
3. Verify those hostnames reach the held AWS origin, and stale/direct ac paths remain held. Confirm TLS and routing before opening writes. Then, from **ac**, run:

```bash
nice -n 19 python3 /usr/local/lib/ac-cutover/cutover.py switch \
  --config "$CUTOVER_CONFIG" --evidence "$CUTOVER_EVIDENCE" --routes-confirmed \
  --execute --approval-record /etc/authority-closers/cutover-approve-switch.json
```

4. Verify the public canary receipts and approved authenticated journeys; confirm only AWS consumers/host timers are active, source remains held, no duplicate spool/job imports or payment actions. Reconcile error/queue-age, memory, steal/credits, disk and backup age. Stop on failed admission rather than interpreting HTTP 200 as complete journey proof.

## Rollback checklist

If AWS has accepted any write, never route back to the stale ac DB. Hold AWS first, fence **both** origins, then perform full reverse DB/files/spool copy and verification. Owner requests its exact recovery approval. Source safety dump and AWS full dump are retained. No automatic deletion; unexpected extra files block manifest equality until an explicitly approved reconciliation. Application-only rollback on AWS may be preferable, but is a separate authorised release action.

```bash
nice -n 19 ionice -c 3 python3 /usr/local/lib/ac-cutover/cutover.py rollback \
  --config "$CUTOVER_CONFIG" --evidence "$CUTOVER_EVIDENCE" \
  --execute --approval-record /etc/authority-closers/cutover-approve-rollback.json
```

After reverse verification, owner moves the production hostname routes from `ac-aws-prod` back to `ac-kvm4-prod`, confirms held ac origin and convergence, then runs `resume-source --routes-confirmed` with its action-specific approval record. It starts only the source writers and runs public canary from ac. Keep AWS held. Do not promise <10 minutes for a post-write rollback; plan allows 30–90+ minutes for recovery. Retain old origin/data under the approved rollback retention; no cleanup/deletion is authorised here.

## AWS backups from minute one

- `backup.py capture`: custom-format logical dump immediately and every 15 minutes, private local root `/srv/authority-closers/backups/aws`; only this job's completed dumps older than 24 hours are pruned. A dump has a SHA-256 receipt. It is a consistent pg_dump, not PITR. Live row counts are not misrepresented as a common exported snapshot.
- `backup.py archive`: requires a dump fresher than 20 minutes and matching digest; packages it, encrypts with OpenSSL CMS AES-256 using a public recovery certificate, uploads hourly to **`s3://ac-archive-283923228069-apse2/prod-backups/<timestamp>.tar.cms`**, then verifies object length. S3 SSE is additional to client encryption. Local plaintext dumps stay mode 0600 and follow the 24 h retention. Hourly copy RPO is up to one hour plus scheduling/failure time; local dump RPO 15 minutes. This does not back up recordings/media: their independent approved protection remains a cutover gate.
- Credentials use the existing `ac-archive-put` Infisical `credentials()` retrieval in memory with a minimal AWS child environment. No credential is passed in argv or written into kit config. Existing `ac-archive-put` intentionally refuses this prefix; it is **not modified**. Orchestrator must admit the production prefix/identity permissions/lifecycle. Private recovery key stays in password manager/Infisical; only public certificate belongs on AWS. Recovery key availability must be proved off host.
- `install-backups.py` plans by default. Operator execution requires the config-bound `install-backups` approval record. It installs units, captures and verifies an encrypted upload **immediately**, then enables both timers. Admission fails if any step fails. `backup_ready_probe` must check fresh successful dump/archive receipts, both timers, and alert routing before open. No real S3 upload, timer enablement, key provisioning or lifecycle change was performed in this task.
- Monitor `systemctl --failed`, both service results, timer next-run and receipt ages; route failures through the existing operator alert channel. This kit emits failure exit codes; it does not install a new owner-messaging channel. Test a periodic isolated decrypt/restore; do not count upload success as restore proof.

```bash
python3 infra/aws/cutover/install-backups.py --config /etc/authority-closers/aws-backup.json
# Operator after admission and actual approval:
python3 /usr/local/lib/ac-cutover/install-backups.py \
  --config /etc/authority-closers/aws-backup.json --execute \
  --approval-record /etc/authority-closers/aws-backup-approval.json
python3 /usr/local/lib/ac-cutover/recover-archive.py \
  --archive /PRIVATE/downloaded.tar.cms --certificate /PRIVATE/public.pem \
  --private-key /PRIVATE/recovery-key.pem --output /PRIVATE/new-recovery-dir
# Digest verified; restore database.dump only into an isolated recovery DB first.
```

## Repeat the fictional rehearsal

Wait for the capacity operator's explicit completion. This reads schema only from its fictional app, then creates a separate network-isolated 192 MiB PG17 fixture engine (same installed image ID; 20 connections, 512 locks per transaction), new `cutover_fixture_<uuid>_{source,target}` DBs, generated rows, private local/AWS files, and two tiny loopback HTTP/worker services. Only the new fixture engine and services are stopped afterward; their durable data is retained. No existing application database or service is stopped/restored. Fixture HTTP checks replace real Caddy/worker/Cloudflare actions, so this is **data-path/lifecycle orchestration proof**, not a production app cutover or a public/authenticated canary proof.

```bash
nice -n 19 python3 infra/aws/cutover/dry_run.py \
  --identity ~/.ssh/ac-rehearsal.pem \
  --evidence /home/acdev/scratch/aws-cutover-20261029/NEW_UNIQUE_RUN
nice -n 19 uv run pytest -q infra/aws/cutover/test_cutover.py
/usr/local/bin/wb-ci --py --include infra/aws/cutover docs/ops/aws-cutover.md \
  --py-tests infra/aws/cutover/test_cutover.py
```

The dry run measures every movement step, sends a post-switch AWS row and file, reverses them, and requires both to survive on the fictional source. Generated fixture DBs/files and encrypted test backups are retained as private evidence; teardown of the shared stack is forbidden. An interrupted attempt must be retained and labelled; use a fresh evidence directory for a clean repeat.
