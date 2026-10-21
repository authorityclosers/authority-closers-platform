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

Host identity: systemd cannot start `User=10001` without an NSS entry (status
217/USER). `scripts/install-dev-runtime-identity.py` (dry-run by default,
`--apply`, `--rollback --apply`) adds the locked, home-less system account
`ac-sales-xray-runtime` (uid 10001) whose only group is the existing
`ac-sales-xray-native` (gid 10001) primary group. It adds no supplementary group
(never `acops`), leaves the native group's member list empty, and its rollback
removes only that account, never the group or any file. The refresh refuses with
`runtime_identity_missing`/`runtime_identity_invalid` before any change unless
exactly this identity exists.

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
owned by root:root, mode 0440 with an ACL that grants read to uid 10001 only (the
group bits are the ACL mask); the confidential readers verify that exact ACL.
In the table, `C` means `/run/credentials/<unit-name>` (systemd `%d`).

| Source relative to development/  | Unit / delivery                          | In-process path                                  |
| -------------------------------- | ---------------------------------------- | ------------------------------------------------ |
| `api.env`                        | API / EnvironmentFile                    | process environment only                         |
| `outbox.env`                     | outbox worker / EnvironmentFile          | process environment only                         |
| `migrator.env`                   | refresh only (root)                      | none                                             |
| `challenge-secret`               | API / LoadCredential                     | `C/challenge-secret`                             |
| `qa-password`                    | API / LoadCredential                     | `C/qa-password`                                  |
| `approval.json`                  | both / LoadCredential                    | each unit's `C/approval.json`                    |
| `database-url`                   | worker / LoadCredential                  | `C/database-url`                                 |
| `service.json`                   | worker / LoadCredential                  | `C/service.json`                                 |
| `service.operator-template.json` | root-only input for the refresh renderer | none                                             |
| `identities/elevenlabs/token`    | worker / read-only directory bind        | `/run/ac-sales-xray/identities/elevenlabs/token` |
| `identities/gemini/token`        | worker / read-only directory bind        | `/run/ac-sales-xray/identities/gemini/token`     |

Each provider directory is root:10001 0550 with exactly one uid-10001 0400 token
file, no symlinks or hard links. The root-only ancestor prevents agent access;
the bind allows the identity child to read its single provider file. The API
receives neither provider directory nor the worker DB credential. The QA file
is delivered for the specified QA contract; current API code has no QA-password
file setting, so this unit does not invent a consumer or enable a QA login.

### OpenAI worker access (21 October 2026)

[AUT-2179](/AUT/issues/AUT-2179) authorizes the dev workers, including
`ac-one-pass@development-live`, to read `OPENAI_API_KEY` from project
`b421c44e-4599-4394-8df6-758ed8aedfed`, environment `dev`, path
`/sales-xray-test/openai`. Provisioning is pending on
[AUT-2180](/AUT/issues/AUT-2180); this is not installed worker access.

The existing Gemini service token reads `dev:/sales-xray-test` and does not
inject the key from the new OpenAI subfolder. `infisical run` can exit zero
without `OPENAI_API_KEY`, so verification must require the variable and compare
its SHA256 prefix with `4963df676805`. Root's broader runtime identity matches
that fingerprint; the worker token does not. Keep the broader identity outside
the worker.

After the scoped credential is provisioned, use the existing per-provider
directory ownership and read-only bind contract above, an OpenAI provider
entry, and `infisical run` child injection. The one-pass launcher must receive
both its existing Gemini credential and the separate dev OpenAI credential;
its current Gemini-only re-exec is insufficient. Keys stay in child process
memory. This credential work grants no analysis, route, budget or approval
change. See the [operator receipt](../../../docs/evidence/20261021_AUT2179_OPENAI_WORKER_ACCESS.md).

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
The migrator file may hold only those two keys.
It syncs the frozen production dependencies, then runs Alembic as uid/gid 10001
in the transient unit `ac-dev-sales-xray-migrate.service` (`systemd-run --wait`)
with the API unit's sandbox: `/srv/authority-closers` stays root:acops 2750 and
is masked by a read-only tmpfs, with only the backend bound back read-only, so
the step needs no traversal right or group. systemd reads `migrator.env` itself
(`EnvironmentFile=`); the URL never enters argv, this process or the checkout.
The smoke step uses the same sandbox (`ac-dev-sales-xray-smoke.service`).
The refresh then renders `service.json` from the root-owned development
template, writes the release marker and API/worker drop-ins, restarts the API, Sales Xray
worker and outbox worker units in that order, then polls `/health/ready` for up to 60 seconds. The refresh
passes only when the API reports the target release and its database is ready.

On failure it prints one JSON line with stable fields only: `phase` (`clone`,
`fetch`, `checkout`, `dependencies`, `migration`, `activation`, `restart`,
`health`), `error` (for example `migration_failed`, `api_restart_failed`),
`exit_status`, `previous`, `migrated`, `units_before` and `rollback`
(`ok`, `failed` steps, final unit states). Command output and URLs are never
printed. With a previous checkout, rollback restores the checkout, marker,
manifest and drop-ins and restarts only the units that were running before.
On a first install (`previous: null`) it stops all three units first, then removes
the new checkout and any files and directories it created, restores
`service.json` to its saved bytes, and leaves all three units stopped with their
failed state cleared, so nothing restart-loops. If a unit cannot be stopped, the
checkout is kept and the result is `rollback_failed`. Rollback never touches the
database, storage or credential files; a completed migration stays applied.

After backend health passes, the service runs the acdev-owned studio sync and
merges `origin/main` under `/run/ac-studio-sync/ac-studio-sync.lock`. A studio
merge failure raises an alert but leaves the refreshed backend in place. If the
target contains `scripts/ops/ac_smoke.py`, the script runs the development smoke
against that core and the merged UI checkout; otherwise it reports `skipped`.
Smoke failures are reported without rolling back the backend.

An explicitly reviewed backend repair can use `--preserve-studio` to retain
the owner's active UI checkout. Backend admission, migration, health and rollback
stay in force; studio sync/merge and its dependent UI smoke are skipped. The
scheduled timer supplies no flag and keeps its usual behavior. The isolated
organisation logo profile has its own [Root installation and rollback steps](organisation-avatar/README.md)
and never activates the broader filesystem media profile.

## Fixture accounts

`python -m ac_platform.development.sales_xray_fixture_accounts` creates three
fictional password accounts on the dev DB for signing in to salesxray-dev:
`sx-owner@example.test`, `sx-admin@example.test` and `sx-member@example.test`.
The addresses are fixed. Each account goes through the app's password
registration and one-use verification with no email sent, and gets only the
Personal learner membership and the current consent version. It gets no
platform role and no organisation; Root adds the organisation with the AUT-438
CLI. A rerun authenticates each existing account and changes nothing; a wrong
password or a changed account refuses without writing. No other person is
read or changed.

It refuses unless `--acknowledge-development-fixtures` is given,
`AC_ENVIRONMENT=development`, and `AC_DATABASE_URL` is exactly
`postgresql+psycopg` on host `172.27.0.2`, port `5432`, database `ac_platform`
(the dev Postgres container's bridge address, AUT-119), with no query string
and no `PG*` variables set. If that container is recreated with another
address, change `DEVELOPMENT_DATABASE` in the module and this section together.

Passwords come only from `AC_DEV_FIXTURE_PASSWORD_OWNER`, `_ADMIN` and
`_MEMBER` (12 to 256 characters), stored in Infisical `dev` at
`/sales-xray/dev-fixture-accounts`. They never appear in arguments or output;
the output is JSON of emails and person ids. Root runs it as uid 10001 with
`api.env`; `--setenv=NAME` without a value copies that variable from
`infisical run` into the unit:

```sh
sudo AC_INFISICAL_ENVIRONMENT=dev AC_INFISICAL_PATH=/sales-xray/dev-fixture-accounts \
  /usr/local/sbin/ac-infisical-run -- \
  systemd-run --pipe --wait --collect --quiet --uid=10001 --gid=10001 \
    --working-directory=/srv/authority-closers/development/backend \
    --property=EnvironmentFile=/etc/authority-closers/development/api.env \
    --property=MemoryMax=256M --property=CPUQuota=50% --property=Nice=10 \
    --property=TasksMax=32 \
    --setenv=AC_DEV_FIXTURE_PASSWORD_OWNER \
    --setenv=AC_DEV_FIXTURE_PASSWORD_ADMIN \
    --setenv=AC_DEV_FIXTURE_PASSWORD_MEMBER \
    --setenv=PYTHONDONTWRITEBYTECODE=1 \
    /srv/authority-closers/development/backend/.venv/bin/python \
    -m ac_platform.development.sales_xray_fixture_accounts \
    --acknowledge-development-fixtures
```

Done check: exit 0 and three `accounts` entries; a second run prints the same
person ids. Then sign in on salesxray-dev with each password.

## Admin dev image (AUT-970)

Admin dev (`admin-dev.authorityclosers.com`, loopback edge `127.0.0.1:3017`)
runs the `admin-web` service of the root-owned dev compose project `acdev-xray`
(`/srv/authority-closers/development/compose.yaml`, AUT-285).
`scripts/deploy-dev-admin-web.py` points that one service at the admin-web image
of a core release the release engine already stored and loaded for staging. It
never builds, pulls, retags or edits a container, and leaves `compose.yaml`,
every other service, staging and production alone.

Preflight (all before any change): the release is on `main` in
`/var/lib/ac-release/mirror.git`; each `--require-ancestor` merge is in it; its
stored `releases/<sha>` passes `RELEASE-FILES.sha256` and names it in
`AC_RELEASE_ID`; the local tag `…/authority-closers-admin-web:<sha>` exists,
carries `org.opencontainers.image.revision=<sha>` and is the same image as the
release's `AC_ADMIN_IMAGE`; Compose accepts the candidate override. The default
release is the `current-staging` core.

Apply writes `compose.admin-web-release.yaml` (`image:` the tag,
`pull_policy: never`) and runs `docker compose -p acdev-xray -f compose.yaml -f
compose.admin-web-release.yaml up --detach --no-deps --no-build --pull never
--force-recreate admin-web`. It passes only when the container is healthy on
that image and revision and the edge returns `/` → 307 `/login` and `/login` →
200; otherwise it restores the previous override and image. It records
`/var/lib/ac-dev-admin-web/history.jsonl` and the root-owned 0644 receipt
`deployed.json` (host, image, revision, verified merges) that the QA launcher
pins. Every later Compose command for `acdev-xray` must pass both files, or
Compose reverts admin-web; `status` reports that drift as `receipt_matches:
false`.

Root, from the released tree (`R=/srv/authority-closers/application/current-staging`):

```sh
S="$R/scripts/deploy-dev-admin-web.py"; M=1daeb17431a83a1330e9ec5f2362c29d3bb39c30
sudo python3 "$S" status --require-ancestor "$M"          # read-only revision proof
sudo python3 "$S" deploy --require-ancestor "$M"          # dry-run: preflight and plan
sudo python3 "$S" deploy --require-ancestor "$M" --apply  # serve the staging release
sudo python3 "$S" status --require-ancestor "$M"          # expect contains[M]=true, receipt_matches
sudo python3 "$S" rollback                                # plan; add --apply to restore
```

## Admin dev QA browser credential (AUT-970, AUT-984, AUT-1156)

Browser QA signs a fictional identity into Admin dev without seeing its
password. Declared references (names only; a separately reviewed fixture task
creates each account, platform grant and secret, not this code; until then the
broker refuses with `broker_secret_unavailable`):

| Identity                | Account                                | Infisical `dev` folder             | Secret name                             | Required Admin merge  |
| ----------------------- | -------------------------------------- | ---------------------------------- | --------------------------------------- | --------------------- |
| `billing-staff`         | `qa-billing-staff-aut969@example.test` | `/application`                     | `AC_DEV_BILLING_FIXTURE_PASSWORD_STAFF` | `1daeb174…` (AUT-890) |
| `organisation-operator` | `qa-org-operator-aut961@example.test`  | `/sales-xray/dev-fixture-accounts` | `AC_DEV_FIXTURE_PASSWORD_ORG_OPERATOR`  | `61e6b240…` (AUT-447) |
| `organisation-reader`   | `qa-org-reader-aut961@example.test`    | `/sales-xray/dev-fixture-accounts` | `AC_DEV_FIXTURE_PASSWORD_ORG_READER`    | `61e6b240…` (AUT-447) |
| `organisation-denied`   | `qa-org-denied-aut961@example.test`    | `/sales-xray/dev-fixture-accounts` | `AC_DEV_FIXTURE_PASSWORD_ORG_DENIED`    | `61e6b240…` (AUT-447) |

Organisation identities also need this capability matrix from the real API
after sign-in (platform grants only; organisation membership roles never
establish them):

| Identity                | `platform_tenants_read` | `platform_organisations_manage` | `GET /v1/platform/organisations` |
| ----------------------- | ----------------------- | ------------------------------- | -------------------------------- |
| `organisation-operator` | required                | required                        | 200 list                         |
| `organisation-reader`   | required                | must be absent                  | 200 list                         |
| `organisation-denied`   | must be absent          | must be absent                  | 403 `authorization_denied`       |

Billing staff must hold `platform_billing_manage` from the same normal
`GET /v1/me/platform-access` API. It does not need an Organisations permission
or request. Missing access routes, failed readback or a missing grant refuse
the browser handoff. The fixture customer is not a broker identity.

- `scripts/dev-qa-credential.py`, installed root:root 0750 as
  `/usr/local/sbin/ac-dev-qa-credential`, is the only root step. It reuses
  `/usr/local/sbin/ac-infisical-run` with `dev` and the identity's folder; a root
  inner process writes only the selected value from the exact declared
  secret-name allowlist to a pipe, including when the folder is `/application`.
  The old billing name, the customer password and undeclared names are refused.
  It refuses unless
  called through sudo by a non-root user, from the installed launcher, with
  stdout a pipe and an allowlisted identity. The bootstrap, `INFISICAL_TOKEN`,
  the folder's other secrets and every API/DB credential stay in root.
- `development/qa-admin-browser.py`, installed root:root 0755 as
  `/usr/local/libexec/ac-dev-qa/qa-admin-browser.py`, runs as QA. Preflight:
  non-root, allowlisted `@example.test` identity, origin exactly
  `https://admin-dev.authorityclosers.com`, a root-owned receipt containing the
  identity's required merge (AUT-890 for `billing-staff`), edge `/login` 200,
  `/v1/me` 401 through the edge and the dev API ready. It then runs a fresh
  sentinel through the same pipe into the real `/login` form, requires the API
  to refuse it, and checks that the sentinel is absent from browser
  argv/environments, profile files and its own output. Only then does it fetch
  the password into a buffer, type it over the DevTools pipe, zero the buffer
  and require `/v1/me` to return the named account. The browser reaches the
  https origin through an in-process TLS bridge to the edge, trusted by the
  ephemeral key's SPKI pin, so the real Host, Origin and `__Host-` cookies
  apply. All identities need, before any credential,
  `/v1/me/platform-access` signed out → 401. Organisation identities also need
  `/v1/platform/organisations` signed out → 401 (404 means the API route is not
  deployed: `organisations_route_absent`), and after sign-in the matrix above
  from `/v1/me/platform-access` and the list route; any difference refuses with
  `permission_matrix_mismatch`, `organisations_read_refused` or
  `organisations_not_capability_denied`. The `access` line prints only the
  person id, permission names and the route outcome, never the session id. It uses Playwright's Chromium with `--no-sandbox`, as Playwright does on
  this host (unprivileged user namespaces are off).
- Limits: all agents share the `acdev` user, so the caller checks guard against
  mistakes, not a hostile same-user process; the DevTools port (loopback) gives
  any `acdev` process the signed-in session, never the password, until the hold
  ends and the profile is deleted.

Root install, once per reviewed release:

```sh
install -d -o root -g root -m 0755 /usr/local/libexec/ac-dev-qa
install -o root -g root -m 0755 "$R/development/qa-admin-browser.py" /usr/local/libexec/ac-dev-qa/qa-admin-browser.py
install -o root -g root -m 0750 "$R/scripts/dev-qa-credential.py" /usr/local/sbin/ac-dev-qa-credential
cat > /etc/sudoers.d/ac-dev-qa-credential.new <<'SUDO'
Defaults!/usr/local/sbin/ac-dev-qa-credential !use_pty
acdev ALL=(root) NOPASSWD: /usr/local/sbin/ac-dev-qa-credential billing-staff, /usr/local/sbin/ac-dev-qa-credential billing-staff --sentinel, \
  /usr/local/sbin/ac-dev-qa-credential organisation-operator, /usr/local/sbin/ac-dev-qa-credential organisation-operator --sentinel, \
  /usr/local/sbin/ac-dev-qa-credential organisation-reader, /usr/local/sbin/ac-dev-qa-credential organisation-reader --sentinel, \
  /usr/local/sbin/ac-dev-qa-credential organisation-denied, /usr/local/sbin/ac-dev-qa-credential organisation-denied --sentinel
SUDO
visudo -cf /etc/sudoers.d/ac-dev-qa-credential.new && chmod 0440 /etc/sudoers.d/ac-dev-qa-credential.new \
  && mv /etc/sudoers.d/ac-dev-qa-credential.new /etc/sudoers.d/ac-dev-qa-credential
```

Organisation identities also need the deployed receipt to pin the AUT-447
Admin merge (root, after the install above, same release tree):

```sh
S="$R/scripts/deploy-dev-admin-web.py"
sudo python3 "$S" status --require-ancestor 1daeb17431a83a1330e9ec5f2362c29d3bb39c30 \
  --require-ancestor 61e6b240cd16c35ca87c19518aefcba1f3d3d555 --write-receipt
```

Done check: `deployed.json` is root:root 0644 with both SHAs in `contains`.
Rollback: remove those three files (the receipt is rewritten by the next
`deploy` or `status --write-receipt`). Upgrading from the AUT-970 install:
keep a copy of the three files first; rollback restores them. QA invocation
(non-root):

```sh
/usr/local/libexec/ac-dev-qa/qa-admin-browser.py --identity billing-staff --sentinel-only  # transport proof only
/usr/local/libexec/ac-dev-qa/qa-admin-browser.py --identity billing-staff                  # sign in and hand off
/usr/local/libexec/ac-dev-qa/qa-admin-browser.py --identity organisation-operator
/usr/local/libexec/ac-dev-qa/qa-admin-browser.py --identity organisation-reader
/usr/local/libexec/ac-dev-qa/qa-admin-browser.py --identity organisation-denied
```

Output is JSON lines with no value. The `handoff` line gives `devtools`
(`http://127.0.0.1:<port>`) for Playwright `chromium.connectOverCDP`; the browser
stays up for `--hold-seconds` (default 3600) or until Ctrl-C/SIGTERM, then the
profile is deleted. A `refused` line names the failed check.

## Sales Xray: protected saved-report QA (AUT-1232)

Use the existing dev studio and AUT-1116 protected credential handoff to read
only its approved fictional report `dadaed4c-2f24-4299-b2fa-c0c47f9b374a`:

```sh
# From the devenv lane checkout, as acdev; no arguments or credential output.
.venv/bin/python infra/application/development/qa-sales-xray-report.py
```

The launcher serves the browser an ephemeral, loopback-only TLS connection to
the existing edge on `127.0.0.1:3016`, using
`https://salesxray-dev.authorityclosers.com` as its actual browser origin.
Chromium trusts only that run's certificate SPKI. It supplies Host and Origin
normally and stores the normal Secure, HttpOnly, host-only session cookie.
Do not substitute `http://localhost:3016` with an overridden Origin: that
invocation failed sign-in 403 and workspace 401 in the recorded reproduction.

The upstream remains the existing staging studio route authorized by AUT-154;
this invocation does not provide an independent dev database or copy the report.
Its exact Origin exception and normal account authorization remain enforced by
staging. No host/service install, Caddy edit, account/grant change or security
setting is needed. The Admin launcher's origin, edge and credential rules retain
their existing defaults; only its TLS utility accepts explicit internal host
and edge arguments for reuse.

A fictional sentinel must receive 401 before the credential is read. The real
password is read into memory from the existing AUT-1116 file and submitted
through the current UI's password form. Chromium receives only PATH, HOME and
the host's shared-library path in its environment. The report is read at
1440x900 and 390x844; JSON stdout contains statuses, binding and visibility
flags only. Other reports, external requests, encoded API paths and background
writes are blocked. The browser, profile and temporary TLS files are removed
when the run ends. No screenshot, transcript or report text is exported.

Use the source-owned invocation from a reviewed main release after merge; the
normal release train carries the script. When running a released copy, use the
lane's existing Python/browser environment:

```sh
.venv/bin/python /srv/authority-closers/application/current-staging/development/qa-sales-xray-report.py
```

Both launcher files must come from that same release tree. Rollback is to stop
using this QA command; it changes no persistent runtime configuration. Do not
fall back to the failing HTTP/header-override invocation or injected cookies.

The [AUT-1156 released-runner runbook](../../../docs/evidence/20261005_AUT1156_BILLING_QA_TRANSPORT.md#operator-runbook)
specifies Root installation, the immutable API executable, dev network and
input boundaries, access-manager prerequisites, preview/apply and rollback.
Actual fixture application stays on [AUT-959](/AUT/issues/AUT-959).

## Dev server watchdog (acdev user units)

`acdev-dev-watchdog.sh <unit> <url> [host]` probes one dev server's page every
30 seconds from acdev's templated user timer `acdev-dev-watchdog@<unit>.timer`.
A 5xx, no answer or a 20-second timeout starts a "bad since" clock in
`~/.local/state/acdev-dev-watchdog/<unit>/`; a good answer clears it. Two
minutes bad restarts the unit, at most once every five minutes, with one journal
line naming the URL, the answer and the unit's memory. A unit that is not active
(stopped on purpose, or failed) is left alone. Each instance reads its probe
(`PROBE_URL`, `PROBE_HOST`) from `~/.config/acdev-dev-watchdog/<unit>.env`,
installed from `acdev-dev-watchdog/`:

- `acdev-admin-dev`: `http://127.0.0.1:3028/login`, Host `admin-dev.authorityclosers.com`
- `acdev-xray-dev`: `http://127.0.0.1:3026/login`, Host `salesxray-dev.authorityclosers.com`

Both login pages render without server-side API reads, so a down back end never
restarts a web server. These are acdev's own user units, not system services: no
Root step.

Why: on 20 Oct 2026 Turbopack hung compiling a new Admin route, and on 21 Oct
the Sales Xray dev server sat at its 3 GB `MemoryHigh` with its 512 MB swap full,
less than two hours after the nightly restart. At `MemoryHigh` the kernel
throttles a service instead of killing it, so `Restart=on-failure` never fired
and every page timed out until a manual restart. Its Turbopack file-system cache
(`apps/sales-xray-web/.next/dev/cache/turbopack`) had grown to 9.6 GB since
11 Oct; restoring and compacting it is what fills the server's memory.

Install or update, as acdev:

```bash
install -m 755 infra/application/development/acdev-dev-watchdog.sh ~/.local/bin/acdev-dev-watchdog
mkdir -p ~/.config/acdev-dev-watchdog
install -m 644 infra/application/development/acdev-dev-watchdog/*.env ~/.config/acdev-dev-watchdog/
install -m 644 infra/application/development/acdev-dev-watchdog@.service infra/application/development/acdev-dev-watchdog@.timer ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now acdev-dev-watchdog@acdev-admin-dev.timer acdev-dev-watchdog@acdev-xray-dev.timer
```

The `acdev-admin-dev` instance replaces the Admin-only watchdog of 20 Oct
(`acdev-admin-dev-watchdog.*`). Remove that one once:

```bash
systemctl --user disable --now acdev-admin-dev-watchdog.timer
rm -f ~/.config/systemd/user/acdev-admin-dev-watchdog.service ~/.config/systemd/user/acdev-admin-dev-watchdog.timer ~/.local/bin/acdev-admin-dev-watchdog
rm -rf ~/.local/state/acdev-admin-dev-watchdog
systemctl --user daemon-reload
```

Watch it with `journalctl --user -u 'acdev-dev-watchdog@*'`.

## Sales Xray dev server units and its nightly cache cap (acdev user units)

`acdev-xray-dev/` records the Sales Xray dev server (`next dev --turbopack` on
`127.0.0.1:3026`) as installed in acdev's `~/.config/systemd/user/`:

- `acdev-xray-dev.service` and its drop-ins in `acdev-xray-dev.service.d/`:
  `30-asset-version.conf` (`NEXT_DEPLOYMENT_ID`), `50-CPUQuota.conf` (75 % of one
  core, the same value as the 29 Sep `set-property` drop-in in
  `~/.config/systemd/user.control/`, which takes precedence), `80-memory.conf`
  (`MemoryHigh` 3G, `MemoryMax` 3584M, swap 512M; 1700M throttled it into
  Cloudflare 524s on 11 Oct), `85-api-origin.conf` (server reads through the dev
  edge on :3016) and `zz-dev-live.conf` (it runs from the shared workbench).
- `acdev-xray-dev-restart.timer` (22:30 UTC, 04:00 IST) starts
  `acdev-xray-dev-restart.service`, which runs
  `acdev-dev-restart.sh <unit> <cache-dir> <cap-MiB> [<url> [<host>]]`. It notes
  the unit's memory peak, pauses its watchdog
  (`acdev-dev-watchdog@acdev-xray-dev.timer`) so a slow first compile is never
  restarted halfway, stops the unit, moves its Turbopack cache
  (`apps/sales-xray-web/.next/dev/cache/turbopack`) aside when the cache is above
  2048 MiB, starts it, waits for the watchdog's probe page (the first compile),
  resumes the watchdog, then deletes the old cache at idle IO priority. A unit
  stopped on purpose stays stopped; a failed one is started; a watchdog that was
  off stays off. The script only ever moves or deletes a directory named
  `.../.next/dev/cache/turbopack`, never a symlink, and nothing else under
  `.next`. The cache is a build cache that next dev rebuilds. Deleting it needs no
  owner approval: decision of the xray-dev-watchdog orchestrator session, 21 Oct,
  under the owner's 18 Oct order that only permanent deletion of customer data
  waits on him (compiler output, no customer data, no audit history). The first
  reset ran on 21 Oct at 12:06 UTC: 9,822 MiB cleared, `/login` 200 after 23 s.

Why: next dev 16.3.8 keeps a Turbopack file-system cache that nothing prunes.
Between 11 and 21 Oct it grew to 9.6 GB, about 2 GB on a busy day. As it grew,
a run's memory peak went from 1.4-1.9 GB (12-15 Oct) to 2.8-3.3 GB (16-20 Oct)
with a JS heap under 0.6 GB, and HMR went from 0.5 s (p50, 11 Oct) to 13-38 s
(p50, 18-20 Oct). Restoring and compacting the cache does it: on 21 Oct at 11:34
UTC, with no page requests, one compaction (740 MB written) took the unit over
`MemoryHigh` 462 times, 1.6 GB of it cache file pages. On 20 Oct the 22:30
restart read about 4.5 GB in ten minutes, filled the swap and hung at
`MemoryHigh` until a manual restart. With
the cap the cache stays under about 4.5 GB and is reset every one or two busy
days. Next's default `experimental.turbopackMemoryEviction: 'auto'` does not see
the unit's 3 GB limit (the host has about 8 GB free), so it rarely evicts. If daily
peaks stay above about 2 GB with the cap, the next lever is `'full'` for dev in
`apps/sales-xray-web/next.config.ts`, which trades memory for re-reads on every
HMR.

Install or update, as acdev (`XDG_RUNTIME_DIR=/run/user/1002`):

```bash
D=infra/application/development
install -m 755 $D/acdev-dev-restart.sh ~/.local/bin/acdev-dev-restart
install -m 644 $D/acdev-xray-dev/acdev-xray-dev.service $D/acdev-xray-dev/acdev-xray-dev-restart.service $D/acdev-xray-dev/acdev-xray-dev-restart.timer ~/.config/systemd/user/
mkdir -p ~/.config/systemd/user/acdev-xray-dev.service.d
install -m 644 $D/acdev-xray-dev/acdev-xray-dev.service.d/*.conf ~/.config/systemd/user/acdev-xray-dev.service.d/
systemctl --user daemon-reload
systemctl --user enable acdev-xray-dev-restart.timer
```

A changed drop-in reaches the running server at its next restart, the nightly one
at the latest. Watch it with `journalctl --user -u acdev-xray-dev-restart.service`:
one line a night with the memory peak since the last start, the cache size, whether
it was cleared and how long the first compile took.
