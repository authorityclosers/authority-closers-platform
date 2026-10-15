# AC Sandbox synthetic load on staging and production (operator runbook, 12 Oct 2026)

Owner order (12 Oct): synthetic data on dev, staging and production so reports and coaching
can be tested everywhere. Dev is done (see `apply-20261011T204859Z.json`). Staging and
production use `load-sales-xray-sandbox-hosted.py` (derived from Strike C's dev loader).

## Gates before any hosted run
1. The release that carries the Report/Coaching work must be live in that environment
   (the other session ships it; schema head must be >= `20261011_0087`, because the loader
   writes `report-pillars/1`, speaker maps and sandbox records introduced on dev).
2. **Backup bound.** `R2_POSTGRES_LOGICAL_MAX_DUMP_BYTES = 8 MiB` per logical dump
   (`/srv/authority-closers/current/config/r2/free-tier-policy.conf`). Production dumps are
   3.5 MB today. Dev grew 322 -> 455 MB for 3,360 calls (about 10:1 compression => ~13 MB
   compressed), so a full load would break production backups and therefore `ac-ship`.
   Load a subset: `--per-business 36` = 360 calls (all 10 sellers, whole journeys,
   ~1.4 MB compressed). No `--include-history` on production.
   Staging dumps are already 30 MB (over the bound since the 11 Oct import); the policy
   needs an owner/CTO decision regardless (for example 64 MiB x 40 points x 2 envs = 5 GiB,
   still inside the 8 GiB R2 envelope). That is a foundation config release, not a hand edit.
3. **Production approval.** AGENTS.md: the owner writes
   `approve data change: AC Sandbox synthetic load (360 calls, 60 fictional reps, no history), production`
   in chat or on the issue. Production also needs the AC Sandbox organisation created first
   (an allowed "workspace create" data change through the platform API; dev/staging tenant id
   `90ec1979-0d85-4829-ba8d-cabde2a9a9d3` does not exist on production) with admin@ as owner.
4. Script checked in under `scripts/data-changes/` (commit it in the workbench after the
   in-flight ship so it does not ride into that release unreviewed).

## Run (same shape as dev)
```
# snapshot first
sudo ac-postgres-backup --capture-only --environment staging      # or production
# dry run (receipt is count/id-only JSON)
AC_DATABASE_URL=<that environment's runtime URL, injected> AC_ENVIRONMENT=staging \
  python scripts/data-changes/load-sales-xray-sandbox-hosted.py \
  --dataset /home/acdev/strikes/1676/sandbox-source-20261011-0537 \
  --environment staging --target-tenant 90ec1979-0d85-4829-ba8d-cabde2a9a9d3 \
  --expect-db-host <postgres host as seen from where it runs> \
  --approver-person-id 311f4bd2-7b8b-4f45-99f0-a2aed83bc95a \
  --approval-reference "approve data change: AC Sandbox synthetic load, staging (owner, 2026-10-12)" \
  --per-business 36
# show the dry-run receipt to the owner, then repeat with --apply
```
Run it from the environment's release checkout (`/srv/authority-closers/releases/<sha>/`, its
venv has the exact `ac_platform`), with the DB reachable on the docker network. The loader
refuses any other environment/host/database.

## Known behaviour (measured on dev)
- One transaction. While it runs, rows it inserts reference the approver person by foreign
  key (KEY SHARE lock), so the approver's own API requests wait until commit. The dev full
  load took ~4.5 min; the 360-call subset should take well under a minute. Run it when the
  approver is not using the app.
- The dev loader locks the tenant row FOR UPDATE, which blocked every API request for that
  tenant and exhausted the API pool (500s). The hosted variant locks FOR SHARE instead.
- Replay is idempotent: identical content is skipped, changed content is refused.

## Read-back after apply
As the owner, select AC Sandbox: Calls shows `Report ready`, a report shows the six pillars,
`/coaching?call=<id>`, `/coaching` and `/coaching?view=team` answer 200, Insights shows the
synthetic label. On dev this was proven with `readback.py` and `shots.cjs` (scripts/data-changes).
