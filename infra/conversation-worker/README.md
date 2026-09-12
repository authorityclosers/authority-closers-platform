# Sales Xray offline worker sandbox candidate

Status: **authored; container build/run/confinement unproven**. No deployment or
Docker execution was performed while the shared release test slot was occupied.
This recipe runs the existing offline CLI and unchanged AudioAtlas kernel. It is
a one-recording process, with no API listener, database/session credentials, queue
connection, provider client, secret reference or external inference capability.
The domain worker outside the sandbox owns leases, authorization, reservation,
generation fencing, trusted object storage and final artifact verification.

## Source and dependency pin evidence

On2026-09-13 the public official
[Docker Hub library/python tag API](https://hub.docker.com/v2/repositories/library/python/tags/3.12-slim-bookworm)
returned index digest
`sha256:782412e85d0f0984994c290652577d4018aff08145c85b262bb63dc0c7522254`,
last_updated2026-09-01T05:08:41.402802Z. Its active Linux amd64 manifest was
`sha256:9c47360a2a0355e2da18516d0b1c2126ec22c195d2185e97347c9d98398c5bef`.
The Dockerfile pins that index in both stages; candidate validation targets
`linux/amd64` explicitly. No account credential was used to query the public API.

Debian's official package pages reported
[g++4:12.2.0-3](https://packages.debian.org/bookworm/g%2B%2B) and
[ffmpeg7:5.1.9-0+deb12u1](https://packages.debian.org/bookworm/ffmpeg).
Those top-level versions are pinned; transitive Debian packages are not a frozen
snapshot, so the resulting image digest, SBOM, FFmpeg build configuration/licenses
and vulnerability findings must be captured before release. A missing pinned
package should fail the build; never silently fall back to an unpinned version.
FFmpeg's runtime libraries are still required; no Python dependency beyond the
standard library is installed. Build tools remain in the build stage.

The native source hash is checked before compiling and by the Python build helper:
`40b8b05256986da5eb5d49c3b3cb48c52d511117ecf2e59d56849457cb12fae3`.
Only explicit offline Python modules, native source, license and provenance enter
the build context's COPY allowlist. The final image contains its own Linux build
and binary manifest, not the local Windows executable.

## Build candidate after the release owner grants the slot

Run from the AC checkout; this is an exact authoring recipe, not an executed receipt:

```sh
docker build --platform linux/amd64 --pull --file infra/conversation-worker/Dockerfile --tag ac-sales-xray-offline:candidate .
docker image inspect ac-sales-xray-offline:candidate --format '{{.Id}}'
```

Record the resulting immutable image ID/digest and use it below. Building can
contact official package registries; processing must have no network. Do not pass
build secrets, SSH agents, provider keys or application `.env` files.

## Mandatory host preparation

The coordinator supplies one canonical server job UUID, an already authorized
materialized source file, and an empty output directory, all private and outside
repositories. Do not mount the whole recording store, user home, host root,
Docker socket or any key directory. Source and output are different paths.

The source is a regular file <=128 MiB, accessible only to the worker's approved
UID mapping. The output is a separate **64 MiB quota-limited private filesystem**,
owned by mapped UID/GID10001 and mode0700. A host-mounted tmpfs with size64m,
nosuid,nodev,noexec can satisfy this temporary-output requirement; provision it
through the infrastructure owner, not by this image. An ordinary unbounded bind
directory does not satisfy the disk boundary. Tmpfs outputs are ephemeral: the
domain worker must validate and persist them before that mount is torn down.

Host cgroupv2 memory/CPU/pids enforcement, the default Docker seccomp profile,
user-namespace/rootless configuration and current patched runtime must be verified.
The1CPU/768 MiB envelope below is a candidate safety cap, not KVM4 capacity proof.
The16kHz profile is fixed here. A48kHz profile requires a separate measured resource
envelope; it must not silently expand these limits.

## Exact bounded execution recipe

The three path/image variables below are supplied by trusted orchestration, never
by request payloads. `AC_WORKER_IMAGE` must be the immutable verified image ID or
digest; `AC_CONTAINER_NAME` must be a fixed prefix plus the canonical server job UUID.
The host source and output permission/quota checks above are prerequisites.

```sh
set -eu
: "${AC_WORKER_IMAGE:?immutable approved image required}"
: "${AC_SOURCE_FILE:?private server-selected source file required}"
: "${AC_OUTPUT_DIR:?private quota-limited empty output filesystem required}"
: "${AC_CONTAINER_NAME:?canonical server job container name required}"
trap 'docker rm --force "$AC_CONTAINER_NAME" >/dev/null 2>&1 || true' EXIT HUP INT TERM
timeout --signal=TERM --kill-after=5s 750s docker run --rm --init \
  --name "$AC_CONTAINER_NAME" \
  --pull=never \
  --network=none \
  --read-only \
  --user=10001:10001 \
  --cap-drop=ALL \
  --security-opt=no-new-privileges:true \
  --pids-limit=32 \
  --memory=768m \
  --memory-swap=768m \
  --cpus=1 \
  --ulimit=nofile=64:64 \
  --ulimit=core=0:0 \
  --ulimit=fsize=268435456:268435456 \
  --log-driver=none \
  --tmpfs=/tmp:rw,noexec,nosuid,nodev,size=16m,mode=1777 \
  --tmpfs=/work:rw,noexec,nosuid,nodev,size=512m,uid=10001,gid=10001,mode=0700 \
  --mount "type=bind,source=$AC_SOURCE_FILE,target=/input/source.media,readonly,bind-propagation=rprivate" \
  --mount "type=bind,source=$AC_OUTPUT_DIR,target=/output,bind-propagation=rprivate" \
  --entrypoint=python \
  "$AC_WORKER_IMAGE" -c '
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path
if sys.flags.optimize:
    raise RuntimeError("Optimized Python is not allowed for sandbox preflight")
os.umask(0o077)
assert os.getuid() == 10001 and os.getgid() == 10001
status = dict(line.split(":", 1) for line in Path("/proc/self/status").read_text().splitlines())
assert all(int(status[name].strip(), 16) == 0 for name in ("CapEff", "CapPrm", "CapBnd", "CapAmb"))
assert status["NoNewPrivs"].strip() == "1" and status["Seccomp"].strip() == "2"
assert set(os.listdir("/sys/class/net")) == {"lo"}
cgroup = Path("/sys/fs/cgroup")
assert 0 < int((cgroup / "memory.max").read_text()) <= 805306368
assert int((cgroup / "memory.swap.max").read_text()) == 0
assert 0 < int((cgroup / "pids.max").read_text()) <= 32
quota, period = (cgroup / "cpu.max").read_text().split()
assert quota != "max" and 0 < int(quota) <= int(period)
mounts = {}
for line in Path("/proc/self/mountinfo").read_text().splitlines():
    fields = line.split()
    mounts[fields[4]] = (set(fields[5].split(",")), fields[fields.index("-") + 1])
assert "ro" in mounts["/"][0] and "ro" in mounts["/input/source.media"][0]
for mount, size in (("/work", 536870912), ("/tmp", 16777216)):
    assert mounts[mount][1] == "tmpfs"
    assert {"rw", "nosuid", "nodev", "noexec"} <= mounts[mount][0]
    filesystem = os.statvfs(mount)
    assert filesystem.f_frsize * filesystem.f_blocks <= size
filesystem = os.statvfs("/output")
assert filesystem.f_frsize * filesystem.f_blocks <= 67108864
assert stat.S_IMODE(os.stat("/output").st_mode) == 0o700
subprocess.run([sys.executable, "-m", "ac_platform.conversation_intelligence", "inspect",
                "/input/source.media", "--out", "/work/checkpoint", "--rate", "16000"],
               check=True, timeout=720)
published = Path("/output/checkpoint")
published.mkdir(mode=0o700)
for name in ("features.aaf", "checkpoint.json"):
    shutil.copyfile(Path("/work/checkpoint") / name, published / name)
'
```

The fixed supervisor also checks actual nonroot identity, capabilities,
NoNewPrivs/seccomp, interfaces, cgroupv2 limits, read-only mounts and filesystem
capacity before invoking the unchanged CLI. Missing kernel interfaces or a
weaker effective configuration fail before audio processing. These checks have
not yet been executed inside a container.

The scratch snapshot, decoded PCM and native raw arrays stay within the bounded
`/work` tmpfs. Only completed feature/checkpoint files are copied into the private
output filesystem, and its `checkpoint` child must not already exist. A failed
copy can leave partial output; only exit0 plus independent source/feature hash
and checkpoint validation permits domain publication. The outer deadline kills
the named container even if the CLI or decoder stops responding. The default
Docker seccomp policy stays enabled; never use privileged mode, host namespaces,
added capabilities, Docker socket mounts or `seccomp=unconfined`.

Network isolation, resource limits and tmpfs semantics are documented by
[Docker's run reference](https://docs.docker.com/engine/containers/run/),
[none network driver](https://docs.docker.com/engine/network/drivers/none/),
[tmpfs reference](https://docs.docker.com/engine/storage/tmpfs/) and
[default seccomp profile](https://docs.docker.com/engine/security/seccomp/).
Docker flags are runtime controls; this Dockerfile alone does not enforce them.

## Required execution receipts before activation

Capture the exact image ID, source and native binary SHA, installed package/SBOM
receipt, host/runtime versions and the actual effective HostConfig. Run synthetic
tone/phase/tail/nonfinite/codec regression fixtures in the container. Demonstrate
nonroot identity, zero effective capabilities, NoNewPrivs, active seccomp, absent
external network interfaces, read-only source/root, blocked outside writes,
effective cgroup memory/CPU/pids limits, tmpfs/output quota exhaustion and complete
process cleanup at timeout. Record actual peak whole-process/cgroup resources.

Then repeat with a recording-specific approved local source, verify source/feature
digests on both sides, and verify deletion of materialization/output/scratch after
the generation fence and trusted storage handoff. Container startup, isolation,
resource exhaustion, kill/reap, output preservation, Linux permission behavior,
and KVM4 headroom have **not been tested by this recipe authoring**. Static contract
tests only detect unsafe recipe changes; they are not container security proof.
Provider processing, public storage, staging and production remain separate gates.

## Static validation performed here

2026-09-13:31 static policy and mocked preflight checks passed, together with28
Windows storage regressions:59passed, zero skips,1.89seconds. The mocks demonstrate
that weaker UID/capabilities/privilege/seccomp/network/cgroup/mount/quota settings
are rejected before CLI invocation. They do not demonstrate those settings on
Docker or Linux. Ruff passed. Strict mypy targeting Linux passed for the signal
and storage modules; Linux runtime behavior remains unexecuted.

Machine receipt:
`D:/Projects/authority-closers-release-transfer/2026-09-13-sales-xray/receipts/storage-sandbox-final-junit.xml`.
Reproduction command from the AC checkout:

```powershell
$env:PYTHONPATH = 'D:/Projects/authority-closers-platform-sales-xray/packages/python'
& 'D:/Projects/authority-closers-platform/.venv/Scripts/python.exe' -m pytest tests/unit/conversation_intelligence/test_worker_sandbox_contract.py tests/unit/conversation_intelligence/test_storage.py -q --tb=short --basetemp='D:/Projects/authority-closers-release-transfer/2026-09-13-sales-xray/receipts/storage-sandbox-final-temp' --junitxml='D:/Projects/authority-closers-release-transfer/2026-09-13-sales-xray/receipts/storage-sandbox-final-junit.xml'
& 'D:/Projects/authority-closers-platform/.venv/Scripts/python.exe' -m mypy --follow-imports=silent --platform linux packages/python/ac_platform/conversation_intelligence/signals.py packages/python/ac_platform/conversation_intelligence/storage.py
```
