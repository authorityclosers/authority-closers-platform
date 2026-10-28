# Isolated t3.small rehearsal

For a dedicated disposable host with **fictional data only**. These files do not
install production, change DNS, fetch real environment files, or activate providers.
The API image pin is v1.3.0; it lacks the later `lean_service` entrypoint. The
rehearsal hosted worker explicitly runs in inert bootstrap mode. Its RSS does not
establish active analysis memory or throughput. The browser Calls acquisition
route also needs the omitted native helper; the measured Calls API is a narrower
read path. Do not promote this composition as an admitted release profile.

## Prepare on the rehearsal host

Use the owner-supplied SSH key and fixed destination. Copy these source files
only (no checkout, Git credentials, existing env files or source data):

- `infra/application/compose.yaml`, `compose.filesystem-media.yaml`,
  `compose.sales-xray-hosted-openai.yaml`, `compose.production-lean.yaml` to
  `~/rehearsal/application/`.
- `infra/application/lean/pgbouncer.ini` to `~/rehearsal/application/lean/`.
- `infra/application/postgres/init/001-roles.sh` to
  `~/rehearsal/application/postgres/init/`.
- This folder's `compose.rehearsal.yaml`, `Caddyfile`, and `release-hold.Caddyfile` to
  `~/rehearsal/application/`; Python and shell helpers to `~/rehearsal/`.

Run `python3 ~/rehearsal/setup.py` on the box. It generates fresh credentials there
and refuses to replace an existing `runtime.env`. Pull the two auxiliary public
images by the digest pins in the composition (PgBouncer and Caddy); the five app
images and pgvector image must already be loaded. Then run
`bash ~/rehearsal/boot.sh`. Migrations bypass PgBouncer; runtime clients use SCRAM
transaction pooling with the database-generated verifier. The seed refuses any
nonempty database and uses the production ORM/storage implementations with the
fictional shape used by the repo's database fixtures. Existing dev-seed hostname
guards are not changed.

The last overlay documents compatibility repairs: quoted PgBouncer tmpfs,
explicit probe username, cleared filesystem-only settings on the core worker,
private networks, a rehearsal-only ingress adapter, and legacy web apps explicitly
included at the orchestrator's request. Scanning has no socket and fails closed;
video and provider processing are omitted. PG17 declares an anonymous nested data
volume under the base profile's PG18-style parent mount; inspect the actual
`/var/lib/postgresql/data` mount and retain it. A real installer must explicitly
match its selected PostgreSQL major and data-directory layout.

Caddy publishes **127.0.0.1:8080 only**. Its private `auth.caddy` injects fictional
session/OAuth credentials for a supplied seller index; that file must stay on the
box, mode 0600. Only Caddy joins the host-reachable tunnel network; API/worker/data
networks are internal. Never copy `auth.caddy`, runtime env files, a SQL dump or
Docker inspect output containing envs to ac. Numeric evidence is safe to export.

## Measure from ac

Open only a loopback SSH tunnel, for example local port 18780 to the box's 8080.
Install k6 from an official `grafana/k6` GitHub release and verify its published
archive checksum. Run `nice -n 19 k6 run load.js` with `REHEARSAL_URL` set to that
loopback URL. The default daily run is 200 VUs for 1,800 seconds, one read every
10 seconds per VU, cycling Home, Leads and Calls API. Ten fresh 16,044-byte WAV app
uploads start at 30 seconds. VUs share ten sellers. These are queued in the real
waiting-for-person app inbox; no external analysis follows. For busy load use
`PHASE=busy SECONDS=300 UPLOADS=20 RUN_ID=<unique> SUMMARY=<output>`. Every fresh run
needs a unique RUN_ID; there is a real 20-pending-uploads-per-person limit.

Run `sudo nice -n 19 python3 ~/rehearsal/sample.py --seconds <duration>` on AWS;
save its JSONL there. Cgroup charged memory includes file cache/tmpfs; summed RSS
can double count shared pages. Record deltas in OOM/restart counters from each
test's baseline. CPU, steal and credit consumption estimates come from `/proc`.
**No exact CPUCreditBalance is available without AWS CloudWatch evidence.** Do
not claim a balance or confirmed credit exhaustion from these counters.

Run `release.sh` only on this isolated host while a separate k6 release phase and
loopback `probe.py` run on ac. It models stop/migrate/recreate from today's
installer. It uses atomic Unix-socket reloads for the edge hold, and preserves the intake
spool route. It does not reproduce database writer revocation, product note
generation or the full governed release engine. Export the observed gap and
failed requests. For crash tests, send SIGKILL inside the API/worker container
with `crash.sh api` / `crash.sh worker` (SIGKILL to the inspected host PID), preserving the restart-policy supervisor; separately
reboot the host through SSH. Probe serving recovery and compare inbox checksums
and database rows after each event. A completed upload surviving is a separate
claim from an interrupted upload being resumable.

`restore.sh` drains the isolated writers, takes a direct `ac_backup` pg_dump and
exact public-table row inventory, resumes serving, then restores into a fresh,
network-disabled PostgreSQL container with a 384 MiB cap and new credentials.
It compares all public-table counts. Only its named restore container is removed;
the dump, row inventories and timing result remain on AWS for review. This is a
same-host logical restore drill, not independent backup/disaster recovery proof.
