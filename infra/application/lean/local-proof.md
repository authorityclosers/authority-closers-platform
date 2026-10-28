# Local proof handoff: fictional, disposable, five-minute ceiling

This is an admission checklist, not a receipt. The acdev account has no Docker
socket access. No production or staging stack, credentials or volumes may be used
as a substitute. The load-harness job supplies the complete fictional fixture and
canonical canary; the application image must contain the committed lean source.

1. Use an approved isolated executor, low process priority (`nice -n 10`), and a
   unique `ac-lean-proof-<run>` Compose project. Build/retrieve images in CI first;
   never build under load on this host. Require three inputs: the fictional stack
   manifest, fictional canonical-canary command, and bounded smoke harness.
2. Load/start only `proof.slice` (4 GiB, zero swap, 200% CPU, CPUWeight 10) through
   the authorized executor. Set **every Docker container's** cgroup_parent to
   `proof.slice`, including foundation services and native children. A scope
   around `docker compose` does not encompass daemon-created containers. Verify
   `memory.max=4294967296`, `memory.swap.max=0`, `cpu.max` quota/period <=2, and each
   container's HostConfig.CgroupParent before boot admission.
3. Render Compose before running it. Check every service cap, no host/container
   name collision, no external networks, no production/staging DB URL, and every
   bind mount beneath this run's private scratch directory. No /srv state, secret
   files or Docker socket in application containers. Use isolated internal
   networks and loopback-only published test ports. Disable external providers,
   use fictional data and fake email, keep side effects held. Do not inherit .env.
4. Start the fictional stack. The source-owned test
   `tests/infra/test_lean_database_proof.py` separately starts a random disposable
   PostgreSQL container using the exact overlay tuning and 384 MiB cap, bootstraps
   the existing roles, migrates through head, writes fictional data, dumps as
   ac_backup, restores and verifies schema/version/data. It removes its own
   container and anonymous volume in finally. It runs on wb-ci's isolated runner;
   locally opt in only with `AC_LEAN_DISPOSABLE_DOCKER=1` after executor admission.
   This DB proof does not establish PgBouncer or application canary acceptance.
5. Verify runtime API/core/Sales Xray DSNs reach PgBouncer, LISTEN reaches direct
   PostgreSQL, migration/backup roles bypass PgBouncer, and pool/session isolation
   survives reconnects. Verify the scanner tunnel points to the heavy target;
   missing scanner/failed/timeout scan stays quarantined and cannot be clean.
6. Run the canonical fictional canary. Then the separate smoke harness may run
   **at most 10 concurrent users for 300 seconds**, with no transcription/scan,
   transcoding, reanalysis, export or backup compression load. Abort on production
   latency alarms, host pressure, failed readiness, OOM or unexpected restarts.
7. Sample only containers bearing this exact project label every 5–10 seconds.
   Record timestamp, service/container id, summed `docker top <id> -eo rss=` KiB,
   cgroup `memory.current`, `memory.peak`, `memory.stat` anon/file/shmem and
   memory.events/oom_kill. Record parent slice memory/CPU too. Summed process RSS
   double-counts shared pages; the cgroup is the authority for cap compliance and
   includes cache/tmpfs/children. Neither `docker stats` working-set alone nor
   only the helper Python RSS proves the native 256 MiB combined cap.
8. Stop/remove only this run's Compose project (`down --volumes --remove-orphans`)
   and disposable fixture files, after exporting bounded numeric evidence. Verify
   no containers, anonymous volumes, networks, harnesses or timers from the test
   remain. Never use a global prune or stop command. Stop the empty proof slice.

Acceptance remains red until boot, canonical canary, pooler correctness, the
five-minute smoke, per-service/parent measurements, zero OOMs and cleanup all have
actual receipts. No production or staging action is part of this proof.
