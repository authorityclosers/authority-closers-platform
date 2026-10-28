# Remote production executor (inactive source)

This change is **code and tests only**. It has not been installed, enabled, or
used against staging or production. The coordinator and staging stay on the VPS.
The destination can be the approved Sydney EC2 instance, Lightsail, or a later
host; the protocol has no AWS API or region dependency.

## Trust and invariants

The coordinator still admits main/CI builds, checks staging, owner authority,
version and schema compatibility, and owns the release ledger. The destination
runs the existing source-owned application/web/foundation/native controllers.
It never builds images or fetches from GitHub. The admitted core/web bundles,
provenance and native zip/descriptors are copied byte-for-byte; an offline Git
bundle supplies the exact installer sources and native reuse history. Destination
checksums are checked for the complete inventory before anything is imported or
loaded. The installed executor controller must match the coordinator's installed
controller SHA. A controller mismatch refuses the operation.

Only `prepare`, `install`, `status`, `backup`, `canary`, `rollback-app` are accepted.
The SSH key also reaches a single-file SCP receiver: only legacy SCP uploads to
`/var/lib/ac-release-executor/incoming/<32 lowercase hex>.tar`, maximum 4 GB,
exclusive creation, no directories, symlinks, downloads or arbitrary paths.
SCP never invokes a shell or the system SCP server. Modern SFTP is refused;
the client explicitly uses `scp -O`.

Receipts under `/var/lib/ac-release-executor/receipts` are durable JSON containing
target identity, request ID/digest, member digests, predecessor tuple, boot ID,
start/end time, duration and prepared/committed/failed/unknown result. State is
written and fsynced before execution and after readback, under the host lock and
the existing engine lock. Installer deployment locks remain in effect. Only a
committed receipt and an exact final tuple readback allow coordinator success.

## Operator bootstrap, later — do not run as part of source review

1. Follow the separately approved host/data migration plan. Provision the host,
   foundation, Docker, `acops`, production state/secrets, edge routes, native
   helper/activation and canary/backup/restore-proof dependencies through their
   governed installers. Preserve the current and predecessor release artifacts,
   activations and schema evidence. Do not copy staging credentials, start a
   second production scheduler, or activate providers through this installer.
   This executor does not select or invent a lean application profile; the
   admitted application release and approved host bootstrap own that profile.
2. Select one reviewed commit for both coordinator and executor. On the new host,
   from its root-owned clean reviewed checkout under trusted parents (for example
   `/root`), an operator can run:

   ```sh
   sudo infra/release/remote/install-executor.sh
   ```

   This installs root-owned, mode 0755 directories under
   `/opt/ac-release-executor/releases/<sha>`, the isolated Python entry point and
   `/usr/local/libexec/ac-release-executor`. It does **not** install a key, target
   map, service or timer. It does not invoke `install-release-engine.sh`, which
   enables coordinator timers and must not be used to bootstrap this host.
   Only root may write installed code, configuration, incoming files and receipts.
3. Set root-owned mode 0600 `/etc/ac-release/executor.json` on the new host:

   ```json
   {"target":"production-host.example.invalid"}
   ```

   Use the exact same host identity in the coordinator target map. The host's
   engine uses the verified offline bundle and its own local state; it cannot
   recurse into a remote target or sync GitHub. No GitHub token is needed there.
4. Create a dedicated coordinator-held SSH key using the approved secret store
   procedure. Do not put its private bytes in Git, logs or this runbook. On the
   destination, authorize **only its public key**, with this exact restriction
   shape, replacing the address and public-key placeholders:

   ```text
   from="<VPS_EGRESS_IP>/32",restrict,command="/usr/local/libexec/ac-release-executor" ssh-ed25519 <DEDICATED_PUBLIC_KEY> ac-release-coordinator
   ```

   Require `PermitRootLogin forced-commands-only`; disable password/keyboard
   authentication for this access, user environment injection, tunnel and
   forwarding access. Preserve the operator's separately governed recovery
   access. Test sshd configuration before reload. Restrict network ingress to
   the coordinator's source address as well. The key gets no interactive shell,
   PTY, agent/X11/TCP forwarding, arbitrary sudo, or other root command.
5. Obtain the host key fingerprint over the approved console/out-of-band channel.
   Compare it before writing the coordinator's root-owned known_hosts file.
   `ssh-keyscan` output alone is not authentication. The client ignores SSH
   config, pins the identity and this known_hosts file, requires strict matching,
   and disables automatic host-key updates and forwarding.
6. Install/read back the reviewed coordinator engine through the authorized
   operator process. Its installer now copies `ac_remote.py` alongside the engine.
   `/usr/local/sbin/ac-ship` is deliberately unchanged in this source task.
   Before switching targets, apply the reviewed
   [`infra/release/remote/ac-ship.patch`](../../infra/release/remote/ac-ship.patch)
   through that same authorized installation process. The patch is pinned to
   the inspected installed script SHA-256
   `ae925f4cb17155816868c764971f19eff5ab67969fc78303734e9b3a8bdcd9a7`.
   Refuse drift; review a fresh patch if that script has changed. This wraps its
   production native descriptor lookup, backup and canary calls while retaining
   all existing checkpoint/CI/staging/version/owner gates and local commands.
   Target-map errors stop the ship, rather than selecting a local fallback.

## Switching targets, later

Absent `/etc/ac-release/targets.json`, or omitted environment entries, every
existing environment stays local. An empty map and explicit local map are also
local. Remote staging is refused. The operator must finish the ac-ship adapter,
bootstrap and rehearsal before atomically installing a root-owned mode 0600 map:

```json
{
  "staging":"local",
  "production":"remote:production-host.example.invalid",
  "ssh":{
    "identity_file":"/etc/ac-release/production-executor.key",
    "known_hosts_file":"/etc/ac-release/production-executor.known_hosts"
  }
}
```

Never change this map during a ship. Pause the coordinator's production/train
entry points during cutover, transfer the authoritative predecessor and release
ledger through the migration procedure, and stop the old production timers and
consumers before the new host owns production. Retain a single release operator.
Do not leave stale VPS production containers serving or scheduling work.

`ac-release production-target` reads configuration only. With remote mode,
`status`/Admin, production install, foundation backup refresh, native preparation,
application rollback, train backup/restore checks and production smoke resolve on
the destination. Staging uses its existing local path. The coordinator retains
its version ledger and pause flags. The executor retains destination deploy
history for native and web rollback.

The adapter exposes `ac-release remote-op backup`, `remote-op canary`, and
`remote-op prepare-native --sha <admitted core SHA>` to the authorized ship tool.
These are **real operations**, not installation diagnostics. Do not run them
before the operator authorizes the rehearsal/cutover. Remote promotion requires
the existing local production-enabled flag; it records a version only after a
passing production canary bound to the admitted core/web pair.

## Backup and rollback

Before an application install the destination requires a fresh verified backup
(under 30 minutes, matching predecessor, positive dump and matching SHA-256).
Core then web, and an admitted schema-compatible native bridge then final core,
can use that same capture. A successful core extends only that receipt's allowed
predecessor chain. The automatic train keeps its existing bounded dump/disk and
off-host restore-proof requirements. It does not inherit a weaker snapshot gate.

The supervised ship backup may fall back from the bounded dump to the reviewed
Drive snapshot command with `--execute`. This accepts only its structured
`upload_download_decrypt=passed`, same-exported-snapshot receipt, and a fresh
local dump with matching release/size/hash/pg_restore metadata. An older tool
that prints an opaque path is refused. The installed VPS snapshot tool was not
readable by acdev in this source task; compatibility with that older installed
binary is not claimed. The destination must have the reviewed structured helper
before cutover. No backup limit or retention policy is raised by this change.

Application rollback selects the previous pair centrally, repeats the schema
compatibility check at the destination, and uses `AC_CORE_ROLLBACK_ONLY` with the
installed reviewed controller. It never restores the database. Native historical
activation, approval and rollback guards remain in the existing installers.
Rollback may proceed without a new backup; it cannot bypass unknown host state.

## Connection loss, host restart and recovery

The coordinator stores immutable request manifests/payloads under
`/var/lib/ac-release/remote-requests/<id>`. It queries an existing ID before
resending. The host returns a completed receipt for duplicates without replaying
the installer; different content under the same ID is refused. A known refusal before the
installer starts stays failed. After fixing a missing backup, a fresh verified
backup receipt creates a new admitted request; the failed ID is never replayed.
After a lost
install response, it reads that receipt and the live tuple. A completed receipt
plus matching tuple succeeds without another install or rollback.

A host restart during execution, interrupted installer, missing final receipt,
or final tuple mismatch is **unknown pending operator readback**, not permission
to retry, promote or roll back. Running/unknown receipts block new installs and
preparations across request IDs while leaving status available. Do not delete or
edit receipts or point production back at the old VPS. The named recovery
operator must compare the request, artifact pins, current tuple, schema,
activation and installer deployment records through the approved recovery path.
Any resolution needs a separate reviewed recorded recovery that supersedes the
unknown evidence; this narrow executor has no general-purpose recovery/shell
verb. Retain original receipts. A failing canary leaves production paused and no
successful new version event; recovery remains supervised.

## Required proof before activation

The source tests use fake transports/hosts and synthetic Git, never production.
Before activation, the authorized operator still owes a real isolated-host
rehearsal: source/key restriction, pinned-key failure, fresh backup plus restore
proof, exact bundle/native pins, staging-local/production-remote readback,
canary failure, lost connection, reboot, compatible app rollback, memory/disk
budget and the synthetic consent/provider/budget scope. Do not claim zero
downtime or live production proof from these unit tests. Retain current and
predecessor artifacts before upstream expiry; never prune unknown requests.
The initial offline Git bundle contains all mirror refs to preserve reuse and
rollback provenance; size and retained payload headroom must be measured on the
approved small host. Source-only shipping does not auto-install an executor
update; controller SHA drift fails closed until the operator aligns reviewed
controllers.
