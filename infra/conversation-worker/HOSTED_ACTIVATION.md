# Release-owned Sales Xray activation

The application image and native image are separate immutable artifacts. The
existing four-image release remains API, learner, admin and coach. Native C1 is
an additional image; do not discover or build it on the VPS. Native packaging
uses `infra/conversation-worker/Dockerfile`, repository-root context, linux/amd64,
and the frozen integrated source commit. See the dedicated native-image workflow.
The standalone frontend's final hostname/transport remains part of the release
task's routing work; this worker overlay does not publish a frontend or DNS.

## Approval and service files

`approval.operator-template.json` and `service.operator-template.json` are
deliberately invalid operator templates. Replace every `REPLACE_WITH_...` using
verified current records and approvals. An empty stage list authorizes no provider
calls. Do not replace missing permissions, quotes or allowances with synthetic
entries. The complete allowance and C2/C4/C5 stage shapes are defined by
`AllowanceApproval` and `StageApproval` in `activation_contract.py`; those include
exact person/tenant/source, active provider configuration digest, provider/model,
recipe, credential reference, request/token/byte limits, pricing evidence,
free-allowance/no-overage references, retention, privacy and expiry.

Render actual files outside Git, mode0444 with non-writable parent directories.
Canonicalize the approved bundle with `load_hosted_approval_bundle(raw).to_json()`
before installation, then hash those exact installed bytes. The API and worker
must use that same file and digest. The service file's release_id must equal
`/app/.ac-release-id` inside the frozen API image. Its native_image_ref is the
verified `sha256:...` OCI transport manifest digest from the loaded native
artifact. The artifact records the separate Docker config/image ID and proves
that the transport manifest references it. After loading, inspect that exact
transport digest and record the store's actual identity behavior. Docker29's
containerd image store on the current VPS returns the verified OCI manifest as
its `.Id`; classic Docker returns the independently bound configuration ID.
Accept `.Id` only if it is that exact verified manifest or its independently
verified configuration ID. A configuration-reference fallback must resolve to
that exact configuration ID. In every case retain the verified archive checksum
and manifest-to-configuration binding; a mutable tag or an unrelated image ID
does not establish image identity. Use the manifest reference when the store
supports it.

The one-time migration bootstrap is a separate, explicit service manifest. Set
`bootstrap_only` to `true`, set `providers` to `[]`, and install an approval
whose `allowances` and `stages` are both empty, has no `acquisition_policy`, and
has no paid budget (`budget_cap_paise` is zero and `paid_approval_ref` is absent).
Its release environment file must set `AC_XRAY_ACQUISITION_ENABLED=false`.
The bootstrap worker validates those exact bindings and then waits for SIGTERM;
it does not open the database, inspect queues, read provider identities or call a
provider. The API overlay receives the same false value and therefore does not
install guest acquisition routes.

Run migration `0037`, then run the supported `processing_cli` provisioning path
against that migrated database to obtain the actual processing principal UUID.
Retain the bootstrap files as an audit record. A subsequent versioned activation
must use the same immutable image with `bootstrap_only=false`, approved provider
launchers, the real principal-bound policy, and
`AC_XRAY_ACQUISITION_ENABLED=true`; reapply it through the canonical installer.
Do not invent principal IDs or replace the bootstrap artifact in place.

For production, replace both the environment and every staging path with their
separate production counterpart; use its own approved bundle and DB credential.
Neither environment adopts or copies private test audio from a local directory.

The service template contains the actual approved Infisical project/path names,
but no token or provider key. Its credential_ref values must exactly match the
approved stages. Initial external identity directories are:

- `/etc/authority-closers/secrets/sales-xray/identities/elevenlabs`
- `/etc/authority-closers/secrets/sales-xray/identities/groq`
- `/etc/authority-closers/secrets/sales-xray/identities/gemini`

Each directory contains only its own token, UID10001, mode0400. The original
ElevenLabs/Groq tokens expire after 24 hours; the Gemini testing token expires
on 2026-09-20 at 22:53 UTC. Verify and renew each scoped identity before sustained
operation. The worker
does not refresh them. Do not mount the parent secret directory. The Infisical
binary is `/usr/local/bin/infisical`, mounted at `/opt/infisical`. The DB-only
credential file is separately provisioned through the existing secret mechanism;
its value is never an argument, compose environment variable or printed output.

## Nonsecret deployment environment

Supply these alongside the release task's existing core Compose configuration.
All values below are references or hashes, never credentials:

```text
AC_XRAY_SERVICE_CONFIG=/etc/authority-closers/sales-xray/staging/service.json
AC_XRAY_SERVICE_SHA256=<SHA256 of exact service.json bytes>
AC_XRAY_APPROVAL_FILE=/etc/authority-closers/sales-xray/staging/approval.json
AC_XRAY_APPROVAL_SHA256=<SHA256 of exact canonical approval.json bytes>
AC_XRAY_DATABASE_URL_FILE=<approved staging DB-only external file>
AC_XRAY_STORAGE_ROOT=/srv/authority-closers/sales-xray/staging/storage
AC_XRAY_SCRATCH_ROOT=/srv/authority-closers/sales-xray/staging/scratch
AC_XRAY_NATIVE_SOCKET_DIR=/run/ac-sales-xray/staging
AC_XRAY_ELEVENLABS_IDENTITY_DIR=/etc/authority-closers/secrets/sales-xray/identities/elevenlabs
AC_XRAY_GROQ_IDENTITY_DIR=/etc/authority-closers/secrets/sales-xray/identities/groq
AC_XRAY_GEMINI_IDENTITY_DIR=/etc/authority-closers/secrets/sales-xray/identities/gemini
AC_XRAY_INFISICAL_BINARY=/usr/local/bin/infisical
AC_XRAY_NATIVE_IMAGE_REF=<verified immutable native transport image reference>
AC_XRAY_CHALLENGE_SECRET_FILE=/etc/authority-closers/secrets/sales-xray/staging/challenge-secret
AC_XRAY_CHALLENGE_SITE_KEY=<public site key for the exact Sales Xray host>
AC_XRAY_ACQUISITION_ENABLED=true
AC_XRAY_ACQUISITION_POLICY_REVISION=<approved acquisition policy revision>
```

For production, use the corresponding `production/challenge-secret` path. The
challenge file is provisioned out-of-band by the approved Cloudflare secret
delivery operator; it is never placed in a Compose environment file, command
argument, image or log. Its fixed basename and metadata are part of activation:
it must be a singly-linked regular file no larger than 4 KiB, owned by UID
`10001`, GID `0`, mode `0400`. Every existing parent must be a root-owned,
non-writable directory with no symlink. Docker resolves the host-side bind as
root; the API only sees `/run/ac-sales-xray/challenge-secret`, so private `0700`
source parents are valid. The operator
creates or rotates it atomically and verifies those facts without printing its
contents. `sales-xray-hosted.py compose-inputs` repeats the no-symlink, regular
file, size, ownership and mode checks before Compose receives the path. See
`infra/application/SALES_XRAY_CHALLENGE_CREDENTIAL.md` for the bounded
provisioning contract.

The release-owned `infra/application/compose.sales-xray-hosted.yaml` merges the
AC_SALES_XRAY_* nonsecret settings and approval/storage mounts into **api only**.
Public source preflight uses the same pinned native image and helper socket as
the worker. The validator rejects a different API preflight image even when the
external descriptor is correctly rehashed. The API receives only the narrow
challenge secret file; it receives no provider identity or Docker socket.
The dedicated worker receives its
service JSON and narrowly scoped credential references. Ordinary worker,
migrator and frontend environment anchors are unchanged.

## First-start storage preparation

The release task creates only the verified environment parent directory, owned
by10001:10001 mode0700. The storage adapter creates each new leaf and ownership
marker. Do not create leaf directories manually, fabricate a marker, point at an
existing unowned store, or recursively change ownership of an unrelated path.

Run these commands only after the exact variables/files and parent path have
been verified by the release task. Example parent for staging:
`AC_XRAY_PARENT=/srv/authority-closers/sales-xray/staging`.

```sh
docker run --rm --init --network none --read-only \
  --user 10001:10001 --cap-drop ALL --security-opt no-new-privileges:true \
  --pids-limit 64 --cpus 0.5 --memory 128m \
  --env HOME=/tmp \
  --tmpfs /tmp:rw,noexec,nosuid,nodev,size=16m,uid=10001,gid=10001,mode=0700 \
  --mount "type=bind,src=$AC_XRAY_SERVICE_CONFIG,dst=/run/ac-sales-xray/service.json,readonly" \
  --mount "type=bind,src=$AC_XRAY_PARENT,dst=$AC_XRAY_PARENT" \
  "$AC_API_IMAGE" python -m ac_platform.conversation_intelligence.service \
  --config /run/ac-sales-xray/service.json --sha256 "$AC_XRAY_SERVICE_SHA256" \
  --prepare-storage
```

Success is `worker_storage_prepared`; this opens no DB/provider credentials and
makes no network request. Repeating it verifies existing owned roots. Only then
provision the separate native output tmpfs under scratch, size64m, mode0700,
UID/GID10001, nosuid/nodev/noexec. Its canonical path is
`$AC_XRAY_SCRATCH_ROOT/native-output-tmpfs`. The helper socket directory must be
root-owned, group10001, mode0750; the helper creates its socket mode0660.

## Native helper and smoke

Use the exact source helper artifact accompanying the native image. Verify its
manifest hashes before extracting into a versioned, root-owned, non-writable
helper directory. A trusted Python3.12 host runtime needs only its standard
library; the helper imports no API Settings, database client or provider SDK.
Its environment must contain no app/provider credentials. Supervise it separately
with the release task's existing process management. The fixed command is:

```sh
PYTHONPATH="$AC_XRAY_HELPER_ROOT/packages/python" python3 \
  "$AC_XRAY_HELPER_ROOT/scripts/native_runtime_helper.py" \
  --socket "$AC_XRAY_NATIVE_SOCKET_DIR/native.sock" \
  --workspace-root "$AC_XRAY_SCRATCH_ROOT" \
  --output-root "$AC_XRAY_SCRATCH_ROOT/native-output-tmpfs" \
  --image-ref "$AC_XRAY_NATIVE_IMAGE_REF" --peer-uid 10001 --peer-gid 10001
```

The helper alone has Docker access and permission to manage its fixed temporary
outputs. Run `test_hosted_native_linux.py` from that same artifact as10001:10001,
with the same socket/workspace/image and a fresh external receipt path. Verify
actual container confinement, output ownership, timeout/reap and current headroom.
Do not treat a successful `docker load`, configuration check or CI build as that
runtime proof.

### Persistent helper supervision

`infra/application/scripts/render-sales-xray-native.py` renders environment-specific
systemd service and mount units as JSON. It installs nothing and reads no secrets.
Render with the final application's versioned script path and the independently
verified native helper artifact, then retain and hash the exact rendered units.
The current verified helper reference is:

```text
helper source: 6204dc48df72ec133d30ce32e24dbddf3ea4993d
helper root: /srv/authority-closers/application/artifacts/sales-xray-native-6204dc48df72ec133d30ce32e24dbddf3ea4993d/helper
host Python: /usr/bin/python3 (3.12.3)
native manifest: sha256:fd29cbf1edc9f6b13ca9fcebc6903adee0fd70583c77b60bd1753816f7f57ef9
bound config: sha256:75e3b01d100534ce667a97822ab34216b09553f820b60c2f66a223b72b481866
native smoke receipt SHA256: 2ff3aa8733f69cb3f280bb87fec4afaad0292784b9427b09706c420f759fa1f4
```

Release Recovery verified that artifact and its two-run, wrong-image rejection
and helper cleanup receipt on the VPS. Reuse that proof; a later API source
release does not require rebuilding the unchanged native image. The six helper
files remain root-owned and their manifest hashes must still match.

The renderer binds each service to its environment's 64 MiB output mount and
fixed helper/image. Its root helper has only the native Docker bridge role;
provider identity directories are inaccessible and its process environment is
cleared before launch. The API and database/provider worker receive no Docker
socket. The helper drains for up to 800 seconds before forced termination.

Keep the socket directory's inode stable because the worker bind-mounts it.
Prestart accepts an absent socket or removes only a root-owned, mode0660 socket
whose connection is refused and whose inode has not changed. A live helper,
foreign node, symlink, writable parent or ambiguous error blocks duplicate start.
It never removes the socket directory or recursively deletes anything.

After owned storage preparation, the release operator installs the reviewed units
root-owned mode0644 through the infrastructure release process and verifies them
with `systemd-analyze verify`. Start the mount before the helper and the helper
before accepting jobs. Record `systemctl is-active`, effective unit properties,
mount capacity/options/ownership, and a supervised stop/restart with successful
worker reconnection. The earlier native receipt proves native execution; it does
not claim this newly rendered supervisor was installed or restart-tested.

The source-owned installer for this release is
`infra/application/scripts/install-sales-xray-native.py`. It consumes the exact
source-rendered `native-units.json`; it does not accept hand-authored unit text.
Execute the byte-verified immutable operator artifact for this leaf from
`operator-inputs/native-installer-reviewed`; do not copy this script into or
modify the frozen application release directory.
The installer also verifies the fixed empty system group
`ac-sales-xray-native` at GID `10001`, creating it through its pinned group
operator only when the group is absent. A different name or GID, or any group
member, blocks activation. Dry-run reports a missing group without creating it.
After the enabled activation descriptor and its digest have been reviewed, run
the following on the host for a dry verification, then repeat with `--start`
for the actual environment. Replace only the descriptor path, its SHA-256 and
the receipt filename with the reviewed values:

```text
sudo /usr/bin/python3 /srv/authority-closers/application/operator-inputs/native-installer-reviewed/install-sales-xray-native.py \
  --environment staging \
  --native-units /srv/authority-closers/application/operator-inputs/staging/native-units.json \
  --native-units-sha256 <reviewed-native-units-sha256> \
  --native-image-config-id sha256:75e3b01d100534ce667a97822ab34216b09553f820b60bd1753816f7f57ef9 \
  --receipt /srv/authority-closers/application/deployments/staging/native-unit-install-reviewed.json \
  --dry-run

sudo /usr/bin/python3 /srv/authority-closers/application/operator-inputs/native-installer-reviewed/install-sales-xray-native.py \
  --environment staging \
  --native-units /srv/authority-closers/application/operator-inputs/staging/native-units.json \
  --native-units-sha256 <reviewed-native-units-sha256> \
  --native-image-config-id sha256:75e3b01d100534ce667a97822ab34216b09553f820b60bd1753816f7f57ef9 \
  --receipt /srv/authority-closers/application/deployments/staging/native-unit-install-reviewed.json \
  --start
```

Use `production` and its separately reviewed descriptor/receipt for production.
The installer holds the shared application deployment lock, verifies the
renderer SHA and exact helper/image bindings, validates the staged units with
`systemd-analyze`, and atomically publishes root-owned mode-0644 unit files.
It starts the output mount before the helper, records active/enabled state and
fragment paths, and keeps prior unit bytes in a versioned rollback directory.
Any failure after publication restores those bytes and the prior systemd state;
the receipt contains hashes and status only.

## Coordinated API/worker activation and rollback

The canonical application installer owns activation, update and rollback. Its
`sales-xray-hosted.py` validator resolves the selected target release's immutable
capability policy, external activation descriptor and SHA-256 sidecar. The
descriptor binds the exact release, environment, overlay, native manifest, service
configuration, approval and individual mount references. Managed operations scope
is passed to validation only inside the existing secret-provider child process.
An absent policy denotes an older disabled release; an enabled policy with missing
or invalid activation input blocks deployment. Do not activate the overlay through
an ad hoc Compose command.

The installer holds ingress and stops ordinary API/worker intake before granting
the hosted worker its 960-second graceful drain. It checks that each existing
hosted container actually exited with status zero. A surviving or forced-killed
worker blocks database mutation and automatic restoration; the release stays on
hold for recovery. Every subsequent Compose call, including rollback, selects the
exact target release's hosted and filesystem-media settings. Ambient hosted
configuration cannot override these selected inputs.

Old quotes are refused with a prepare-again response; queued work is never
rewritten. Execute authenticated staging upload, report, playback, IDOR and deletion
checks, then promote the accepted immutable images through the same installer and
verify production. Preserve source/checkpoints and audit history. Numeric/official
scoring remains separately gated, and a successful build or helper startup alone
does not establish the learner journey.
