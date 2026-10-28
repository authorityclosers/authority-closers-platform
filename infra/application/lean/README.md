# Lean production candidate (28 October 2026)

Opt-in code only. The current release installer does not select this profile.
No deployment, cloud resources, spend, retention change or provider activation is
included. The owner job and its 12b design summary supersede PLAN-lean's older
web/scanner allocation; PostgreSQL shared_buffers is 128MB as instructed.

Apply `compose.production-lean.yaml` LAST to the existing application, filesystem
media and hosted-worker overlays. Compose >=2.24.4 is required. Migrations and
backup/restore use the direct PostgreSQL endpoint and their existing roles;
never send them through the runtime pool. `AC_LEAN_DATABASE_URL` and the private
`AC_XRAY_POOLED_DATABASE_URL_FILE` must name `pgbouncer:6432`, database ac_platform,
role ac_runtime. Keep the hosted manifest's original database credential for the
separate direct LISTEN connection. The PgBouncer image must be reviewed and pinned
by digest, version >=1.24, with `pgbouncer` and `pg_isready` on PATH and UID 10001
supported. Build/admit it in CI, never on production. Mount its runtime-only
SCRAM userlist (ac_runtime only), readable by UID 10001, outside Git. No trust auth
or owner/migrator/backup credentials enter the pooler. psycopg 3.3 and PgBouncer
tracked prepared statements are used; prove reconnect and session-isolation in
the disposable database before release.

Apply `lean/compose.foundation.yaml` LAST to the **foundation** project. Caddy and
telemetry are separate services; do not create duplicates in application. Set
AC_LEAN_OTEL_CONFIG_FILE to the reviewed lean/otel-collector.yaml: its memory
limiter is 48 MiB with a 12 MiB spike allowance and batches capped at 128 items. Load the native
slice and helper service drop-in through the release installer, with the helper
and its Docker child sharing `native.slice`. The child must use `--memory-mib 192
--cgroup-parent native.slice`; parent limit 64 MiB + child limit 192 MiB gives a
combined 256 MiB ceiling, including the existing output tmpfs. Merely limiting the
Python supervisor does not limit a Docker-daemon-owned child.

All specified memory+swap limits are equal: no service may use swap. Steady app
ceilings: DB 384, pooler 64, API 512, Sales Xray worker 512, core worker 192,
spool 64, Caddy 64, telemetry 64, combined native 256 = **2112 MiB**. OOM scores
protect DB (-900), API (-500); workers/helpers are +500. This is kill preference,
not a guarantee that a DB exceeding its own hard cap can survive. Kernel/host
headroom, two API colors and transient backup/migration memory need separate proof.

Legacy web services are profile-gated pending static Pages delivery and route
proof; never enable `static-web-legacy` on the lean box. Sales Xray's separate web
project uses lean/compose.sales-xray-static.yaml, applied last by the static-web
job after Pages admission.
No Cloudflare operation is performed here.

## Heavy lane boundary

No scanner or video runner starts in the lean project. The core worker continues
its exact lightweight routes, leaving Studio jobs durable for a dedicated runner.
API filesystem media remains enabled. `AC_HEAVY_SCANNER_TUNNEL_ROOT` names a private
Unix-socket forward to clamd on the heavy host (or the on-demand heavy cgroup).
The operator owns authenticated encrypted transport and host-key pinning. Never
expose raw clamd on a public interface. The existing scanner streams bytes through
this forward and requires its exact clean verdict, checksum and stable object
revision. An absent socket, timeout, rejected/failed scan never means clean.
Forwarding a protocol to a remote daemon does not require a local scanner process.

Use `heavy.slice` only for on-demand heavy work, with CPUWeight 10 and CPUQuota 50%.
Its 3 GiB memory cap is **additional** to the lean budget: on a 4 GiB box pause/drain
analysis and reserve measured physical headroom first, or use a separate approved
host. Never start it alongside a full lean workload on assumed spare memory.
Source, scratch, object versions and DB identity remain production-scoped; moving
real data requires the existing consent/provider/provenance gates. No dev data path
may be substituted for production. See `heavy-contract.md` for topic semantics.

## Admission remains pending

Run a fictional isolated stack, tuned DB migration/dump/restore, canonical canary
and at most 10 concurrent users for five minutes. Record per-cgroup memory and RSS,
OOM/restarts, then remove only that stack. A systemd scope around the Docker CLI
alone does **not** constrain daemon-created containers: use a real cgroup_parent
for every container beneath the 4 GiB / 2 CPU slice. No production/staging stacks,
volumes, secrets or networks may enter the proof. See the scratch REPORT.md for
actual executed evidence and limitations. No measurement is implied by these caps.
