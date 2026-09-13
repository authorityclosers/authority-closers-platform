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
verified `sha256:...` image ID from the loaded native artifact.

For production, replace both the environment and every staging path with their
separate production counterpart; use its own approved bundle and DB credential.
Neither environment adopts or copies private test audio from a local directory.

The service template contains the actual approved Infisical project/path names,
but no token or provider key. Its credential_ref values must exactly match the
approved stages. Initial external identity directories are:

- `/etc/authority-closers/secrets/sales-xray/identities/elevenlabs`
- `/etc/authority-closers/secrets/sales-xray/identities/groq`

Each directory contains only its own token, UID10001, mode0400. Their initial
24-hour expiry requires external refresh before sustained operation. The worker
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
AC_XRAY_INFISICAL_BINARY=/usr/local/bin/infisical
```

`compose.hosted.yaml` merges the five AC_SALES_XRAY_* nonsecret settings and
approval/storage mounts into **api only**. The dedicated worker receives its
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
  --image-ref "$AC_XRAY_NATIVE_IMAGE_ID" --peer-uid 10001 --peer-gid 10001
```

The helper alone has Docker access and permission to manage its fixed temporary
outputs. Run `test_hosted_native_linux.py` from that same artifact as10001:10001,
with the same socket/workspace/image and a fresh external receipt path. Verify
actual container confinement, output ownership, timeout/reap and current headroom.
Do not treat a successful `docker load`, configuration check or CI build as that
runtime proof.

## Coordinated API/worker activation and rollback

Stop old intake and drain accepted48k jobs before switching both API and dedicated
worker to this16k release. Old quotes are refused with a prepare-again response;
queued work is never rewritten. Add this overlay to the release task's complete
existing Compose invocation, including its real environment and other overlays:

```sh
docker compose -f infra/application/compose.yaml \
  -f infra/conversation-worker/compose.hosted.yaml \
  --profile sales-xray-hosted config --quiet
docker compose -f infra/application/compose.yaml \
  -f infra/conversation-worker/compose.hosted.yaml \
  --profile sales-xray-hosted up -d --no-build api sales-xray-worker
```

Execute authenticated staging upload, report, playback, IDOR and deletion checks;
then canary/rollback and promotion of the same immutable images, followed by
production checks. Stop/drain the dedicated worker before rolling back its
configuration/image. Remove the API activation overlay or explicitly disable its
Sales Xray setting. Preserve source/checkpoints and audit history. No manual SQL
recovery and no localhost demonstration-service exposure are part of this recipe.
