# Sales Xray hosted native runtime adapter

This slice adds the concrete boundary between the durable conversation worker and
the reviewed AudioAtlas candidate image. The worker uses
`SocketNativeRuntime`; it does not import a Docker client, join a Docker group or
receive provider credentials. A separately supervised helper runs
`native_runtime_helper.py`, which owns the Docker CLI and constructs
`DockerNativeRuntime`.

## Coordinator contract

The hosted composition supplies:

```python
SocketNativeRuntime(
    socket_path=Path("/run/ac-sales-xray/native.sock"),
    workspace_root=private_scratch_root,
    expected_image_ref="registry.example/ac-sales-xray-native@sha256:<approved-digest>",
)
```

The durable worker calls:

```python
runtime.inspect(
    source_path,
    output_path,
    job_id=canonical_job_uuid,
    rate=16000,
)
```

The request is a bounded canonical JSON frame over a Unix stream socket. It carries
only server-selected source/output paths, source digest/size, job UUID, expected
image reference and the fixed 16 kHz profile. Audio and result bytes stay in the
private workspace. The response is an acknowledgement; the client reads and
validates the checkpoint and feature object from the private output path.

The helper is started with an explicitly configured peer UID and private workspace:

```sh
python scripts/native_runtime_helper.py \
  --socket /run/ac-sales-xray/native.sock \
  --workspace-root /srv/authority-closers/conversation-scratch \
  --output-root /srv/authority-closers/conversation-scratch/native-output-tmpfs \
  --image-ref registry.example/ac-sales-xray-native@sha256:<approved-digest> \
  --peer-uid <worker-uid> \
  --peer-gid <worker-gid>
```

The helper accepts one request at a time, verifies the Unix peer credential and
exact request shape, rechecks path scope and source digest, invokes the fixed
candidate recipe, and returns only a stable success/error code. The
`--output-root` directory must already be a private mode-0700 filesystem whose
total capacity is at most 64 MiB; the helper stages there and copies only the
independently validated result to the worker output path. The host supervisor
must provision the socket parent, private source/output filesystem permissions,
cgroup limits and the Docker runtime.

The supported topology for this slice is a dedicated host supervisor identity
with access explicitly scoped to the private scratch workspace. This is separate
from the database worker identity, which receives only the Unix socket; the
helper binds that socket as mode `0660` with the configured peer group. The
decoding process inside the container remains UID/GID `10001:10001`; the
supervisor must capture a permission receipt showing that its host bind mount
can read the worker's mode-0600 source snapshot and collect the mode-0700
output. A rootless supervisor is not activation-ready until its UID/GID mapping
proves those same permissions; this adapter does not chmod, chown or broaden
source access to make an unproven mapping work.

The candidate image remains pinned and database/provider-free. Its execution
includes `--network=none`, a read-only root and source bind, non-root UID
10001:10001, dropped capabilities, NoNewPrivs, the default seccomp profile, bounded
CPU/memory/pids, noexec tmpfs scratch, a quota-limited output bind and forced
container cleanup. The adapter refuses mutable image tags and never accepts
`--env-file`, arbitrary commands, provider keys, Docker socket mounts or request
supplied runtime flags.

## Source and C1 provenance

The hosted worker keeps the existing storage fence and source object validation.
It materializes one verified source snapshot under the scratch root, sends only
that path to the helper, and publishes a feature object only after the helper
returns and the adapter validates:

- exact source SHA-256 and byte count;
- checkpoint schema and C1 stage;
- canonical checkpoint JSON with duplicate/non-finite JSON rejection;
- 16 kHz acoustics and decoded-track timebase;
- feature SHA-256, bounded feature size and complete AudioAtlas row validation.

The hosted C1 cache key explicitly contains `decode_rate: 16000`. The existing
local worker remains `environment="local"|"test"` with its established 48 kHz
profile. A hosted worker must use `environment="staging"|"production"` and an
injected native adapter; it cannot claim hosted execution by passing
`environment="local"`.

## Proof boundary

Unit tests exercise request framing, peer-side contract checks, fixed sandbox
flags, source/output separation, checkpoint canonicality, source/hash/rate
binding, feature validation and failure cleanup with synthetic data. They do not
claim that Docker, Linux namespaces, cgroups, UID mapping, rootless mode or KVM4
capacity has been exercised on this Windows host. The release owner must capture
the actual image, helper, host permission, confinement, resource, timeout/reap,
synthetic fixture and deletion receipts before staging or production activation.
No provider call, database connection or deployment is performed by this adapter.
