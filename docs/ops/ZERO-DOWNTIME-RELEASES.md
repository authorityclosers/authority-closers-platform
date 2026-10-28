# Zero-downtime production releases

Status: design and phased plan, 27 Oct 2026. S1 and S2 built on the workbench 28 Oct 2026; S3 is planned in `docs/ops/ZERO-DOWNTIME-S3-PLAN.md`.
Source pin: `main` 6160b08ab (v0.98.0). Installer line numbers refer to
`infra/application/scripts/install-application-release.sh` at that commit.

## Built so far (28 Oct 2026)

- **S1, graceful edge switches.** Each release carries `infra/application/edge/Caddyfile`, byte-identical to the foundation's (a test keeps them equal), with Caddy's admin API on `unix//run/caddy/admin.sock` inside the router (a private 0700 tmpfs; no TCP listener). The installer copies it to `/srv/authority-closers/application/edge-config/<sha256>/Caddyfile` and layers `infra/application/edge/compose.edge.yaml` on the installed foundation's compose file. The first release after this recreates the router once, at the hold switch that already recreated it; every later switch is `caddy reload` on the socket. A rollback target from before S1 keeps the old behaviour.
  - Why the release carries the file: the release engine installs only the foundation's backup scope, and it has not updated itself since 12 Oct (its timer tick returns while staging is paused between ships). A foundation-only change would never reach the host through ac-ship.
- **S2, a shorter hold.** The installer captures the environment `with_release_secrets` produces once, before the preflights, and keeps it in memory only; the wrapper then answers every later call from it instead of logging in and fetching twice per call. PostgreSQL's bootstrap scripts are mounted from `/srv/authority-closers/application/postgres-init/<sha256>/` (the installer exports `AC_POSTGRES_INIT_ROOT`; `compose.yaml` falls back to `./postgres/init`), so an application release no longer recreates PostgreSQL. Backup and rotation tools that only `exec` into the server keep working without the variable.
- **Probe:** `scripts/ops/release-probe.py`; **dev drill:** `scripts/ops/edge-reload-drill.sh`. Evidence: `docs/evidence/zero-downtime-s1-s2-20261028.md`.
Measurements were taken read-only on `ac` on 26–27 Oct, from four sources:
- deployment records in `/srv/authority-closers/application/deployments/{production,staging}/`;
- pre-migration dumps in `/srv/authority-closers/backups/application/production/`;
- release logs in `/var/log/ac-release/`;
- the dockerd/containerd journal, which goes back to 23 Oct 05:27Z.

The usage query went through the logged path (`/home/suyash/costq/zdr-usage-by-hour.sql`, with a line in QUERY-LOG).

Related work owned elsewhere: the client "Updating" banner with retries, and release-safe lead intake. This plan removes most of the holds they guard against. Both stay useful for the rare hold that remains and for network errors.

## Owner summary

1. Every production update today closes the whole site for about 3 minutes (152–189 s, median 175 s). Before 23 Oct it was about 2 minutes.
2. In the last 14 days there were 61 production updates. Together they closed the site for about 2.4 hours, and half of them ran between 09:00 and 22:00 IST.
3. Only about 30 s of each 3 minutes is real work: copying the database (3 s), changing it (3 s), starting the new version (about 20 s). The rest is the installer fetching secrets 58 times and restarting the database when nothing about it changed.
4. Each update, and each test-site update, also restarts the front door for everyone. That happened about 250 times in 14 days. Each restart drops every request still running past 10 s, so a long upload fails even when no update is running on production.
5. The fix: start the new version beside the old one, check it, move traffic over in one step, then let the old one finish what it was doing. No closed sign. That covers the 39 updates with no database change first (phase S, about a week), then the other 22, which only added things (phase M, 1–2 weeks). In phase S the API also runs as two copies, so one stuck process no longer slows everyone.
6. Call analysis is never cut short: the old analyser finishes its current call while people already use the new version. A call that arrives in that time waits a few minutes to start; nobody sees an error.
7. Leads keep flowing: with no closed sign, Meta, WhatsApp and website forms are answered throughout. Lead OS's store-and-forward receiver covers the rare short hold that remains.
8. Timing: ac-ship switches production only when no client has used the app in the last 15 minutes and no call is being analysed. Otherwise it waits for the next quiet slot (06:00–09:00 IST for now, learned from telemetry after 4 weeks of data). Urgent fixes skip the wait.
9. Rings: the AC team gets a new version first, then testers, then everyone. On the web that is per organisation; on Play it is the closed track, then 10% → 50% → 100% of production. A web stage stops in seconds; a Play stage can be halted.
10. Rollback means moving traffic back to the old version in seconds, with no database restore. On Play it means halting the rollout and shipping a fixed build.

## 1. What happens today (measured)

### 1.1 The sequence

| Step | Installer | What users see |
|---|---|---|
| Edge to the hold route (Caddy container **recreated**) | `activate_edge_route` :1747 → `reconcile_edge_router` :1304 (`up --force-recreate edge-router`) | 503 "completing a reviewed release" on all six production hosts, webhooks included |
| Stop api + core worker (30 s timeout) | :885 | — |
| Drain hosted Sales X-Ray worker (up to 960 s) | :855 | the hold keeps running while it drains |
| Fence writers, `pg_dump`, `pg_restore --list`, sha256, receipt | `prepare_postgres_release` :1757 | — |
| **Recreate PostgreSQL**, fence again | same | — |
| `alembic upgrade head`, then the product-notes writer | :1760, :1761 | — |
| Start api + learner/admin/coach web, wait healthy | :1794 | — |
| Edge to the live route (Caddy recreated again) | :1809 | site back |
| Start core worker + Sales X-Ray worker | :1826 | — |
| *Separate step after commit:* recreate `sales-xray-web` | release engine "production-web" step | 502 on salesxray.* pages for about 1.3 s |

### 1.2 Hold length and where it goes

Thirteen production releases between 23 and 26 Oct had full journal coverage. For these, the hold runs from the first edge-router network join to the second.

| | min | median | max |
|---|---|---|---|
| **Hold (503 on every host)** | **152 s** | **175 s** | **189 s** |
| hold on → api/worker stopped | 14 | 14 | 15 |
| Sales X-Ray worker drain (SIGTERM → exit) | 1 | 1 | 1 |
| drain end → dump finished | 34 | 38 | 39 |
| dump end → PostgreSQL recreated | 17 | 18 | 25 |
| PostgreSQL up → migrate container start | 30 | 33 | 35 |
| migrate start → api start (migrate ≈3 s, notes ≈3 s) | 31 | 36 | 39 |
| api start → hold off | 13 | 18 | 20 |
| hold off → workers started | 18 | 20 | 22 |
| refused-connection gap per Caddy recreate | 0.33 | 0.40 | 0.75 |

Releases from 13 to 22 Oct predate the journal. For those, the deployment-record time from backup reservation to commit was 136–275 s (median 151 s), which puts the hold at about 130 s.
- On 23 Oct (v0.86) the hold grew by about 25 s. That release added the verified pre-restart snapshot and the PostgreSQL recreate.
- The 275 s outlier is 0c5f9cf on 23 Oct.

**Real work inside a 177 s hold** (6160b08, 26 Oct 17:33:07–17:36:04Z), timed from the journal and the Infisical timestamps in the release log:

| Step | Time |
|---|---|
| Caddy switch | ≈0.4 s × 2 |
| Stopping the api | <1 s |
| Worker drain | 0.7 s |
| `pg_dump` of 17 MB | ≈3 s |
| migrate | 3.3 s |
| product notes | 3 s |
| api/web start to healthy | ≈20 s |

The remaining time breaks down as follows:
- **58 Infisical secret fetches during the hold.** Every `compose_for` call runs `ac-infisical-run` + `infisical run` twice, via `load_sales_xray_hosted_inputs` and `with_practice_pilot_scope` (:667, :693). At about 1.5 s each, that is roughly 80–100 s.
- **A PostgreSQL recreate on every release.** The init bind mount is `./postgres/init` (compose.yaml:38), a path inside the per-release directory, so the service config changes every release. That cause is inferred; the recreate itself shows in all 13 journaled releases. It costs about 35 s including health waits and the second fence.
- **Health-wait polling.**

### 1.3 Counts for the last 14 days (13–26 Oct)

- **61 production releases.** 22 changed the migration head (36%) and 39 did not (64%). They ran 4.4 a day on average and 6 on 26 Oct.
- **About 144 minutes of production 503s in total.** That is the 13 measured holds plus the 48 older ones estimated as record duration minus 22 s.
- **When they ran (IST):** 30 of 61 between 09:00 and 22:00, 8 between 05:00 and 09:00, and 23 between 22:00 and 05:00.
  - On 26 Oct, four of the six holds started at 12:13, 13:58, 17:50 and 19:49 IST.
- **62 staging releases.** Staging and production share `ac-edge-router`, and every staging release recreates it twice (verified in the staging release log). Each recreate:
  - refuses production connections for about 0.4–0.75 s;
  - stops the old Caddy with Docker's default 10 s timeout (no `stop_grace_period` in the foundation compose), so any production request still running after 10 s is cut. That includes Sales X-Ray uploads, which have a 900 s response budget (`AC_SALES_XRAY_UPLOAD_RESPONSE_BUDGET_SECONDS=900`), and 2 GB admin/coach uploads.
  - Over the 14 days that is about 246 edge restarts (122 production + 124 staging).
- **The Sales X-Ray worker drain** took 1 s in all 11 releases where it could be measured, so nothing long was in flight. The bound is still 960 s, and one long analysis would keep the whole site on hold for up to 16 minutes.
- **Migrations 0088–0139** (52 revisions, carried by those 22 releases) are expand-type by the rules in §3:
  - 38 add tables;
  - every `add_column` is nullable;
  - 4 relax NOT NULL (0092, 0110, 0133, 0138);
  - every CHECK replacement widens the allowed set (upgrade compared with downgrade lists);
  - 0122 builds its index CONCURRENTLY;
  - none drops, renames, retypes or backfills.
  - Data-level compatibility was not reviewed (see §3.3).

## 2. Design principles

1. **One release, one set of app containers.** api and web containers are named and aliased per release. The edge switches between releases with a **graceful Caddy reload**, never a container recreate.
2. **The database is long-lived.** An app release never restarts PostgreSQL. A PostgreSQL configuration change is its own release, and it takes the hold path.
3. **Schema changes in a release are expand-only.** Contract steps go out in a later release, after no running code needs the old shape.
4. **Old code retires by draining.** It is never killed while it holds a request or a job.
5. **The hold is the exception.** It is chosen by CI from the migrations a release carries, and it should take seconds, not minutes.

It carries over to AWS (§10, phase L): per-release task sets behind a load balancer, a one-off migration task under the same expand rules, and workers that drain or resume.

## 3. Schema rules: expand and contract

### 3.1 Classes

| Class | Allowed operations | Path |
|---|---|---|
| **expand** | Create a table, view, function or sequence. Add a nullable column, or one with a constant default (metadata-only in PostgreSQL 11+). Widen a CHECK (new allowed set ⊇ old). Relax NOT NULL. `CREATE INDEX CONCURRENTLY` on an existing table (a plain index only on a table created in the same revision). Add a CHECK or FK as `NOT VALID` and `VALIDATE` it in the same or a later revision. | rolling (no hold) |
| **contract** | Drop a table, column, index or constraint. Rename. Change a type. `SET NOT NULL`. Narrow a CHECK. Remove an enum value. | only in a release **after** the release whose code stopped using it; rolling then works, because the code running on both sides no longer needs it |
| **hold** | Data rewrites that must be atomic with a code change. Backfills over large tables inside the migration. Extension or PostgreSQL configuration and version changes. Anything that needs writers stopped. | hold path (§4.6) |

Standard recipes:
- **Rename:** add the new column → dual-write → backfill in a job → read the new column → drop the old one (contract, later release).
- **NOT NULL:** add `CHECK (col IS NOT NULL) NOT VALID` → `VALIDATE` → `SET NOT NULL`, which is quick in PostgreSQL 12+ once a valid check exists.
- **Large backfill:** a batched worker job, never the migration.

### 3.2 Making migrations safe to run while the old code serves

- **Lock timeouts.** `db/migrations/env.py` sets neither `lock_timeout` nor `statement_timeout`. Set `lock_timeout = '3s'` per migration and retry the whole revision up to 5 times with backoff. An `ALTER TABLE` waiting behind a long transaction would otherwise queue every later query on that table. Most widened CHECKs take ACCESS EXCLUSIVE briefly, and several revisions lock hot tables (`lead_desk_leads`, `memberships`).
- **One transaction per revision,** as today (transactional DDL). A failed migration leaves no change and the old code keeps serving.
- **CONCURRENTLY** needs an autocommit block, following the precedent in 0122.

### 3.3 Data compatibility during the overlap

Schema expand is not enough. While old and new code overlap, new code must not write values that old code cannot read:
- the old api overlaps for seconds;
- the old Sales X-Ray worker overlaps for up to 16 minutes;
- the old core worker overlaps for none, per §4.4.

Examples from this window:
- 0138 makes `person_photos.photo` nullable, and new code may write `storage_key` only;
- new CHECK values such as lead stages, event kinds and roles may reach an old reader.

Rule: put new values behind a switch that turns on after the release completes, or make the reader tolerant one release earlier.

### 3.4 CI gate: migration class

Add `scripts/ci/migration_class.py` to `migration-safety.yml` and wb-ci's `migrations` gate.

1. **Every new revision declares a class,** with a module-level `RELEASE_CLASS = "expand" | "contract" | "hold"`. Revisions already released, via `scripts/ci/released_migrations.py`, are exempt and recorded as historical classes; 0088–0139 are all `expand`.
2. **A static check** (`ast` over `upgrade()`) fails when a revision declares `expand` but contains any of these:
   - `op.drop_*`, `rename_table`, or `alter_column(type_=… | new_column_name=… | nullable=False)`;
   - `add_column(nullable=False)` with no constant `server_default`;
   - `create_index` on a pre-existing table without `postgresql_concurrently=True`;
   - `create_check_constraint` whose allowed literal set is not a superset of the one it replaces (both are in the file, as the downgrade shows today);
   - raw `op.execute` SQL containing DROP, RENAME, TYPE, SET NOT NULL, UPDATE, DELETE or TRUNCATE.
3. **A `contract` revision must name the release that stopped using the object** (`CONTRACT_AFTER = "<release sha>"`). The gate checks that release is an ancestor of `main`.
4. **The release bundle records the path.** The release engine computes the class over **every revision between the running production head and the new head**, since production can skip releases. It writes `AC_RELEASE_PATH=rolling|hold` into `release-images.env`. The installer takes the hold path only for `hold`, or when the PostgreSQL service definition changed.
5. **Phase M adds a dynamic proof:** run the previous release's API contract tests against the new head in the migration rehearsal ("old code on new schema"). This is the real compatibility test; the static check is the fast filter.

## 4. The release paths

### 4.1 Prerequisites (both rolling paths)

- **Graceful edge reload.** Caddy runs with `admin off`, which is why every switch recreates the container. Use these settings:
  - `admin unix//run/caddy/admin.sock` inside the container (no TCP port);
  - switch with `docker exec ac-edge-router caddy reload --config /etc/caddy/Caddyfile --address unix//run/caddy/admin.sock`.

  A reload swaps the config atomically and lets existing connections finish ("eternal grace period"). Validation stays as it is today, in a throwaway Caddy container. The hold on/off switch uses the same reload. This alone ends the staging→production blips.
- **Release-scoped upstreams.**
  - api and web run in compose project `ac-app-production-<rid12>`, with edge aliases `ac-production-api-<rid12>`, `ac-production-learner-<rid12>` and so on.
  - The release-owned route file (`edge-route-releases/<rid>/production.caddy`, already per release) is rendered with those aliases, so switching the selector symlink plus a reload moves traffic.
  - Add `lb_try_duration 10s` / `lb_try_interval 250ms` so a dial that lands just as a container leaves is retried.
  - The api adds an `X-AC-Release` response header so probes can prove which code answered.
- **Fixed-name networks.**
  - `app`, `data` and `egress` become external networks with fixed names, created once, so containers from two projects reach the same PostgreSQL.
  - PostgreSQL stays in `ac-application-production` with a stable init mount path (content-addressed under `/srv/authority-closers/application/postgres-init/<sha>`), so it is never recreated by an app release.
  - The move to fixed networks is a one-time release that takes the hold.
- **Workers keep their fixed names** (`ac-application-production-sales-xray-worker-1`). `ac-call-data`, one-pass, lead-desk-ai, partner-events, pointer-review, the canary and `infra/release/ac_release.py:4113` all hard-code that name. Workers swap one after the other (§4.4), so they don't need per-release names until phase L.
- **Fetch secrets once per install.** Run the mutation phase under one `with_release_secrets`, and let `compose_for` use the inherited environment. Cache `load_sales_xray_hosted_inputs` per target release for the run. This takes 58 fetches down to 1–2 and needs a security review; secrets stay in process memory, never in a file.

### 4.2 Path A: no migration (39 of 61 releases)

1. **Prepare.** No user impact. Verify the archive and images, load the images, render and `caddy validate` the route.
2. **Start green:** `compose -p ac-app-production-<rid12> up -d --wait api learner-web admin-web coach-web`, plus `sales-xray-web` in its own per-release project.
3. **Probe green directly on `ac_edge`:**
   - `/health/ready` on `ac-production-api-<rid12>:8000`;
   - learner `/`, admin `/login`, coach `/login`, salesxray `/`;
   - the release header.
4. **Retire the old writers that must not overlap:**
   - SIGTERM the old Sales X-Ray worker. It stops claiming at once and finishes in-flight work (`ci/service.py:179-190`, `ci/runner.py:247-265`).
   - Stop the exec'd runners (`ac-call-data` `stop_container_runner`).
   - Stop the old core worker (30 s).
5. **Switch:** selector symlink → green route, then `caddy reload`. Run `check_route` on every host, expecting the new `X-AC-Release`.
6. **Drain blue web and api:** `stop --timeout 900` on the blue api. It gets no new requests, and uvicorn exits as soon as in-flight requests (uploads) finish. Then stop blue web (30 s).
7. **Start the new core worker** right after the switch.
8. **When the old Sales X-Ray worker exits 0 (≤16 min), start the new one.** Jobs created meanwhile wait in `jobs`, leased by `FOR UPDATE SKIP LOCKED` (`outbox/repository.py:322-386`). Nothing is lost or run twice. The only cost is up to drain-time queue latency, and only when a long job was in flight.
9. **Record** the committed evidence. Keep blue's containers stopped, not removed, until the next release, for rollback.

No hold, no PostgreSQL restart, no fence.

### 4.3 Path B: expand-only migration (22 of 61, every one in this window)

1. **Path A step 1** (prepare). Blue keeps serving, and green is not started yet.
2. **Pre-migration dump, unfenced.** `pg_dump` takes an MVCC snapshot without blocking writers. Write the sha256 and head into the receipt, as `take_pre_restart_snapshot` does today. It takes about 3 s.
3. **`alembic upgrade head` while blue serves,** with the lock timeouts from §3.2. No fence: the fence (:1467) ends every `ac_runtime` session, including a draining Sales X-Ray worker, and would turn in-flight provider calls into ambiguous dead-letters (`outbox/repository.py:452-480`). A failure rolls the revision's transaction back; blue never stopped, so the release just aborts.
4. **Start green and continue** with Path A steps 2–9.

### 4.4 The analysis worker in detail

Verified on `main` (code audit, 27 Oct):
- **Claims are exclusive:** `FOR UPDATE SKIP LOCKED` plus a lease token and `leased_until`, re-checked at every phase (`outbox/repository.py:1736-1824`).
- **SIGTERM stops claiming before the next unit and finishes in-flight work.** Per-job bounds are: provider call 860 s, native C1 750 s, plan step 30 s. All fit inside the 16-minute grace.
- **Kill recovery:**
  - a local stage is reclaimed after its 15-minute lease and rerun, up to 5 attempts;
  - a provider stage killed after its dispatch marker becomes an ambiguous dead-letter and is never re-sent. A kill loses a paid result; it never pays twice.

So a drain must never be cut short.

**Why not overlap old and new worker today:** nothing routes a job to the right version.
- Job kinds are all `.v1`.
- `policy_revision` is not used in claims.
- Mismatches fail closed: the approval digest holds the plan, an unknown plan field holds it as coordinator-failed, a provider-input hash mismatch dead-letters the job, and the native helper accepts one image ref.

An old worker that picks up a new-shape job fails it instead of leaving it. The core `worker` is worse: `claim_pending` takes every pending outbox event and dead-letters unknown event types (`outbox/repository.py:1002-1008`, `:1076-1088`). Hence the order above:
- core worker: stop old before the switch, start new after it;
- Sales X-Ray worker: SIGTERM old before the switch, start new after its exit.

Guards that would allow overlap later (phase M):
1. Bump the job kind (`.v2`) on any semantic change. The claim already filters by kind.
2. The plan scheduler skips, rather than holds, plans whose authority or manifest version isn't its own.
3. The outbox claim takes only event types the worker knows and leaves the rest pending.
4. The native helper accepts both image refs during the overlap.
5. Renew the provider-job lease during the call. Today it is renewed once at dispatch, which leaves about 40 s of slack (`ci/inference_worker.py:440-462`).

### 4.5 Backups

| Path | Recovery point | Where it is taken | Cost to users |
|---|---|---|---|
| A (no migration) | latest 5-minute logical backup (`ac-postgres-backup.timer`; production dump 17.3 MB, cap 64 MiB), id recorded in the release record | not needed in the release | none |
| B (expand) | unfenced `pg_dump` immediately before migrate (sha256 receipt) | outside any hold | none |
| Hold | fenced `pg_dump` inside the hold, as today | inside the hold, ≈3 s once overhead is gone | seconds |

The 5-minute logical backup alone can't be the pre-migration point, because it can miss up to 5 minutes of writes. It is the fallback.

Restoring an unfenced dump after writes have continued is a **forward data change** under OWNER-APPROVED DATA CHANGES, never automatic. This matches today's rule: "Destructive rollback is forbidden after write exposure" (:1526).

### 4.6 The hold path, made short (rare)

Used only for `hold`-class migrations or a PostgreSQL change.
1. **Drain the Sales X-Ray worker first, with no hold:** SIGTERM, wait for exit 0. Users are unaffected and jobs queue.
2. **Pre-start green containers** without traffic, if they don't need the new schema to boot. Otherwise `docker create` them.
3. **Hold on** (reload) → stop api and core worker → fence → dump → migrate → start or attach green → **hold off** (reload) → start workers.

Target: ≤30 s, versus 175 s today. With secrets fetched once and no PostgreSQL recreate, even today's order would take about 45–60 s.

## 5. Rollback, per path

| Path | App rollback | Schema | Data |
|---|---|---|---|
| A | Start blue (stopped, kept) → wait healthy → symlink back + `caddy reload` → drain green. Workers swap back the same way. About 15–20 s, with no user-visible gap. Same checks as `rollback_application_only` (head must match). | unchanged | unchanged |
| B | Same as A: old code runs on the expanded schema by definition. The schema stays forward, and there is no downgrade. | stays expanded | new columns or rows written by green stay, and blue ignores them |
| B, migration fails | Nothing to roll back: the revision's transaction aborts and blue never stopped | unchanged | unchanged |
| B, bad data found later | Forward fix. Restoring the pre-migration dump is an owner-approved data change and loses later writes. | — | — |
| Hold | As today: before write exposure, automatic restore of the fenced dump plus the previous release and route. After write exposure, forward recovery only (`record_forward_recovery_required`). | restored or forward | restored or forward |
| Edge | The previous route file stays in `edge-route-releases/`. Symlink back + reload. | — | — |

## 6. Release windows from data (owner addition a)

The owner, 27 Oct: releases should happen when research and telemetry say the fewest clients are working.

### 6.1 What production shows

All reads were counts only and logged: `zdr-usage-by-hour.sql` and `zdr-usage-weekday.sql`.

**`sx.*` telemetry arrives almost at once.** Across 6,402 events, the time from event to stored row was p50 3 s, p90 4 s, p99 15 s. That is fast enough for a 15-minute gate.

**Telemetry by IST hour and day** (events/people; "." means none). The notice took effect at 00:00 IST on 24 Oct, so there are three full days:

| IST hour | Sat 24 | Sun 25 | Mon 26 |
|---|---|---|---|
| 00 | . | . | 165/3 |
| 01 | . | . | 231/2 |
| 02 | . | 50/2 | 211/3 |
| 03 | . | 159/1 | . |
| 04 | . | 107/2 | 103/2 |
| 05 | . | . | 33/2 |
| **06** | . | . | **1/1** |
| **07** | . | . | **1/1** |
| **08** | . | . | **3/1** |
| 09 | . | 20/1 | 237/3 |
| 10 | 85/1 | . | 26/1 |
| 11 | . | . | 275/2 |
| 12 | 51/1 | . | 121/1 |
| 13 | 218/2 | 274/1 | 142/1 |
| 14 | 277/2 | . | . |
| 15 | 84/2 | 69/1 | 13/1 |
| 16 | . | 200/2 | . |
| 17 | 4/1 | 175/2 | 388/2 |
| 18 | 12/1 | 942/3 | 13/1 |
| 19 | 12/1 | 370/2 | 145/2 |
| 20 | . | 436/1 | 72/1 |
| 21 | 91/3 | 159/1 | 64/2 |
| 22 | 25/1 | 158/2 | 1/1 |
| 23 | . | 83/2 | 32/1 |

The 14-day hourly averages (lead desk, sign-ins, uploads) are in the table below.

**Every hour of the day saw someone on at least one of the three days.** The quietest stretch is 06:00–09:00 IST: nobody on Saturday or Sunday, and one person with 1–3 events on Monday. Weekend evenings are busy; Sunday 18:00 was the busiest hour, with 942 events from 3 people.

**A weekday pattern can't be read yet:**
- telemetry covers 3 days;
- 14 days of lead-desk events are dominated by one person's bulk imports (774 events on a Wednesday at 17:00, 382 on a Friday at 00:00, 341 on a Sunday at 16:00), so they don't measure sellers at work.

**The numbers are small.** 17 people made an authenticated request in the 14 days, staff, testers and smoke accounts included.

**Live check at 02:25 IST on 27 Oct:** 1 person active in the last 15 minutes (sessions) and 1 in telemetry; 0 analysis jobs leased; 0 queued.

So a fixed schedule drawn from this data would be a guess. The rule must be a **live gate**, with 06:00–09:00 IST as the fallback slot until 4 weeks of telemetry exist.

The 14-day hourly view, kept from the first pass:

| IST hour | lead events/day | telemetry events/day | max people active (app / lead desk) | uploads/day | sign-ins/day |
|---|---|---|---|---|---|
| 00 | 27.4 | 55 | 3 / 1 | 0.36 | 0.36 |
| 01 | 0.1 | 77 | 2 / 1 | 0.21 | 0.64 |
| 02 | 0.6 | 87 | 3 / 1 | 0.57 | 0.43 |
| 03 | 0.3 | 53 | 1 / 1 | 0.43 | 0.29 |
| 04 | 0.6 | 70 | 2 / 1 | 3.64 | 0 |
| 05 | 0 | 11 | 2 / 0 | 0.14 | 0.07 |
| **06** | **0** | **0.3** | **1 / 0** | **0.07** | **0** |
| **07** | **0** | **0.3** | **1 / 0** | **0.21** | **0** |
| **08** | **0** | **1.0** | **1 / 0** | **0.14** | **0** |
| 09 | 0 | 85.7 | 3 / 0 | 0.14 | 0.14 |
| 10 | 1.6 | 37 | 1 / 1 | 1.00 | 0 |
| 11 | 0.5 | 91.7 | 2 / 1 | 2.14 | 0.07 |
| 12 | 1.1 | 57.3 | 1 / 1 | 2.14 | 0.50 |
| 13 | 1.4 | 211.3 | 2 / 1 | 0.14 | 0.43 |
| 14 | 0.6 | 92.3 | 2 / 1 | 0.29 | 0.57 |
| 15 | 2.1 | 55.3 | 2 / 1 | 0.29 | 0.14 |
| 16 | 25.9 | 66.7 | 2 / 1 | 0.29 | 0.21 |
| 17 | 57.1 | 189 | 2 / 2 | 0.21 | 0.29 |
| 18 | 0.1 | 322.3 | 3 / 2 | 0.21 | 0.29 |
| 19 | 0 | 175.7 | 2 / 0 | 0.29 | 0.64 |
| 20 | 0.1 | 169.3 | 1 / 1 | 0.07 | 0.43 |
| 21 | 0.1 | 104.7 | 3 / 1 | 0.07 | 0.07 |
| 22 | 0.6 | 61.3 | 2 / 2 | 0.21 | 0 |
| 23 | 0.3 | 38.3 | 2 / 1 | 0.21 | 0.36 |

Totals:
- lead desk: 1,685 events by 5 people in 14 days;
- telemetry: 6,338 events from 7 people in 3 days;
- 83 sign-ins and 189 uploads in 14 days.

### 6.2 The quiet-slot gate in ac-ship

**Signals.** One checked-in module, `ac_platform.release_gate`, ships with each release. ac-ship runs it inside the running production api container in a `READ ONLY` transaction and gets JSON counts only. The result goes into the release record (`AC_QUIET_GATE_*`). It is a release control, not an ad-hoc query.

1. **`client_people_15m`** (primary): distinct people with a non-revoked session whose `last_seen_at` is within the last 15 minutes.
   - Every authenticated request advances `last_seen_at` (`identity/application.py:489-494`), so it counts people who opted out of telemetry and old Android builds too.
   - It excludes the AC team: members of the operations tenant (from Infisical, like the other managed tenant references), staff, the ac-qa smoke accounts and the release probe.
2. **`telemetry_people_15m`**: the same from `sx.*` events, as corroboration. It covers consenting people only.
3. **`analyses_in_flight`**: `jobs` leased with kind `conversation.inspect_local.v1` or `conversation.infer_provider.v1`, plus call-data runs marked running.
4. **`requests_in_flight`** (after S1): from Caddy's metrics over the admin socket. A long upload is invisible to the database until it finishes.

**Rule:**

| Release path | Switch when | Otherwise |
|---|---|---|
| Hold (today's installer, until S3) | `client_people_15m = 0` and `analyses_in_flight = 0` | re-check every 5 min |
| Rolling A/B (after S3/M) | no gate is needed for safety. For the first 2 weeks of each new path: `client_people_15m ≤ 2` | re-check every 5 min, wait at most 2 h, then switch |
| Any, `ac-ship --urgent "<reason>"` (P0) | at once | the counts and the reason are recorded; the Updating banner shows |

**Deadline.** A hold-path release that hasn't passed by the end of the fallback slot (09:00 IST) moves to the next day's slot, and the releases Telegram line says so.

**Learned slot.** Once 28 days of telemetry exist, the "next quiet slot" replaces the fixed 06:00–09:00 slot:
- it is the hour in the next 24 h with the fewest expected people, averaged over the last 4 matching weekday-hours;
- the live gate still decides.

**Per ring** (§7):
- the internal ring may switch at any time;
- the testers ring at its own organisations' quiet slot;
- everyone at the global slot.

## 7. Staged rollouts (owner addition b)

The owner, 27 Oct: app updates could reach different people at different times, based on telemetry and usage.

### 7.1 Web: rings per organisation

Three rings: **internal** (the AC team), **testers** (tester-programme and pilot organisations) and **everyone** (the default).

**Store.** `release_ring_assignments(tenant_id, ring, assigned_by, assigned_at, superseded_at)` is append-only: a change supersedes the old row and never overwrites it. It is set from Admin → Organisations, or by a `scripts/data-changes/` script, since product switches per workspace are an approved data-change kind. Each change writes an audit event.

**Two levers.**

1. **Server-side feature flags, for behaviour.**
   - `feature_flags(key, stage, killed, …)`. A stage of internal, testers or everyone says how far the flag has rolled out.
   - The API evaluates flags for the selected tenant, and `/v1/me` returns the ones that are on. The web, the Android app's bundled web and the API itself all read them.
   - Stop: move the stage back or set `killed`. It applies on the next request, with no deploy. Every change is an audit event.
   - This is the lever for most features. There is no flag system today; capability grants are the nearest thing.
2. **Web version rings, after S3.**
   - A candidate web build runs beside the current one, using the per-release upstreams from §4.1.
   - The API sets an `ac_ring` cookie (HttpOnly, Secure, SameSite=Lax) from the selected tenant's ring. It does so on sign-in, on tenant switch and on `/v1/me`.
   - Caddy sends `salesxray.` page requests that carry `ac_ring=internal|testers` to the candidate's upstream. The cookie only chooses a web build; the API still checks everything.
   - **The API stays one version for everyone.** The expand rules let it serve both builds, so the API ships first and the web follows ring by ring.
   - A tenant switch that changes ring does a full page load.

**Promotion.** internal → testers → everyone, after a soak: internal at least 2 h, testers at least 24 h. Each step needs both of these:
- `GET /v1/admin/telemetry/gate` passes for the candidate's release, filtered to that ring's tenants. The filter is new; the gate itself exists (`telemetry/improvement.py:701`, "not_enough_data never blocks").
- Script-error and slow-API counts are flat.

**Stop and roll back.** One reload points the ring route back at the current build, in seconds. Rolling back the everyone ring is §5, Path A.

**Open tabs must not break.** A tab on the old build lazy-loads `/_next/static/*` from its own build.
- Route `/_next/static/*` to the current build, and on a 404 retry the previous or candidate build. Keep the previous web container for 24 h (about 100 MB).
- The Updating banner session's client offers a reload when `X-AC-Release` changes.

Without this, a switch can break navigation in a tab that is already open.

Admin, learner and coach web can use the same mechanism later. Start with `salesxray.`.

### 7.2 Android: Play tracks and staged rollout

**What exists:**
- The app is a Capacitor app that carries its own web copy, built at `web_ref`. `/v1` calls go to the production API.
- versionCode is 100000 plus the play.yml run number.
- `scripts/play-upload.py` signs in keyless (WIF). The service account may release to **testing tracks only**. An internal release goes out completed; every other track is left as a draft for the owner.
- In-app updates (`StoreUpdates.java`): priority 0–3 is a flexible "Update available" with Later; 4–5 forces the update.

**Ladder for one versionCode:**

| Stage | Who | Promote when |
|---|---|---|
| Internal testing (completed) | AC team | automatically after the production web ship, as now |
| Closed testing "Alpha" | tester Google Group | at least 24 h on internal, and: Crashlytics crash-free users ≥ 99.5% for the version, no new top crash, and the telemetry gate passes for `sx.app_launch`, frames and key actions on that app version |
| Production, `inProgress`, `userFraction` 0.10 | random 10% of production users | at least 24 h on Alpha, same gates |
| Production 0.50, then `completed` | everyone | at least 24 h per step, same gates |

**What it needs:**
1. **play-upload.py commands:**
   - `promote <versionCode> <track> [fraction]`;
   - `halt <track>`;
   - `complete <track>`.

   Each is one `edits.tracks.update`, with status inProgress, halted or completed and the `userFraction`.
2. **An owner decision on production:** let the service account release to production, which is a Play Console permission, or keep the production steps as owner clicks, with ac-ship preparing the draft and posting the gate result.
3. **Gate inputs per versionCode:** our telemetry already records the app version. Crashlytics needs a read path, such as a Firebase or BigQuery export, which isn't set up.

**Stop and roll back:**
- **Halt** sets status `halted`: no more devices get that version, and devices that already have it keep it.
- **Play can't downgrade.** Roll forward with versionCode + 1 built from the last good apps ref and `web_ref`, at priority 4–5 if it must be taken.
- **The fastest lever is on the server.** Feature flags reach the bundled web too. Proposed: a "use live web" switch in the app's `/v1` config, so a bad bundled copy can be bypassed with no Play release. It isn't built, and BundledWeb's fallback behaviour isn't verified.

**API compatibility:**
- Every bundle still in the field calls the production API.
- A contract-class API change waits until bundles older than the change are under 1% of active devices (from telemetry), or until a forced update has gone out.

**Timing:** the in-app prompt must not interrupt a call or a recording upload.
- A flexible update installs on the next move to the background.
- A forced update is only for a fix that must be taken.

Play's production percentage is random per user and can't target an organisation. On Android, "different people at different times" means the closed ring first, the staged percentage next, and a prompt that waits for an idle moment.

## 8. Inbound integrations (owner addition c)

The owner, 27 Oct: nothing should stop during an update, Meta webhooks and other inbound leads included.

This coordinates with Lead OS's `docs/product/lead-desk/release-safe-intake.md` (bbd99bf85, on the workbench branches, not yet on `main`).

**Their findings:**
- Meta lead ads (36 h of retries, plus the 10-minute pull), WhatsApp (7 days of retries) and Google Ads (retryable, plus the 10-minute pull) already survive a hold.
- `POST /v1/lead-desk/capture/{id}` (website forms, plus Zapier, Make and Pabbly) loses leads.

**Their fix:** `intake-spool`, a small receiver in the foundation compose. The hold route sends the capture paths to it, and it replays them after the release and on a 5-minute timer.

**How the two designs fit:**
1. **Rolling paths have no hold.** In Paths A and B the API answers webhooks and capture requests throughout:
   - the old api finishes its in-flight requests (900 s drain);
   - a graceful reload drops no connection (S1).

   With S3 and M in, no webhook sees a 503 because of a release.
2. **The spool is still needed:**
   - until S3 ships;
   - for the rare hold path (§4.6, ≤30 s);
   - for an API crash outside a release (their "later" item: always write, then forward; on AWS that maps to API Gateway plus SQS).

   It is independent of this plan, so ship it now.
3. **Shared files mean sequential pull requests.** Both change `production-hold.caddy`, `staging-hold.caddy` and the foundation compose: the spool adds a service next to the edge, and S1 adds the admin socket. **The spool PR goes first**, because it protects leads today. S1 rebases on it.
4. **Replay hook.** Their installer hook runs after write exposure. On the rolling paths there is no hold, so it finds nothing. Keep calling it after every switch (it is idempotent); the 5-minute timer stays the safety net.
5. **Core-worker gap.** Inbound events go to the outbox. The core worker swaps one after the other (§4.4), so an event waits seconds and is only ever seen by the new worker. M5's outbox guard (unknown types stay pending) matters only once old and new workers overlap.
6. **One drill for both.** The release probe (§10) adds, through every staging release on each path:
   - a capture POST every 5 s;
   - a signed staging Meta test webhook.

   Each must be filed exactly once, with 0 5xx. This is the drill Lead OS proposes.
7. **Make holds measurable.** Their doc notes the edge keeps no access log. With S1, Caddy's metrics (requests by host and status) are readable over the admin socket. Each release record then stores the 5xx count during the switch, which turns "no webhook saw the hold" into a number.

## 9. Two or more API processes on the current box (orchestrator addition)

**Why.** Production's API is one uvicorn process: `CMD ["uvicorn", "ac_platform.http.app:app", …]` with no `--workers` (`infra/application/Dockerfile.python:61`). Every request shares one event loop.

Anything that holds that loop stalls everyone:
- a full garbage collection, about 245 ms before `settle_startup_heap()`;
- a C-level GIL hold, 3.7 s on 26 Oct;
- synchronous work.

The loop watchdog says as much in its own header (`application/loop_watchdog.py`). Bug-radar's telemetry (side notes `perf-20261027/findings.md`) shows slow calls, those over 1.5 s, at p75 of 4.5–10.8 s across availability, submissions, updates, chats, notifications and leads. Before v0.98 they came in bursts across many endpoints at once, the mark of a whole-process stall.

### 9.1 What changes with N processes (verified on `main` 4081f055)

| State held in the process | Where | Effect with N processes | Needed |
|---|---|---|---|
| **Token-bucket rate limits.** `InMemoryTokenBucketLimiter`, documented as a "single-process limiter" | `http/rate_limits.py:243`. Default rules :32–225: sign-in codes and passwords (5–20 per 10–15 min), OAuth start and callback, the guest acquisition session (5 per 15 min per address), telemetry batch (120/min), public catalogues (300/min), community | Each limit becomes up to N× looser, and unevenly: it depends on which process takes the request. Sign-in and abuse shields weaken. | Shared limiter, or `capacity / N` for abuse rules (below) |
| Integrations API key (120/min) | `integrations/api_http.py:69, :532` | A customer-facing promise turns fuzzy, anywhere from 120 to N×120 | **Shared limiter** |
| Admin staff key (60/min) | `admin_settings/staff_keys.py:102, :297` | Same | Shared limiter |
| OAuth client registration (10/h per address, 200/h in total) | `integrations/oauth_http.py:91–104, :207` | The "in total" cap becomes N×200 | Shared limiter |
| Native-app sign-in (start 5, poll 120, decide 20, refresh 30 per 10 min) | `http/native_devices.py:103–110` | Looser; a poll split across processes still works | Shared limiter, or `capacity / N` |
| Bug reports (12/h per person), feedback (30/h per person) | `bug_reports/http.py:138`, `feedback/http.py:77` | Looser | `capacity / N` is enough |
| Memos with a TTL: the "analysis paused" switch (10 s), org insights (LRU with a TTL) | `http/conversation_execution_control.py:37`, `conversation_intelligence/org_insights.py:76` | Each process warms its own copy. A change shows within the same TTL as today. | Nothing. Rule: never a write-through invalidation that clears only the local process |
| Telemetry retention purge, at most one batch per hour per process | `http/telemetry.py:567` | N bounded batches an hour | Nothing |
| Budget-ledger memo, as named by the orchestrator | not on `main` 4081f055 under that name | A spend cap checked against a per-process memo would let N processes each spend up to the cap within the memo's TTL | If it lands, it must read the ledger row (or a `FOR UPDATE` on it), not a memo |
| Loop watchdog and `settle_startup_heap()` | `http/app.py:127–137` | One per process. It only observes and logs; it never kills. | Add the pid to `event_loop_blocked` and `gc_pause` lines |
| DB pool: default `create_async_engine` (5 + 10 overflow) | `db/session.py:10` | Up to 15 connections per process. Postgres allows 100, and 11 `ac_runtime` connections were in use at 20:5xZ on 26 Oct. | Set `pool_size=5, max_overflow=5` explicitly. Two replicas plus blue/green overlap then stay ≤ 40 api connections. |
| Streams: no WebSockets or SSE. `StreamingResponse` serves audio, video and report bytes | `http/conversation_playback.py`, `media_delivery.py`, `studio_video_preview.py` and others | Stateless. A drain waits for them, within the 900 s budget. | Nothing |
| Background tasks in the API: only the watchdog (lifespan, `http/app.py:127`) | — | Nothing gets run twice | Nothing |

`media/processing.py:60` (`_WORKSPACE_BUDGET_RESERVED`) is a per-process disk reservation for Studio video transcodes. It runs in the core worker, so API replicas don't touch it.

### 9.2 Two shapes, and the recommended one

| | A. `uvicorn --workers 2` in one container | **B. Two api containers as separate Caddy upstreams (recommended)** |
|---|---|---|
| A stalled process | Keeps the keep-alive connections Caddy already holds to it. New requests on those connections wait. Uvicorn (0.52.4 here) restarts a dead worker, not a stalled one. | `lb_policy least_conn` gives it fewer requests: its in-flight count climbs. An active health check on `/health/live` (exists, `http/app.py:454`) every 2 s with a 1 s timeout marks it down, and passive `unhealthy_latency 5s` does too. New requests go to the healthy replica within about 2–5 s. |
| Health | One container health check can't see one stalled worker | One check per replica |
| Request spread | Per connection, so uneven | Per request (Caddy picks an upstream for each request) |
| Memory | About 2 × 215 MiB inside one 768 MiB limit: too tight, raise it to 1 GiB | Each replica keeps its own 768 MiB limit |
| Fit with §4 | — | `docker compose up --scale api=2` inside the per-release project. Caddy 2.11.4 (running) resolves the release alias with `dynamic a ac-production-api-<rid12> 8000 { refresh 2s }` and treats each replica as its own upstream. |

### 9.3 Memory and the smallest safe step

**Memory.** The api container uses 214–220 MiB. A second replica adds about 215 MiB, because separate processes share nothing.
- Steady state: +0.2 GB against 7.4 GB available.
- During a blue/green overlap with 2 + 2 replicas: about +0.45 GB more, while blue drains (≤900 s).

That fits, but swap is already 3.7 of 4 GB, so the probe watches swap and blue web stops first.

**How it fits the rolling switch.** Green starts with 2 replicas, waits for both to be healthy, then the reload moves the dynamic upstream to green's alias. Blue's 2 replicas drain as in §4.2. The hold path starts both before hold-off. On AWS this is ECS `desiredCount: 2` behind the ALB. The shared limiter stays in Postgres, or moves to ElastiCache later.

**Smallest safe step,** in order (S5 then S6 in §10):
1. **Rate limits** (api lane, 1–2 days).
   - `PostgresTokenBucketLimiter`: the same interface as `InMemoryTokenBucketLimiter`, one atomic `INSERT … ON CONFLICT DO UPDATE … RETURNING tokens` per limited request on a new `rate_limit_buckets(rule, key_sha256, tokens, updated_at, expires_at)` table. That is an expand migration, keys are stored hashed, and expired rows are swept.
   - Use it for the **throughput rules**: integrations key, staff key, telemetry batch, public catalogues, native poll, OAuth register-all. Halving those could 429 a legitimate client whose requests happen to land on one replica.
   - For the low-capacity **abuse rules** (sign-in codes and passwords, guest session, community, bug reports, feedback), `ceil(capacity / AC_API_REPLICAS)` per process is enough for now. It fails closed: at worst a person meets the limit a little sooner. Move them to the shared limiter later.
2. **Explicit pool size** (`pool_size=5, max_overflow=5`), and the pid in watchdog lines.
3. **`AC_API_REPLICAS=2`**, read by the limiter and the compose file.
4. **Two replicas behind Caddy** (devenv, 1 day, after S1, because changing the upstream config needs the graceful reload):
   - `least_conn`;
   - active and passive health checks as in §9.2;
   - `lb_try_duration 10s`.
5. **Measure.** Bug-radar's `sx.api_slow` and the watchdog's `event_loop_blocked` lines, with the pid, should show a stall on one replica no longer slowing the other. Expect a lower p75 for slow calls.

**Tests:**
- limiter unit tests for refill, expiry and two concurrent sessions spending the same bucket;
- a two-process test: two uvicorn processes on one database admit ≤ capacity in total;
- `caddy validate` for the dynamic-upstream config;
- a **staging stall drill**: `docker pause` one replica under the release probe. Expect 0 5xx, and p99 back under 2 s within 5 s. Requests already inside the paused replica wait until it resumes, which the drill reports.

## 10. Phases

### S — days (devenv lane, plus S5 in the api lane; after Lead OS's spool PR)

| Task | What | Size | Proof |
|---|---|---|---|
| S1 | Caddy admin on a unix socket. `activate_edge_route` and `reconcile_edge_router` reload instead of recreating. `lb_try_*` on upstreams. Caddy metrics readable over the socket. Foundation compose and Caddyfile change, shipped as a foundation release. | 1 day | Probe (below) at 20 rps through 40 staging route switches: 0 refused connections and 0 5xx on production hosts. A 120 s slow upload survives a switch. |
| S2 | Secrets fetched once per install. Hosted-inputs result cached. Stable PostgreSQL init mount, so no recreate. | 1–2 days | Staging release log shows ≤3 Infisical fetches. Journal shows no PostgreSQL recreate. Measured staging hold ≤60 s. |
| S3 | Path A: per-release api/web projects and aliases, rendered route, reload switch, drain with `--timeout 900`, sequential worker swap, rollback by reload. The engine picks Path A when the head is unchanged. Includes the one-time fixed-network release (hold) and static-asset fallback for open tabs. | 2–3 days | Probe through 10 staging Path-A releases and 3 rollbacks: 0 5xx, `X-AC-Release` flips once. A slow upload started before the switch completes. Synthetic jobs queued across the switch each reach exactly one terminal state with `attempt_count = 1`. An old-build tab still navigates after the switch. Then the first 3 production Path-A releases under the probe. |
| S4 | Quiet-slot gate (§6.2): `ac_platform.release_gate`, plus `--urgent` and the deadline in ac-ship. It replaces the manual window rule. | 1 day | Fixture tests at the 15-minute boundary, with excluded tenants, analyses in flight and the urgent override. A dry run on production records the counts. |
| S5 | (api lane, in parallel with S1–S3) A shared limiter for the throughput rules, `capacity / N` for the abuse rules, an explicit pool size and the pid in watchdog lines (§9.3 steps 1–3) | 1–2 days | Two processes against one database admit no more than the rule's capacity. Limiter unit tests (refill, expiry, two concurrent sessions). |
| S6 | Two API replicas behind Caddy: dynamic upstreams, `least_conn`, health checks (§9.3 step 4), after S1 and S5 | 1 day | Staging stall drill: pause one replica under the probe; 0 5xx, and p99 recovers within 5 s. |

### M — 1–2 weeks (devenv, api, admin and apps lanes)

| Task | What | Size |
|---|---|---|
| M1 | `migration_class.py` gate with declared classes and `AC_RELEASE_PATH` in the bundle; the engine computes it from production head to new head | 2 days |
| M2 | Migration runner: `lock_timeout` and retry in env.py; unfenced pre-migrate dump with receipt | 1–2 days |
| M3 | Path B in the installer | 2 days |
| M4 | "Old code on new schema": the previous release's API contract tests against the new head, in the migration rehearsal | 2–3 days |
| M5 | Worker guards (api lane): job-kind bump rule, outbox leaves unknown types pending, plan scheduler skips foreign plans, native helper takes two refs, provider-lease renewal | 3 days |
| M6 | Sales X-Ray worker overlap (new worker starts at the switch) once M5 is in | 1–2 days |
| M7 | Short hold path (§4.6) | 1 day |
| M8 | Rings and flags (api + admin): `release_ring_assignments`, `feature_flags`, `/v1/me` flags, Admin → Organisations ring control, a ring filter on the telemetry gate | 2–3 days |
| M9 | Web version rings (devenv + ui): `ac_ring` cookie, ring routes in Caddy, promote and stop commands in ac-ship | 2 days |
| M10 | Play ladder (sales-xray-apps): `promote`, `halt` and `complete` in play-upload.py, gate checks, idle-time update prompt; the owner's decision on production permission | 1–2 days |

### L — with AWS phase 2 (weeks)

| Task | What |
|---|---|
| L1 | PostgreSQL out of the app project into its own lifecycle (maps to RDS) |
| L2 | Per-release worker containers, with host scripts discovering the name |
| L3 | Provider-stage reconciliation, so a killed provider call is fetched by its provider job id instead of dead-lettered. Needed because Fargate's `stopTimeout` maximum is 120 s and a Spot interruption warning is 2 minutes, both far below the 16-minute drain. |
| L4 | ECS mapping: one service per process; rolling deploy (minimum healthy 100%, maximum 200%) or CodeDeploy blue/green behind the ALB; API deregistration delay 900 s (upload budget); circuit breaker with rollback; migrations as a one-off task before the service update, gated by the same class check |
| L5 | Canary: weighted routing (Caddy weights, then ALB weighted target groups) before a full switch |
| L6 | Learned quiet slot (§6.2) once 28 days of telemetry exist; per-ring slots |
| L7 | Crashlytics read path (Firebase or BigQuery export) feeding the Play gate |
| L8 | Permanent store-and-forward intake in front of the capture route (Lead OS's later item; API Gateway plus SQS on AWS) |

### Tests that prove it

- **`scripts/ops/release-probe.py`** (new; runs on `ac` against `127.0.0.1:8080` with Host headers, and from outside through Cloudflare). It drives a mixed load at about 20 rps:
  - api `/health/ready`;
  - learner, admin and salesxray pages and a static asset;
  - an authenticated read as an ac-qa smoke account;
  - a telemetry batch POST;
  - one slow 120 s upload to a staging test account;
  - a lead capture POST every 5 s and a signed staging Meta test webhook.

  It asserts 0 responses ≥500, 0 connection errors, p99 < 2 s and a single old→new flip of `X-AC-Release`. Every capture and webhook must be filed exactly once. It writes evidence JSON into the release record. It runs on every staging release and on the first production releases of each new path.
- **Migration class unit tests:** fixture revisions for each forbidden op, a declared-class mismatch and a CHECK narrowing. Regression: 0088–0139 classify as `expand`.
- **Job integrity test on staging** (fixture providers, no paid calls): enqueue K jobs, release mid-flight, and assert one terminal state each, no dead-letter and no duplicate result rows. Outbox: emit a new event type during the switch and assert it is not dead-lettered (after M5).
- **Quiet gate tests:** sessions and jobs at the window edges; excluded tenants; deadline postponement; urgent override recorded.
- **Ring tests:** an internal-ring tenant gets the candidate build (by `X-AC-Release`) and others get the current one. One stop command reverts it. A flag set to internal is off for an everyone-ring tenant.
- **Play dry run:** on the internal and Alpha tracks with a test build: promote, halt, resume and complete through the API.
- **Rollback drill on staging** under the probe, every phase.

## 11. Risks

| Risk | Mitigation |
|---|---|
| Memory: blue and green overlap. The second api/web set is about 470 MB resident against 7.4 GB available, but swap is 3.7 of 4 GB used. | Overlap is seconds for web and ≤15 min for an idle blue api; watch swap in the probe; stop blue web first. |
| A migration lock queue on a hot table while blue serves | `lock_timeout` 3 s + retry; CONCURRENTLY; NOT VALID + VALIDATE |
| Data written by green unreadable by the old worker during its drain | §3.3 rule, M4 test, M5 guards |
| The Caddy admin socket widens the attack surface | Unix socket inside the container only; no port; the config stays file-owned and validated |
| Fixed-network move needs one hold release | Run it through the quiet gate |
| A long drain delays new analyses by up to 16 min | Only when a long job is in flight (measured drain: 1 s in all 11 measured releases); removed by M6 |
| Path selection wrong (expand declared, contract in effect) | Static gate + dynamic M4 test; the engine computes the class over the whole head range |
| Exec'd runners (`ac-call-data`) killed mid-call can cause one duplicate paid call (`call_data/engine.py:206-225`) | Stop them at drain start (S3) |
| The quiet gate never passes, because a client is always on | Deadline at the end of the fallback slot, then the next day; `--urgent`; the gate is soft on the rolling paths |
| Telemetry undercounts (opt-outs, old app builds) | The gate's primary signal is `sessions.last_seen_at`, which doesn't depend on consent |
| An open tab breaks after a web switch | Static-asset fallback to the previous build for 24 h; reload prompt |
| A bad bundled web copy on Android can't be downgraded | Halt; roll forward with versionCode + 1; feature flags; proposed "use live web" switch |
| Spool and S1 edit the same hold and foundation files | Sequential PRs, spool first (§8) |

## 12. Found on the way (not part of this plan)

- **Staging 5-minute logical backups are failing:** "The staging logical dump exceeded its fixed size bound" (`ac-postgres-backup.service`, 26 Oct 20:40Z). Production's dump is 17.3 MB, about 27% of the 64 MiB cap.
- **Swap on `ac` is nearly full** (3.7/4.0 GB).
- **The provider-job lease is renewed only once,** at dispatch. A call near its 860 s limit has about 40 s of lease slack.
- **Failed systemd units left on `ac`:** `ac-release-train`, `ac-cut-v092`, `ac-cut-v095` and `ac-ship-v09x-resume*`.
