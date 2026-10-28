# Zero-downtime releases S1 and S2: evidence (28 Oct 2026)

Design: `docs/ops/ZERO-DOWNTIME-RELEASES.md`. Next step: `docs/ops/ZERO-DOWNTIME-S3-PLAN.md`.

## What changed

| Step | Files | Effect |
|---|---|---|
| S1 | `infra/application/edge/{Caddyfile,compose.edge.yaml}`, `infra/vps-foundation/compose/foundation/{Caddyfile,compose.yaml}`, `install-application-release.sh` (`prepare_edge_caddyfile`, `edge_compose`, `reconcile_edge_router`), `verify-release-archive.py` | Route switches are `caddy reload` on a private admin socket; the router is recreated only when its Caddyfile content changes |
| S2 | `install-application-release.sh` (`capture_release_environment`, `with_release_environment`, `postgres_init_copy`, `compose_for`), `infra/application/compose.yaml` | One managed-secret fetch per install instead of two per Compose call; PostgreSQL keeps one bootstrap mount, so it is not recreated |
| Tools | `scripts/ops/release-probe.py`, `scripts/ops/edge-reload-drill.sh` | 200 ms probe of both environments; scratch drill of restart vs reload |

## Baseline (before S1/S2)

- **Infisical:** the last core installs (v1.0, 044e2a4c3, 27 Oct) logged 72 "Injecting 34 Infisical secrets" lines each (`/var/log/ac-release/20261027T024523Z-staging-core-*.log`, `20261027T025638Z-production-core-*.log`): 36 `with_release_secrets` calls, each an `ac-infisical-run` fetch plus an inner `infisical run`.
- **PostgreSQL:** both environments' servers mount `releases/<release>/postgres/init` (checked with `docker inspect`, 27 Oct 18:5xZ), so each release's `up postgres` recreates them.

**v1.1.0 under the probe** (27 Oct, before S1/S2; `release-probe.py` every 200 ms per target through `127.0.0.1:8080`, fresh and keep-alive connections; production and staging API `/health/ready` and Sales X-Ray `/robots.txt`):

| Deploy | Hold (503) on its own hosts | Refused or reset on both environments | Sales X-Ray web 502 |
|---|---|---|---|
| Staging core, 20:59Z | 168.6 s (21:00:26–21:03:15Z) | 0.4–0.6 s at 21:00:25Z and 21:03:15Z (each edge recreate) | 1.2 s at 21:04:42Z |
| Production core, 21:10Z | 174.2 s (21:11:50–21:14:44Z) | 0.2–0.6 s at 21:11:49Z and 21:14:44Z | 1.2 s at 21:15:46Z |

So a ship blipped production four times (two edge recreates per environment) besides its own 174 s hold.

## Dev proof (S1)

`sudo scripts/ops/edge-reload-drill.sh /var/tmp/zdr-drill-s1b 5 20` on ac, 27 Oct 23:02Z: a scratch router from the running router's image (`sha256:5f5c8640…`) with this release's Caddyfile and the router's security settings, a scratch upstream, two hosts probed every 200 ms on fresh and keep-alive connections, five switches per phase with a 20 s request in flight.

| Phase | Responses | Refused | Failure windows | 5xx | 20 s request | Router restarts |
|---|---|---|---|---|---|---|
| Restart (stand-in for today's recreate) | 672 | 44 | 20 (12.0 s, then 0.4 s per restart) | 0 | cut at 12.1 s, 0 bytes | 5 |
| `caddy reload` on the admin socket | 424 | **0** | **0** | **0** | **200, all 20 bytes, 19.0 s** | **0** (start time unchanged) |

In the reload phase, 7 idle keep-alive connections were closed by the retiring config and retried on a new connection (`idle-closed`), as browsers and Go clients such as cloudflared do; p99 latency stayed under 51 ms. The first restart waited 10 s on the in-flight request before Docker killed it, which is what a recreate does to a long upload today.

The first drill run (`/var/tmp/zdr-drill-s1`) gave the same numbers; there the probe still counted those idle-connection retries as resets, which is why it now retries them like a browser.

## Commits and CI

- **S1:** `f34353c43` on the workbench (includes the orchestrator's intake-spool setgid fix). wb-ci run 40598491355 green on all families (lint, control-plane, 17 Python shards including the real-Caddy reload test); run 40600047678 green for the final probe.
- **S2:** `e915d1594`. wb-ci run 40607178067 green (lint, control-plane, all Python shards). A first S2 layout (run 40605360428, red) changed `compose_for`'s helpers and broke about a dozen test harnesses that run `compose_for` with their own stubs; the committed layout caches inside `with_release_secrets` and exports `AC_POSTGRES_INIT_ROOT`, leaving `compose_for` unchanged.
- The Compose mount proof also ran as root on ac's Docker Compose 5.5: with the stable mount the stand-in server kept its container across two release directories; with the release-relative mount it was recreated.

## Expected on the next release

| | Before (v1.1.0) | After S1 + S2 |
|---|---|---|
| Infisical "Injecting" lines per core install | 72 | 2 (one capture), none inside the hold |
| PostgreSQL recreated | every release | once more (mount moves to `postgres-init/<sha256>`), then never by an app release |
| Edge router recreated | twice per environment deploy | once on the first deploy (onto the release Caddyfile), then never |
| Refused connections on the other environment | 0.4–0.6 s twice per deploy | 0 after the first deploy |
| Hold | 168–174 s | target 45–60 s |

## First release with S1 and S2: v1.2.0 (main 4a6564b, 28 Oct)

The watcher on ac (`/var/tmp/zdr-s1s2-proof/`) recorded both core deploys: the release probe on both environments every 200 ms, container start times and mounts before and after, and Infisical fetches in the release log.

| | Staging core, 07:25Z | Production core, 07:34Z | v1.1.0 (before) |
|---|---|---|---|
| Hold (503) | **80.7 s** (07:29:47–07:31:08Z) | **62.6 s** (07:35:31–07:36:34Z) | 168.6 s / 174.2 s |
| Refused or reset, either environment | one 0.2 s window at 07:29:47Z: the one-time edge move | **none** | 0.4–0.6 s, twice per deploy |
| Edge router | recreated once, onto `edge-config/92a96c82…/Caddyfile`; socket `s-w------- 1000` | **not recreated** (start time unchanged); both switches reloaded | recreated twice per deploy |
| PostgreSQL | recreated once, onto `postgres-init/b108da99…` | recreated once, onto the same copy | recreated every deploy |
| Infisical "Injecting" lines | **2** | **2** | 72 |
| Sales X-Ray web 502 (separate web deploy) | 1.4 s at 07:33:09Z | 1.2 s at 07:37:16Z | 1.2 s |

- During the production deploy, staging served every request: the first production deploy that did not blip staging.
- One or two idle keep-alive connections per switch were closed by the retiring config and retried (`idle-closed`); no request failed.
- Production's 5-minute logical backups kept succeeding after the release (07:40:59Z, 07:45:43Z): `docker compose exec` works with the `./postgres/init` default. Staging's have failed since 26 Oct on their 64 MiB size bound (the hold's staging dump is 119 MB); that is unchanged by this work.

**Where the holds went** (deployment receipts, dump mtimes, container start times):

| Step | Staging | Production |
|---|---|---|
| Stop api and core worker, drain the Sales X-Ray worker | ≈10 s | ≈10 s |
| Fenced `pg_dump` and receipt | ≈26 s (119 MB) | ≈5 s (17.5 MB) |
| PostgreSQL recreate and first health check (one-time) | ≈7 s | ≈7 s |
| Fence, migrator grant, migrate, product notes | ≈15 s | ≈21 s |
| Start api and web, wait healthy (admin and coach wait for the api), switch | ≈23 s | ≈20 s |
| **Total** | **80.7 s** | **62.6 s** |

**Next release.**
- Production should land near 56 s: same steps, without the one-time PostgreSQL recreate.
- Staging should land near 74 s, dominated by its 119 MB dump.
- Two cheap reductions:
  1. `start_interval: 1s` on the PostgreSQL, api and web health checks. Docker's default 5 s start interval is why the api takes about 11 s to count as healthy, and admin and coach start only after it; this saves about 10 s per hold.
  2. Staging's database is 7 times production's. Finding and clearing what grew it is an owner-approved staging data change, and it would also bring back staging's 5-minute backups.
- S3 removes the hold altogether for releases without a migration.
