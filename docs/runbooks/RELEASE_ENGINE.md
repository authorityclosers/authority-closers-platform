# Release engine (staging auto-deploy)

`infra/release/ac_release.py` runs on the VPS as root from a systemd timer every
two minutes. It keeps staging on the latest `main` commit that passed CI. It
never builds anything. It downloads the exact bundles CI produced, keeps an
immutable copy in `/srv/authority-closers/release-store/<sha>/`, and runs the
same source-owned installers the laptop script used to run over SSH.

| Piece | Source | Installed by the engine with |
|---|---|---|
| Core app (API, worker, learner, admin, coach) | `ac-application-<sha>` from `application.yml` | `infra/application/scripts/install-application-release.sh` |
| Sales Xray web | `ac-sales-xray-web-<sha>` from `sales-xray-web-image.yml` (built only when web inputs change) | `verify-artifact.py`, `docker load`, compose `up --wait` |
| Sales Xray activation | the running release's `/etc/authority-closers/sales-xray/<env>/activation-<sha>.json` | carried forward with `prepare-sales-xray-native-activation.py` (see [Sales Xray activation](#sales-xray-activation)) |
| Sales Xray native | `ac-sales-xray-native-<sha>` from `sales-xray-native-image.yml` (built only when native inputs change) | stored for good in `release-store/native/<sha>/`; a new native image is still installed separately with `install-sales-xray-native.py` |

## One-time setup (owner)

1. Create a fine-grained GitHub token: resource owner `authorityclosers`, only
   `authority-closers-platform`, **Actions: read-only**. Save it on the server:
   `sudo install -d -m 700 /etc/ac-release && sudo bash -c 'read -rsp "Token: " T && umask 077 && printf %s "$T" > /etc/ac-release/github-actions-read.token'`
2. Install from a clean checkout of the reviewed commit:
   `sudo infra/release/install-release-engine.sh`.
   A first install leaves staging auto-deploy **paused**.
3. First supervised deploy: `sudo ac-release deploy staging --dry-run`, then
   `sudo ac-release deploy staging`, then `sudo ac-release resume staging`.

After this one-time install, the engine **updates itself**. When a tick finds
that `main` changed `infra/release/`, it waits for that commit's full
validation to pass, then reinstalls itself from that exact commit (a clean
checkout from its mirror, then `install-release-engine.sh`) and ends the
tick. The next tick runs the new engine. A failed self-install is recorded in
`history` and not retried for the same commit; deploys continue on the engine
already installed. `ac-release status` shows the installed engine commit.

## Commands

| Command | Does |
|---|---|
| `ac-release status` | What runs where, pause state, failures |
| `ac-release deploy staging [SHA] [--component core\|web\|all] [--dry-run]` | Deploy a commit on `main` (default: latest) |
| `ac-release pause staging` / `resume staging` | Stop or restart automatic deploys; `resume` also clears failure marks |
| `ac-release rollback staging --component web` | Restore the previous Sales Xray web image |
| `ac-release history -n 20` | Recent deploy records (`/var/lib/ac-release/history.jsonl`) |
| `ac-release prune-artifacts [--apply] [--keep-recent N] [--no-images] [--json]` | Report, or with `--apply` remove, installer artifacts and core images nothing needs (see [Disk space](#disk-space)) |
| `ac-release store-native SHA [--from ZIP]` | Keep a Sales Xray native build for good. Downloads it while GitHub still has it; `--from` adopts a saved copy only if it matches the digest and size GitHub recorded |

Logs for each deploy are in `/var/log/ac-release/`.

## Safety rules

- Only `push` builds of `main` from this repository count. Artifact digests are
  checked against GitHub, and bundle checksums against `SHA256SUMS`. The GitHub
  token is sent only to `api.github.com`, never to the storage redirect.
- A failed **core** deploy pauses staging and is not retried automatically.
  The installer takes a database dump before migrating. If the install fails,
  it restores that dump, the release link and the edge route by itself. The
  engine then waits for a person to decide.
- **Automatic backup support for new migrations.** Before a core deploy, the
  engine checks the backup tool installed under `/usr/local/libexec`. If the
  tool does not recognise the bundle's migration head, the engine installs
  only the backup-scoped foundation from that build's exact commit, after
  checking that the candidate also supports every running environment's head.
  It records `foundation-backup-install` and rechecks the installed tool before
  continuing. Failure still pauses staging; dry runs only report the planned
  step, and application-only rollbacks never install the foundation.
- A failed **web** deploy automatically restores the previous web image.
- Production deploys are refused unless `/etc/ac-release/production.enabled`
  exists **and** the same commit already passed staging. That file is created
  only after the off-host backup restore check passes.
- Admin → Releases production controls are proposed in [ADR 0034](../adr/0034-admin-release-control-through-engine-inbox.md); the inbox consumer and Admin release routes are not implemented yet.

## Admin production controls (ADR 0034)

**Status: proposed; implementation pending.** The installed engine does not
currently provide the Admin request routes, inbox consumer, `promote` command,
or production rollback command described here. Do not use the planned commands
below until their implementation tasks have landed and the engine is updated.

Production Admin submits intent to the engine through the request inbox. The
production API can create request files but cannot list the inbox. Once the
engine moves a request into the root-only `processed/` directory, the API can
no longer reach it. The root engine consumes each request under its lock and
writes `status.json` plus a per-request result into the outbox using atomic
writes. Staging and production APIs mount the outbox read-only. A systemd path
unit triggers the consumer, with the two-minute engine tick as backup.

Requests use a strict schema and reject unknown keys. The engine moves each
inbox request into the root-only `processed/` directory before handling it, so
a request runs at most once. It reads the moved file once: the opened file must
be regular, not a symlink, no larger than 4 KB, and owned by uid `10001`. The
engine validates only the bytes read from that open file; it never re-reads the
inbox path. It also refuses requests older than 15 minutes, concurrent
requests, and stale expected production commit/version values.

Before writing a request, the production API requires the owner-only
`platform_release_manage` capability, a safe origin, and typed confirmation of
the resulting version; it appends an `audit_events` entry and includes its
`audit_event_id` in the request. It then writes the request and returns `202`
with its id. Status is read from the outbox. Staging Admin cannot submit
production actions.

The engine enforces these production guards on every request:

- Production is enabled only when `/etc/ac-release/production.enabled` exists;
  the off-host backup restore check must have passed.
- The core commit and paired web build must be on `main` and pass staging.
- Compare-and-swap must match the current production commit and version, and
  the engine lock permits one action at a time.
- Rollback can target only the immediately previous release with the same
  migration head as production. Database rollback is forbidden.
- Foundation support for new migrations must be installed first, and the
  Sales Xray approval must have at least one day remaining.
- The engine accepts requests only from the production inbox, which no other
  API mounts, and each request must carry its `audit_event_id`.
- The engine derives the next version from tags and release records.

The API requires the owner to type the displayed resulting version to
confirm. The agreed baseline is current production `v0.2.0`; with no existing
`vX.Y.Z` tags, the first minor promote is `v0.3.0` (D1). Production actions
come only from production Admin; staging Admin is read-only, and CLI is the
fallback (D3). The authorization is a new owner-only `platform_release_manage`
capability, not `platform_access_manage` (D4; see [ADR 0031](../adr/0031-explicit-platform-and-studio-capabilities.md)).

After the engine CLI work is implemented, the planned fallback commands are
`sudo ac-release promote --bump minor` and
`sudo ac-release rollback production`. Until then, use only the currently
implemented commands in this runbook.

## Sales Xray activation

A core release that runs hosted Sales Xray needs its own activation
descriptor. The installer refuses a release without one. For each core deploy
(real or dry run), the engine does the following:

1. Does nothing if the target already has an activation, or if the running
   release has none (hosted Sales Xray is not active there).
2. Refuses if the running approval, or its acquisition policy, lapses within a
   day. `ac-release status` shows each environment's approval end date.
3. Finds the loaded native artifact behind the running native image and builds
   the native reuse proof from `release-store/native/<sha>/` and its git mirror.
4. Runs the repository tool `prepare-sales-xray-native-activation.py` with the
   approval **carried forward unchanged** into
   `application/operator-inputs/<env>/release-<sha>-<time>/`. It then installs
   the descriptor and its digest (mode 0444). A dry run prepares inside its
   temporary stage and publishes nothing.

After the installer, the core check also waits for `sales-xray-worker` to run on
the release's API image and to stay up for 30 seconds without restarting.

The engine never creates, renews or widens an approval. A new approval (new
limits, testers or providers) is still prepared by a person against a new
release. The engine also pauses staging, with a message, in two cases:

- the release changes the native image inputs (install the new native build
  first);
- the running native build is not stored and GitHub has already dropped it
  (adopt the saved copy with `store-native --from`).

## Disk space

Two stores keep core release bundles on the server:

| Store | Holds | Cleaned by |
|---|---|---|
| `/srv/authority-closers/release-store/<sha>/` | The engine's downloads | The engine, after each successful deploy: what runs plus the last 10 successful deploys |
| `/srv/authority-closers/application/artifacts/<sha>/` | The installer's immutable copy of every core bundle it installed (about 390 MB each), plus the four images it loaded into Docker | `ac-release prune-artifacts`, run by the owner |

GitHub keeps each bundle for one day, so these copies are the only local way
to reinstall an older release. Once a copy is removed, reinstalling that
release needs its bundle from the release store, or a new package from the
*Application release package recovery* workflow.

### What `prune-artifacts` keeps

A core artifact stays if any of these is true. The report prints the reasons.

1. `current-staging` or `current-production` points at it.
2. An environment's records in `application/deployments/<env>/` name it at or
   after the last `COMMITTED` record. That covers the `AC_PREVIOUS_RELEASE`
   rollback target, any later unfinished attempt, and any
   `FORWARD_RECOVERY_REQUIRED` release, whose recovery is to reapply that exact
   release.
3. A file under `application/deployments/` or `application/operator-inputs/`
   names `artifacts/<sha>`. Files over 1 MB are not scanned.
4. It is one of the newest N (`--keep-recent`, default 10), by the time it was
   written.

A core image (`authority-closers-api`, `-learner-web`, `-admin-web`,
`-coach-web`) stays if any container uses it, or if it belongs to a kept
release (by its tag or that release's `release-images.env`).

It never touches:

- `sales-xray-native-<sha>` directories, because the native systemd units run
  their helper from there;
- `sales-xray-web-<sha>` bundles and the installer's `.stage-*` directories;
- Sales Xray web and native images, foundation and third-party images, and
  untagged images.

The report lists their size. The native units start their image only for a
job, so Docker counts it as unused. **Do not run `docker image prune -a`**: it
would delete the live native image.

The command stops without removing anything when a current link or deployment
record is not what the installer writes, or when a file it must scan cannot be
read.

### Running it

```bash
sudo ac-release prune-artifacts
sudo ac-release prune-artifacts --apply
```

The first command is the dry run: every entry marked keep or remove, with its
reasons and size. The second removes what the dry run marked remove. Before the
engine is installed, run the same commands from a clean checkout of the
reviewed commit as `sudo python3 infra/release/ac_release.py prune-artifacts`.

`--apply` runs only as root. It refuses while an engine run or an installer
holds its lock (`application/.deployment.lock`), and it decides again after
taking both locks. Each artifact is renamed to `.prune-<sha>.<random>` before it
is deleted, so an install never sees a half-deleted bundle. The next run
finishes any interrupted removal. Images are untagged with `docker image rm`,
never with `--force`. The outcome is appended to `history.jsonl`.

Dry run on 2026-09-28:

- **Core artifacts:** 109 (31.4 GB). Keep 14 (5.4 GB), remove 95 (26.0 GB).
- **Core images:** all 20 belong to the five kept releases that have images
  loaded, so none would be removed.
- **Unmanaged:** 60 Sales Xray entries (8.0 GB) and 19 Docker images were left
  alone.
