# Development backend units

`ac-dev-api.service` listens on `127.0.0.1:8100` as uid/gid 10001.
`ac-dev-sales-xray-worker.service` runs the dedicated worker with a sterile
allowlisted environment, a pinned manifest and a 16-minute graceful stop.
`ac-dev-outbox-worker.service` runs `python -m ac_platform.worker`, the same
module as the staging compose `worker` service, so dev sends its own sign-in and
verification email codes. All three require systemd system services; this
directory installs nothing.

The Root specialist installs the reviewed units from
`/srv/authority-closers/application/current-staging/development/` after AUT-159.
Keep the admin-web alias `api.development.ac.internal.invalid:8000` working at
cutover (AUT-285); these units do not change networking or Caddy.

Expected host paths:

- `/srv/authority-closers/development/backend`: root-owned checkout and `.venv`
  of the deployed staging commit, no agent/service write access or symlink into
  a hidden home/cache. Its Python interpreter must resolve outside `/home` and
  `/root`. `.ac-release-id` contains that commit; the worker sees it read-only
  at `/app/.ac-release-id`.
- `/srv/authority-closers/sales-xray/development`: uid/gid 10001, mode 0700;
  `storage` and `scratch` are initialized by the storage adapter. Same canonical
  paths inside both sandboxes and the native helper; only this tree is rebound rw.
- `/run/ac-sales-xray/development`: prepared dev helper socket directory,
  rebound read-only; the helper accepts uid/gid 10001.
- `/usr/local/bin/infisical`: reviewed root-owned executable, bound read-only at
  `/opt/infisical` in the worker; no CLI install or provider activation here.
- `/usr/local/bin/uv`: root-owned executable, version 0.12.19, used by the
  backend refresh from its fixed system `PATH`.

All source files below live under root-owned, mode 0700
`/etc/authority-closers/development/`. No agent can traverse it. Ordinary source
files are root:root 0600, regular files with one link and no symlink ancestors.
systemd reads them as root. `LoadCredential` delivers private, read-only files
owned by uid 10001; mode 0400 meets `read_private_file`'s confidential checks.
In the table, `C` means `/run/credentials/<unit-name>` (systemd `%d`).

| Source relative to development/ | Unit / delivery | In-process path |
| --- | --- | --- |
| `api.env` | API / EnvironmentFile | process environment only |
| `outbox.env` | outbox worker / EnvironmentFile | process environment only |
| `migrator.env` | refresh only (root) | none |
| `challenge-secret` | API / LoadCredential | `C/challenge-secret` |
| `qa-password` | API / LoadCredential | `C/qa-password` |
| `approval.json` | both / LoadCredential | each unit's `C/approval.json` |
| `database-url` | worker / LoadCredential | `C/database-url` |
| `service.json` | worker / LoadCredential | `C/service.json` |
| `service.operator-template.json` | root-only input for the refresh renderer | none |
| `identities/elevenlabs/token` | worker / read-only directory bind | `/run/ac-sales-xray/identities/elevenlabs/token` |
| `identities/gemini/token` | worker / read-only directory bind | `/run/ac-sales-xray/identities/gemini/token` |

Each provider directory is root:10001 0550 with exactly one uid-10001 0400 token
file, no symlinks or hard links. The root-only ancestor prevents agent access;
the bind allows the identity child to read its single provider file. The API
receives neither provider directory nor the worker DB credential. The QA file
is delivered for the specified QA contract; current API code has no QA-password
file setting, so this unit does not invent a consumer or enable a QA login.

`api.env` supplies development settings, the dev DB URL and approval digest.
It must omit `AC_SALES_XRAY_APPROVAL_PATH`,
`AC_SALES_XRAY_CHALLENGE_SECRET_FILE`, `AC_DATABASE_MIGRATOR_URL`, and
`AC_RELEASE_ID`; the units set the first two, and the API drop-in sets the
release id. Environment-file values would override those settings. The
root-only `migrator.env` contains `AC_ENVIRONMENT=development` and
`AC_DATABASE_MIGRATOR_URL`; it is mode 0600 and is loaded by no service unit.

`outbox.env` (root:root 0600) holds only the settings `ac_platform.worker`
reads:

- `AC_ENVIRONMENT=development`
- `AC_DATABASE_URL`: the same dev runtime DB URL as `api.env`
- `AC_EMAIL_CHALLENGE_SECRET`: equal to the API's value; the worker decrypts the
  codes the API encrypted
- `AC_PUBLIC_APP_URL` and `AC_ADMIN_APP_URL`: the dev app URLs used in email links
- `AC_EMAIL_PROVIDER=resend`, `AC_RESEND_API_KEY`, `AC_RESEND_FROM`: dev-only
  values from Infisical dev, never staging's
- `AC_EXTERNAL_SIDE_EFFECTS_HOLD=false`: this unit only; `api.env` keeps `true`

It must omit `AC_DATABASE_MIGRATOR_URL` and every `AC_SALES_XRAY_*` setting. The
outbox unit gets no Sales Xray storage bind, native socket, approval, challenge,
QA credential or provider identity. The worker's `prepare()` sends nothing until
the dev database recovery gate is `ready`; an operations admin sets it with the
existing `POST /v1/admin/recovery/reconcile` (empty release set, a reason and an
`Idempotency-Key`) on the dev API.
The worker manifest
uses literal `C` expansions for its own unit, `/opt/infisical`, the provider
paths above and the canonical dev storage/socket paths. It must use a dev-only
DB endpoint compatible with `load_database_url`; localhost aliases are rejected.

AUT-159 writes root-owned
`/etc/systemd/system/ac-dev-sales-xray-worker.service.d/manifest.conf`:
`[Service]` followed by `Environment=AC_DEV_WORKER_MANIFEST_SHA256=<64 hex digest>`.
systemd expands this into argv before `env -i` strips the service environment;
the digest does not enter the worker environment. Missing/wrong digests fail closed.
The refresh must restart after replacing credentials or manifest; credentials
are snapshots. Tests verify parsing and sandbox contracts without starting units.

## Backend refresh

`ac-dev-sales-xray-refresh.timer` runs every ten minutes. Its root oneshot
service runs the script from
`/srv/authority-closers/application/current-staging/scripts/refresh-dev-sales-xray-backend.py`
and checks out the selected staging core commit from the local
`/var/lib/ac-release/mirror.git`. Git checkout does not use GitHub credentials.
A valid `staging_pick.core` with a stored
core build takes precedence over `current-staging`; otherwise the symlink is the
target.

Before it changes the backend, the script checks for `uv` on its fixed system
`PATH`, then compares native inputs against the development native unit
descriptor. It requires `AC_ENVIRONMENT=development` and
`AC_DATABASE_MIGRATOR_URL` in the root-only
`/etc/authority-closers/development/migrator.env`. It refuses if the API
environment file contains either the migrator URL or `AC_RELEASE_ID`.
It syncs the frozen production dependencies, runs Alembic as uid/gid 10001,
renders `service.json` from the root-owned development template, writes the
release marker and API/worker drop-ins, restarts the API, Sales Xray worker and
outbox worker units in that order, then
polls `/health/ready` for up to 60 seconds. The refresh passes only when the API
reports the target release and its database is ready. Failures during this
refresh restore the previous checkout, marker, manifest and drop-ins before
restarting all three units.

After backend health passes, the service runs the acdev-owned studio sync and
merges `origin/main` under `/run/ac-studio-sync/ac-studio-sync.lock`. A studio
merge failure raises an alert but leaves the refreshed backend in place. If the
target contains `scripts/ops/ac_smoke.py`, the script runs the development smoke
against that core and the merged UI checkout; otherwise it reports `skipped`.
Smoke failures are reported without rolling back the backend.
