# S3: releases with no migration switch with no hold (plan)

Status: plan, 28 Oct 2026. It follows S1 (graceful edge reload) and S2 (one secret fetch, PostgreSQL left running) from `docs/ops/ZERO-DOWNTIME-RELEASES.md`. Lane: devenv. Size: 2–3 days, then proof on 10 staging releases.

## What it does for users

About two of every three releases change no database migration (39 of 61 in 13–26 Oct). For those, the new version starts beside the old one, is checked, and takes over in one step. Nobody sees the "completing a reviewed release" page, uploads in progress finish, and Meta, WhatsApp and website leads are answered throughout. Releases with a migration keep S2's short hold until phase M.

## Facts this plan rests on (checked 27–28 Oct on the workbench and on ac)

1. **The release engine on ac has not updated itself since 12 Oct** (installed `bc49a3ddd`). It updates only from its timer tick, and the tick returns early while staging is paused, which ac-ship keeps between ships. So S3 must not depend on engine changes. The application installer, which every release brings in its own archive, can do all of it:
   - it already knows both migration heads (`previous_release/release-images.env` and the bundle), as `rollback_application_only` uses today, so it can choose Path A itself;
   - fixing the engine's self-update is its own task (see Follow-ups).
2. **Green can join blue's networks without moving PostgreSQL.** The environment networks have fixed names (`ac-application-<env>_app`, `_data`, `_egress`, `_telemetry`, and `ac_edge`). A per-release Compose project declares them `external: true` with those names. The design's one-time "fixed-network" hold release is not needed.
3. **The edge reload exists after S1**, and route files are already copied per release into `edge-route-releases/<rid>/`.
4. **Upstreams are named by alias in the route files** (`ac-production-api:8000`, `ac-production-learner:3000`, …, from `AC_EDGE_*_ALIAS`). Blue and green must not share an alias: Docker DNS would spread requests across both, and the switch would not be one step.
5. **The Sales X-Ray web container is deployed by the engine's `deploy_web`** (separate Compose project), recreated about 60 s after each core release: about 1.3 s of 502 on `salesxray.*` pages. Blue/green for it needs the engine, so S3 covers it with a retrying upstream instead (step 6).
6. **Workers must not overlap** (design §4.4): the core worker dead-letters outbox event types it does not know, and nothing routes jobs by version.

## Steps

1. **Path choice in the installer.** `AC_RELEASE_PATH=rolling` when all hold:
   - the previous release exists and its `AC_MIGRATION_HEAD` equals the bundle's;
   - PostgreSQL's service definition is unchanged (S2's content-addressed init plus image and command), compared by `docker compose config --hash postgres` for both releases;
   - the hosted Sales X-Ray native image is unchanged (`--native` releases stay on the hold path).
   Anything else takes today's hold path. The choice and its reason go into the prepared and committed deployment records.
2. **Green project.** `compose -p ac-app-<env>-<rid12>` with a generated override (from the release, not host state):
   - only `api`, `learner-web`, `admin-web`, `coach-web`;
   - every network `external` with the environment's fixed names;
   - edge aliases `ac-<env>-api-<rid12>` and so on; the internal API alias (`AC_INTERNAL_API_HOST`) stays shared, since web-to-API calls are expand-compatible;
   - the intake spool stays in the environment project (its folder is shared and replays are locked).
   `up --detach --wait`, then probe each green service on `ac_edge` by its new alias: `/health/ready`, learner `/`, admin `/login`, coach `/login`.
3. **Rendered route.** The release's `edge-routes/<env>.caddy` is rendered with the green aliases into the projection directory (`edge-route-releases/<rid>/<env>.caddy`), root-owned 0444. The projection check compares it with a fresh render of the release source instead of the source bytes. `caddy validate` as today.
4. **Order of the switch** (design §4.2):
   1. SIGTERM the old Sales X-Ray worker; it stops claiming and finishes its job in the background (no wait here). Stop `ac-call-data` exec runners first.
   2. Stop the old core worker (30 s).
   3. Selector symlink to the rendered route, `caddy reload`, `check_route` on every host expecting `X-AC-Release` = the new commit (the API adds this header in this step).
   4. Start the new core worker.
   5. `docker stop --time 900` the blue API (in-flight uploads finish), then blue web (30 s). Keep blue's containers stopped, not removed, until the next release.
   6. When the old Sales X-Ray worker has exited 0, start the new one (jobs wait in `jobs`, leased with SKIP LOCKED).
   7. Call the intake spool replay (idempotent; it finds nothing).
5. **Rollback by reload.** Start blue, wait healthy, symlink back, `caddy reload`, drain green; workers swap back in the same order. The schema is unchanged by definition of Path A. A new `AC_CORE_ROLLBACK_ONLY` branch uses this when the previous release is a stopped blue.
6. **Sales X-Ray web without 502s.** Add `lb_try_duration 15s` and `lb_try_interval 250ms` to the `salesxray.*` page upstreams (and the API upstreams) in both route files. While `deploy_web` recreates the container, Caddy retries the dial instead of answering 502. Requests wait about 1–2 s.
7. **Open tabs.** Keep blue web stopped, not removed, for 24 h. Route `/_next/static/*` to green first and, on 404, to blue started on demand (design §7.1), or ship the simpler first cut: keep blue web running for 10 minutes after the switch with `/_next/static/*` falling back to it.
8. **Evidence.** The deployment record gains `AC_RELEASE_PATH`, the reason, green project name and the probe summary when a probe ran.

## Tests

- Installer functions with Docker stubs (as `tests/infra/test_edge_graceful_reload.py` does): path choice for equal and different heads, a changed PostgreSQL hash and a native release; the order of worker stops, reload and drain; rollback by reload; a failed green health check that leaves blue serving and no route change.
- Rendering: deterministic output, only alias substitutions, projection verification against a re-render, `caddy validate` with the pinned image.
- Real Compose in CI: a green project on external networks reaches a fixture service in the blue project by alias; blue's container id is unchanged by green's start.
- `release-probe.py` through 10 staging Path-A releases and 3 rollbacks: 0 refused, 0 5xx, one `X-AC-Release` flip per target, a 120 s upload started before the switch completes.
- Job integrity on staging with fixture providers: K synthetic jobs across a switch each reach one terminal state with `attempt_count = 1`.

## Proof before production

1. Dev: the drill (`scripts/ops/edge-reload-drill.sh`) extended with a blue and a green upstream.
2. Staging: 10 Path-A releases under the probe, 3 rollbacks.
3. Production: the first 3 Path-A releases under the probe, at a quiet time, with the hold path one flag away (`AC_RELEASE_PATH=hold` forced in the profile).

## Risks

| Risk | Mitigation |
|---|---|
| Memory during the overlap (about 470 MB for a second api/web set; swap is nearly full) | Stop blue web first; blue API drains with no new requests; the probe records swap |
| A route render bug sends a host nowhere | Render is checked against a re-render, validated by Caddy, and checked by `check_route` per host before blue stops; rollback is one reload |
| Old and new code overlap on the same database for up to 15 minutes (blue API drain) | Path A has no schema change; new values behind switches (design §3.3) |
| The Sales X-Ray worker drain delays new analyses by up to 16 minutes | Only when a long job is in flight (measured drain: 1 s); removed in phase M |

## Follow-ups outside S3

- **Engine self-update while staging is paused** (devenv): `ac-ship` calls `ac-release` to update the engine from the merged main commit before its staging deploy, or `deploy` runs `update_engine` first. Until then, workbench changes to `infra/release/` (including the backup-scope drift check) are not running on ac.
- **Caddy request metrics over the admin socket** (design §8.7), so each release record stores 5xx counts during the switch.
