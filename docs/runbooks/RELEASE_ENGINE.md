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
| Sales Xray native | pinned by `install-sales-xray-native.py` | not handled; changes rarely and is installed separately |

## One-time setup (owner)

1. Create a fine-grained GitHub token: resource owner `authorityclosers`, only
   `authority-closers-platform`, **Actions: read-only**. Save it on the server:
   `sudo install -d -m 700 /etc/ac-release && sudo bash -c 'read -rsp "Token: " T && umask 077 && printf %s "$T" > /etc/ac-release/github-actions-read.token'`
2. Install from a clean checkout of the reviewed commit:
   `sudo infra/release/install-release-engine.sh`.
   A first install leaves staging auto-deploy **paused**.
3. First supervised deploy: `sudo ac-release deploy staging --dry-run`, then
   `sudo ac-release deploy staging`, then `sudo ac-release resume staging`.

## Commands

| Command | Does |
|---|---|
| `ac-release status` | What runs where, pause state, failures |
| `ac-release deploy staging [SHA] [--component core\|web\|all] [--dry-run]` | Deploy a commit on `main` (default: latest) |
| `ac-release pause staging` / `resume staging` | Stop or restart automatic deploys; `resume` also clears failure marks |
| `ac-release rollback staging --component web` | Restore the previous Sales Xray web image |
| `ac-release history -n 20` | Recent deploy records (`/var/lib/ac-release/history.jsonl`) |

Logs for each deploy are in `/var/log/ac-release/`.

## Safety rules

- Only `push` builds of `main` from this repository count. Artifact digests are
  checked against GitHub, and bundle checksums against `SHA256SUMS`. The GitHub
  token is sent only to `api.github.com`, never to the storage redirect.
- A failed **core** deploy pauses staging and is not retried automatically.
  The installer takes a database dump before migrating. If the install fails,
  it restores that dump, the release link and the edge route by itself. The
  engine then waits for a person to decide.
- **Foundation first for new migrations.** `ac-postgres-backup` checks the
  migration head of every environment before it backs up any of them. A core
  release whose `AC_MIGRATION_HEAD` the installed foundation backup tool does
  not know would stop backups for staging **and production**. The engine
  refuses such a deploy until the foundation release from `main` is installed
  (`infra/vps-foundation/scripts/install-foundation-release.sh`).
- A failed **web** deploy automatically restores the previous web image.
- Production deploys are refused unless `/etc/ac-release/production.enabled`
  exists **and** the same commit already passed staging. That file is created
  only after the off-host backup restore check passes.
- Admin → Releases (T5) will call these same commands.
