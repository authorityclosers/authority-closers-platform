# ADR 0037: Development Sales Xray backend identity

Status: proposed. Source: [AUT-155 plan](/AUT/issues/AUT-155#document-plan),
revision 3 (`6a57c5e6-23f7-4455-a3e7-b4a5222c563b`), CTO, 29 September 2026.
The Decision, Alternatives and Consequences below preserve that design record.
AUT-157 supplies units only; refresh, native installation and activation remain
separate tasks. Their historical routing references are not new host commands.

## Decision


The dev Sales Xray back end runs as **two root-managed system services under uid/gid 10001**, **from a root-owned checkout of the exact commit staging runs**, **inside a systemd sandbox that shows them only development paths**. The native helper for `development` is a **fresh native build of a main commit** whose own release renderer knows `development`.

- **Code:** `/srv/authority-closers/development/backend`, root-owned, `.venv` built by root (`uv sync --frozen --no-dev`). No agent can write it. It follows `current-staging` (CI-green, deployed main), so dev back end = main. The dev web stays the live ui checkout.
- **Services:** `ac-dev-api.service` (`python -m ac_platform.http --host 127.0.0.1 --port 8100`, the same port Caddy uses now) and `ac-dev-sales-xray-worker.service` (`python -m ac_platform.conversation_intelligence.service` behind `/usr/bin/env -i` with only allowlisted vars, and `/app/.ac-release-id` bound read-only from the checkout's marker). Both run `User=10001 Group=10001`.
- **Sandbox (both units):** `ProtectSystem=strict`, `ProtectHome=yes`, `PrivateTmp=yes`, `PrivateDevices=yes`, `NoNewPrivileges=yes`, empty `CapabilityBoundingSet=`, `RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6`, `UMask=0077`. `TemporaryFileSystem=` hides `/srv/authority-closers`, `/run/ac-sales-xray` and every staging/production credential root, then binds back only `backend` (ro), `sales-xray/development` (rw) and `/run/ac-sales-xray/development` (ro). No Docker socket.
- **Secrets:** root-owned `/etc/authority-closers/development/` (0700). systemd reads `api.env` (`EnvironmentFile=`, root 0600). Secret files (challenge secret, QA password, worker DB URL, provider identity tokens, approval bundle, worker manifest) reach the process through `LoadCredential=` (0400, owned by the service user) or read-only binds of root-owned per-provider directories where the code requires one. The engineer picks one per file in AUT-157. **acdev (every agent) can't read any of them**, and `/proc/<pid>/environ` of a uid-10001 process is closed to acdev.
- **Refresh:** a root timer runs a reviewed script that moves the checkout to `current-staging`, runs `uv sync`, migrates the **dev DB only**, writes the release marker and worker manifest digest, and restarts both units. It refuses a target whose native inputs differ from the dev native build's commit. App code (alembic, python) never runs as root.
- **Native for development:** dispatch `sales-xray-native-image.yml` with `frozen_sha` = main HEAD at dispatch time, when `releases/<sha>` exists on ac. `find_native_run()` matches `head_sha`, so the sha must be main HEAD when dispatched. `ac-release store-native` within 24 h (artifact retention is 1 day). Install with the reviewed installer for `development` only. Staging and production stay on `390b4285`: untouched, no reinstall. Native helpers are unmanaged by `prune-artifacts`, and `native_for_image()` stays unambiguous as long as the new image ref differs from `390b4285`'s (a stop check in the host steps).
- **Latent release-path bug (blocker 1), fixed separately:** the installer accepts a **reviewed set** of renderer hashes, each with the environments it renders. Old builds install with main's installer again, and a test fails when the renderer changes without a new reviewed entry. Making the renderer a native input was rejected: every renderer edit would block staging and production deploys until a native reinstall (`native_inputs_changed`).

### Alternatives rejected
- **Per-environment peer uid (e.g. 10002 for dev):** changes pinned native inputs and forces a native reinstall on staging and production. Largest blast radius.
- **Dev as a third release-engine environment (containers):** the most faithful, but `install-application-release.sh` (1,649 lines) and the release engine are staging/production only. Weeks of release-path change. Revisit if dev needs parity beyond Sales Xray.
- **acdev user units with uid 10001 access:** gives every agent the native socket and puts provider keys in agent-writable code's reach.

### Consequences
- Agents lose `systemctl --user restart acdev-api` and the dev API's journal. The dev back end changes only through main → staging → refresh. Debugging goes through the Root specialist or a later read-only log path (not in scope).
- Dev back end lags main by the staging deploy time (minutes).
- The AUT-154 route (dev `/v1/*` → staging) stays until AUT-123's end-to-end passes. Then dev `/v1/*` moves back to the dev API (CEO decision, 29 Sep): it is the last step of AUT-123's command list, with no further sign-off.
- The `acdev-api` user unit is frozen (CEO, 29 Sep) until AUT-119 replaces it with `ac-dev-api.service`: nobody rebuilds, edits or restarts it with changes.


## Filesystem boundary inventory

Reviewed against `infra/application/scripts/install-application-release.sh`,
`infra/release/ac_release.py` and `infra/conversation-worker/HOSTED_ACTIVATION.md`.
The installer also invokes `infra/vps-foundation/scripts/ac-infisical-run`.
Both units hide these host roots, including all their children:

| Hidden host root | Staging/production material |
| --- | --- |
| `/srv/authority-closers/application` | releases, artifacts, deployments, operator-inputs, current-staging/current-production, edge routes |
| `/srv/authority-closers/releases` | foundation releases |
| `/srv/authority-closers/current` | foundation current link |
| `/srv/authority-closers/state/application/staging` | database and application state |
| `/srv/authority-closers/state/application/production` | database and application state |
| `/srv/authority-closers/backups/application/staging` | database backups |
| `/srv/authority-closers/backups/application/production` | database backups |
| `/srv/authority-closers/volumes/media-video/staging` | video data |
| `/srv/authority-closers/volumes/media-video/production` | video data |
| `/srv/authority-closers/volumes/media-safety-socket` | scanner socket |
| `/srv/authority-closers/sales-xray/staging` | recording storage and scratch |
| `/srv/authority-closers/sales-xray/production` | recording storage and scratch |
| `/srv/authority-closers/release-store` | release and native artifacts |
| `/etc/authority-closers/sales-xray/staging` | manifest and approval |
| `/etc/authority-closers/sales-xray/production` | manifest and approval |
| `/etc/authority-closers/secrets` | Infisical bootstrap, DB/challenge secrets and all provider identities |
| `/run/ac-sales-xray/staging` | native helper socket |
| `/run/ac-sales-xray/production` | native helper socket |
| `/etc/ac-release` | GitHub read token and release configuration |
| `/var/lib/ac-release` | release history, mirror and control state |
| `/var/log/ac-release` | release logs |
| `/run/ac-release.lock` | release lock |
| `/run/docker.sock` | Docker control socket (`/var/run` aliases `/run`) |
| `/run/containerd` | container runtime sockets |
| `/var/lib/docker` | container volumes and layers |
| `/var/lib/containerd` | container runtime data |

The three tmpfs masks are read-only; only the dev recording tree is rebound
writable. PrivateTmp hides release-engine `/var/tmp` staging. ProtectHome hides
agent and root homes. The two provider directory binds expose only development
identities; credentials use systemd's per-unit read-only credential directory.
Because uid 10001 is shared, `/proc` is inaccessible to prevent foreign process
root/fd paths from bypassing the mounts; `~@debug` denies ptrace and process-memory
syscalls. Host activation must check API and provider-child startup with these
restrictions. Native container self-checks run in the separate native helper.
These mount controls follow [systemd.exec](https://github.com/systemd/systemd/blob/v255/man/systemd.exec.xml).
Network families remain enabled for the dev DB and approved providers: filesystem
isolation is not an egress firewall. Activation must supply dev-only DB endpoints
and credentials. No production DB or provider configuration is inferred here.

## Resource and verification consequences

Both services cap memory at 768M, CPU at 100%, use Nice=10 and idle I/O priority;
API TasksMax=128 and worker TasksMax=64. The worker drains for up to 16 minutes
before systemd kills its process group. Tests check the unit contracts and every
inventory path, and verify the exact unit bytes with systemd-analyze in an inert
fixture root. No service starts during tests. Runtime isolation and the fictional
upload journey remain Root specialist checks after AUT-159 and host installation.
