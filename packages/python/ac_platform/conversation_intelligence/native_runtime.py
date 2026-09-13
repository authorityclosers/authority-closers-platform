"""Hosted native C1 execution behind the reviewed container boundary.

The application worker owns authorization, the storage fence and publication.  This
module only owns the narrow process boundary around the database/provider-free
AudioAtlas candidate image.  It intentionally accepts a server-selected source
path and output path, never a request filename or an image chosen by a caller.

The candidate image's 16 kHz contract is explicit here.  The local worker keeps its
existing 48 kHz profile; the hosted adapter cannot silently select that profile.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import socket
import stat
import struct
import subprocess  # noqa: S404 -- fixed argv, no shell, bounded container lifetime
import tempfile
from collections.abc import Callable, Mapping, Sequence
from contextlib import suppress
from pathlib import Path
from typing import Any, Literal, Protocol
from uuid import UUID

from ac_platform.conversation_intelligence.signals import iter_features

HOSTED_C1_RATE: Literal[16000] = 16000
MAX_SOURCE_BYTES = 128 * 1024 * 1024
MAX_OUTPUT_BYTES = 64 * 1024 * 1024
MAX_CHECKPOINT_BYTES = 2 * 1024 * 1024
MAX_RUNTIME_SECONDS = 750.0
NATIVE_RUNTIME_SCHEMA = "ac.sales-xray.native-runtime/1"
MAX_REQUEST_BYTES = 16 * 1024
MAX_RESPONSE_BYTES = 4 * 1024
NATIVE_UID = 10001
NATIVE_GID = 10001
_IMAGE_REF = re.compile(r"^(?:[A-Za-z0-9._/-]+@)?sha256:[0-9a-f]{64}$")
_CONTAINER_PREFIX = re.compile(r"^[a-z][a-z0-9-]{0,40}$")
_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_CHECKPOINT_FILES = frozenset({"checkpoint.json", "features.aaf"})


class NativeRuntimeError(ValueError):
    """Stable, content-free failure code from the hosted native boundary."""

    _CODES = frozenset(
        {
            "native_runtime_configuration_invalid",
            "native_runtime_image_not_immutable",
            "native_runtime_source_invalid",
            "native_runtime_output_invalid",
            "native_runtime_output_exists",
            "native_runtime_docker_unavailable",
            "native_runtime_timeout",
            "native_runtime_failed",
            "native_runtime_container_cleanup_failed",
            "native_runtime_checkpoint_invalid",
            "native_runtime_checkpoint_not_canonical",
            "native_runtime_source_binding_mismatch",
            "native_runtime_rate_mismatch",
            "native_runtime_feature_invalid",
        }
    )

    def __init__(self, code: str) -> None:
        self.code = code if code in self._CODES else "native_runtime_failed"
        super().__init__(self.code)


class NativeRuntime(Protocol):
    """Synchronous adapter used from the worker's fenced executor thread."""

    def inspect(
        self,
        source: Path,
        outdir: Path,
        *,
        job_id: UUID,
        rate: Literal[16000],
    ) -> dict[str, Any]:
        """Create one immutable C1 output directory and return its payload."""


# This is intentionally the same bounded preflight as the reviewed candidate
# README. It is kept as a fixed program rather than accepting a caller command or
# arbitrary environment. The only subprocess it starts is the offline CLI.
_CONTAINER_PROGRAM = r"""import os
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
"""


def _reject_json_constant(_: str) -> None:
    raise ValueError("non-finite JSON number")


def _object_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _canonical_json(value: Mapping[str, Any]) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def _regular(path: Path, *, max_bytes: int | None = None) -> os.stat_result:
    try:
        info = path.lstat()
    except OSError:
        raise NativeRuntimeError("native_runtime_output_invalid") from None
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise NativeRuntimeError("native_runtime_output_invalid")
    if max_bytes is not None and not 0 < info.st_size <= max_bytes:
        raise NativeRuntimeError("native_runtime_output_invalid")
    return info


def _directory(path: Path) -> None:
    try:
        info = path.lstat()
    except OSError:
        raise NativeRuntimeError("native_runtime_output_invalid") from None
    # POSIX directories normally have one link for themselves and one for each
    # child namespace. Only regular files are required to have a unique link.
    if not stat.S_ISDIR(info.st_mode):
        raise NativeRuntimeError("native_runtime_output_invalid")


def _path_is_safe(path: Path, root: Path | None) -> bool:
    if not path.is_absolute() or any(part == ".." for part in path.parts):
        return False
    try:
        if any(parent.is_symlink() for parent in (path, *path.parents)):
            return False
        if root is not None and not path.is_relative_to(root):
            return False
    except OSError:
        return False
    return True


Runner = Callable[[Sequence[str], str, float], None]
Exchange = Callable[[bytes], bytes]


def _safe_environment() -> dict[str, str]:
    # The helper needs only executable lookup and temporary directory behavior.
    # In particular, provider keys, Docker config and application settings never
    # cross the native child boundary.
    return {
        name: os.environ[name]
        for name in ("PATH", "SystemRoot", "WINDIR", "TEMP", "TMP", "TMPDIR")
        if name in os.environ
    }


def _validate_request_paths(source: Path, outdir: Path, workspace_root: Path) -> tuple[str, int]:
    if not isinstance(source, Path) or not isinstance(outdir, Path):
        raise NativeRuntimeError("native_runtime_configuration_invalid")
    if not _path_is_safe(source, workspace_root) or not _path_is_safe(outdir, workspace_root):
        raise NativeRuntimeError("native_runtime_source_invalid")
    try:
        source_info = source.lstat()
    except OSError:
        raise NativeRuntimeError("native_runtime_source_invalid") from None
    if (
        not stat.S_ISREG(source_info.st_mode)
        or source_info.st_nlink != 1
        or not 0 < source_info.st_size <= MAX_SOURCE_BYTES
    ):
        raise NativeRuntimeError("native_runtime_source_invalid")
    if outdir.exists() or outdir.is_symlink():
        raise NativeRuntimeError("native_runtime_output_exists")
    try:
        _directory(outdir.parent)
    except NativeRuntimeError:
        raise NativeRuntimeError("native_runtime_output_invalid") from None
    return _file_sha256(source), source_info.st_size


def _recv_exact(channel: socket.socket, length: int) -> bytes:
    result = bytearray()
    while len(result) < length:
        block = channel.recv(length - len(result))
        if not block:
            raise NativeRuntimeError("native_runtime_failed")
        result.extend(block)
    return bytes(result)


class SocketNativeRuntime:
    """Coordinator-side client for the separately supervised native helper.

    The database/credential worker uses this client and never invokes Docker. The
    helper process owns the Docker CLI, image and container lifecycle. Requests
    contain only server-selected paths, an opaque job UUID, the pinned image
    reference and the explicit 16 kHz profile; audio and checkpoint bytes stay on
    the private workspace filesystem.
    """

    def __init__(
        self,
        socket_path: Path,
        *,
        workspace_root: Path,
        expected_image_ref: str,
        timeout_seconds: float = MAX_RUNTIME_SECONDS,
        exchange: Exchange | None = None,
    ) -> None:
        if (
            not isinstance(socket_path, Path)
            or not socket_path.is_absolute()
            or len(os.fsencode(socket_path)) > 107
            or any(parent.is_symlink() for parent in (socket_path, *socket_path.parents))
            or not isinstance(workspace_root, Path)
            or not workspace_root.is_absolute()
            or workspace_root.is_symlink()
            or _IMAGE_REF.fullmatch(expected_image_ref) is None
            or type(timeout_seconds) not in {int, float}
            or not 1 <= timeout_seconds <= MAX_RUNTIME_SECONDS
            or (exchange is not None and not callable(exchange))
        ):
            raise NativeRuntimeError("native_runtime_configuration_invalid")
        self.socket_path = socket_path
        self.workspace_root = workspace_root
        self.expected_image_ref = expected_image_ref
        self.timeout_seconds = float(timeout_seconds)
        self._exchange = exchange

    def inspect(
        self,
        source: Path,
        outdir: Path,
        *,
        job_id: UUID,
        rate: Literal[16000],
    ) -> dict[str, Any]:
        source_sha256, source_bytes = _validate_request_paths(source, outdir, self.workspace_root)
        if type(rate) is not int or rate != HOSTED_C1_RATE:
            raise NativeRuntimeError("native_runtime_rate_mismatch")
        if type(job_id) is not UUID:
            raise NativeRuntimeError("native_runtime_configuration_invalid")
        request = {
            "schema": NATIVE_RUNTIME_SCHEMA,
            "operation": "inspect",
            "source": str(source),
            "outdir": str(outdir),
            "job_id": str(job_id),
            "image_ref": self.expected_image_ref,
            "rate": HOSTED_C1_RATE,
            "source_sha256": source_sha256,
            "source_bytes": source_bytes,
        }
        try:
            response = self._exchange_frame(request)
        except NativeRuntimeError:
            raise
        except (OSError, ValueError, TypeError, TimeoutError):
            raise NativeRuntimeError("native_runtime_failed") from None
        if response.get("schema") != NATIVE_RUNTIME_SCHEMA:
            raise NativeRuntimeError("native_runtime_failed")
        if response.get("ok") is not True:
            error = response.get("error")
            if not isinstance(error, str) or error not in NativeRuntimeError._CODES:
                error = "native_runtime_failed"
            raise NativeRuntimeError(error)
        try:
            payload = DockerNativeRuntime._validate_output(
                outdir, source_sha256=source_sha256, source_bytes=source_bytes
            )
        except NativeRuntimeError:
            raise
        except (OSError, ValueError, TypeError):
            raise NativeRuntimeError("native_runtime_checkpoint_invalid") from None
        return payload

    def _exchange_frame(self, request: Mapping[str, Any]) -> dict[str, Any]:
        raw = _canonical_json(request)
        if len(raw) > MAX_REQUEST_BYTES:
            raise NativeRuntimeError("native_runtime_configuration_invalid")
        frame = struct.pack(">I", len(raw)) + raw
        response_raw = (
            self._exchange(frame) if self._exchange is not None else self._socket_exchange(frame)
        )
        if len(response_raw) > MAX_RESPONSE_BYTES:
            raise NativeRuntimeError("native_runtime_failed")
        try:
            response = json.loads(
                response_raw.decode("utf-8"),
                object_pairs_hook=_object_pairs,
                parse_constant=_reject_json_constant,
            )
        except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError):
            raise NativeRuntimeError("native_runtime_failed") from None
        if not isinstance(response, dict):
            raise NativeRuntimeError("native_runtime_failed")
        return response

    def _socket_exchange(self, frame: bytes) -> bytes:
        if not hasattr(socket, "AF_UNIX"):
            raise NativeRuntimeError("native_runtime_configuration_invalid")
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as channel:
                channel.settimeout(self.timeout_seconds)
                channel.connect(str(self.socket_path))
                channel.sendall(frame)
                header = _recv_exact(channel, 4)
                length = struct.unpack(">I", header)[0]
                if not 0 < length <= MAX_RESPONSE_BYTES:
                    raise NativeRuntimeError("native_runtime_failed")
                return _recv_exact(channel, length)
        except NativeRuntimeError:
            raise
        except (OSError, TimeoutError):
            raise NativeRuntimeError("native_runtime_failed") from None


class DockerNativeRuntime:
    """Invoke the immutable AudioAtlas image using the reviewed fixed envelope.

    The runner argument exists only for unit tests and deterministic local
    contract tests. Production composition leaves it unset, which uses the
    Docker CLI with no shell, no environment file and no provider or database
    credentials.
    """

    def __init__(
        self,
        image_ref: str,
        *,
        workspace_root: Path,
        output_root: Path | None = None,
        native_owner: tuple[int, int] | None = None,
        docker_executable: str | Path = "docker",
        container_prefix: str = "ac-sales-xray-native",
        timeout_seconds: float = MAX_RUNTIME_SECONDS,
        runner: Runner | None = None,
    ) -> None:
        if (
            not isinstance(image_ref, str)
            or _IMAGE_REF.fullmatch(image_ref) is None
            or not isinstance(workspace_root, Path)
            or not workspace_root.is_absolute()
            or workspace_root.is_symlink()
            or (
                output_root is not None
                and (
                    not isinstance(output_root, Path)
                    or not output_root.is_absolute()
                    or output_root.is_symlink()
                )
            )
            or (
                native_owner is not None
                and (
                    not isinstance(native_owner, tuple)
                    or len(native_owner) != 2
                    or any(type(value) is not int or value < 0 for value in native_owner)
                )
            )
            or not _CONTAINER_PREFIX.fullmatch(container_prefix)
            or type(timeout_seconds) not in {int, float}
            or not 1 <= timeout_seconds <= MAX_RUNTIME_SECONDS
            or not isinstance(docker_executable, (str, Path))
            or not str(docker_executable)
            or (runner is not None and not callable(runner))
        ):
            raise NativeRuntimeError("native_runtime_configuration_invalid")
        self.image_ref = image_ref
        self.workspace_root = workspace_root
        self.output_root = output_root
        self.native_owner = native_owner
        self.docker_executable = str(docker_executable)
        self.container_prefix = container_prefix
        self.timeout_seconds = float(timeout_seconds)
        self._runner = runner

    def inspect(
        self,
        source: Path,
        outdir: Path,
        *,
        job_id: UUID,
        rate: Literal[16000],
    ) -> dict[str, Any]:
        if type(rate) is not int or rate != HOSTED_C1_RATE:
            raise NativeRuntimeError("native_runtime_rate_mismatch")
        if type(job_id) is not UUID:
            raise NativeRuntimeError("native_runtime_configuration_invalid")
        if not isinstance(source, Path) or not isinstance(outdir, Path):
            raise NativeRuntimeError("native_runtime_configuration_invalid")
        if not _path_is_safe(source, self.workspace_root) or not _path_is_safe(
            outdir, self.workspace_root
        ):
            raise NativeRuntimeError("native_runtime_source_invalid")
        if self.output_root is not None and not _path_is_safe(
            self.output_root, self.workspace_root
        ):
            raise NativeRuntimeError("native_runtime_configuration_invalid")
        try:
            source_info = source.lstat()
        except OSError:
            raise NativeRuntimeError("native_runtime_source_invalid") from None
        if (
            not stat.S_ISREG(source_info.st_mode)
            or source_info.st_nlink != 1
            or not 0 < source_info.st_size <= MAX_SOURCE_BYTES
        ):
            raise NativeRuntimeError("native_runtime_source_invalid")
        if outdir.exists() or outdir.is_symlink():
            raise NativeRuntimeError("native_runtime_output_exists")
        try:
            _directory(outdir.parent)
        except NativeRuntimeError:
            raise NativeRuntimeError("native_runtime_output_invalid") from None
        if self.output_root is not None:
            self._validate_output_root(self.output_root, expected_owner=self.native_owner)

        source_sha256 = _file_sha256(source)

        staging: Path | None = None
        container_name = f"{self.container_prefix}-{job_id.hex}"
        try:
            staging_parent = self.output_root or outdir.parent
            staging = Path(tempfile.mkdtemp(prefix=".native-output-", dir=str(staging_parent)))
            self._restrict_directory(staging)
            command = self._command(source, staging, container_name)
            self._invoke(command, container_name)
            try:
                current_source = source.lstat()
                unchanged = (
                    stat.S_ISREG(current_source.st_mode)
                    and current_source.st_nlink == 1
                    and current_source.st_size == source_info.st_size
                    and _file_sha256(source) == source_sha256
                )
            except OSError:
                unchanged = False
            if not unchanged:
                raise NativeRuntimeError("native_runtime_source_binding_mismatch")
            payload = self._validate_output(
                staging / "checkpoint",
                source_sha256=source_sha256,
                source_bytes=source_info.st_size,
            )
            self._publish_output(staging / "checkpoint", outdir)
            return payload
        except NativeRuntimeError:
            raise
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            raise NativeRuntimeError("native_runtime_output_invalid") from None
        finally:
            if staging is not None:
                shutil.rmtree(staging, ignore_errors=True)

    @staticmethod
    def _validate_output_root(
        output_root: Path, *, expected_owner: tuple[int, int] | None = None
    ) -> None:
        try:
            info = output_root.lstat()
            usage = os.statvfs(output_root)  # type: ignore[attr-defined,unused-ignore]
        except OSError:
            raise NativeRuntimeError("native_runtime_configuration_invalid") from None
        if (
            not stat.S_ISDIR(info.st_mode)
            or info.st_nlink < 1
            or stat.S_IMODE(info.st_mode) != 0o700
            or usage.f_frsize * usage.f_blocks > MAX_OUTPUT_BYTES
            or (
                expected_owner is not None
                and (
                    getattr(info, "st_uid", None) != expected_owner[0]
                    or getattr(info, "st_gid", None) != expected_owner[1]
                )
            )
        ):
            raise NativeRuntimeError("native_runtime_configuration_invalid")

    def _restrict_directory(self, path: Path) -> None:
        try:
            os.chmod(path, 0o700)
            if self.native_owner is not None and hasattr(os, "chown"):
                os.chown(path, *self.native_owner)
        except OSError:
            raise NativeRuntimeError("native_runtime_output_invalid") from None

    def _restrict_file(self, path: Path) -> None:
        try:
            os.chmod(path, 0o600)
            if self.native_owner is not None and hasattr(os, "chown"):
                os.chown(path, *self.native_owner)
        except OSError:
            raise NativeRuntimeError("native_runtime_output_invalid") from None

    def _publish_output(self, checkpoint: Path, outdir: Path) -> None:
        if outdir.exists() or outdir.is_symlink():
            raise NativeRuntimeError("native_runtime_output_exists")
        publish: Path | None = None
        try:
            publish = Path(tempfile.mkdtemp(prefix=".native-publish-", dir=str(outdir.parent)))
            self._restrict_directory(publish)
            for name in ("features.aaf", "checkpoint.json"):
                shutil.copyfile(checkpoint / name, publish / name)
                self._restrict_file(publish / name)
            try:
                publish.replace(outdir)
            except FileExistsError:
                raise NativeRuntimeError("native_runtime_output_exists") from None
            publish = None
        except NativeRuntimeError:
            raise
        except (OSError, ValueError, TypeError):
            raise NativeRuntimeError("native_runtime_output_invalid") from None
        finally:
            if publish is not None:
                shutil.rmtree(publish, ignore_errors=True)

    def _command(self, source: Path, staging: Path, container_name: str) -> tuple[str, ...]:
        # Every argument is fixed except the three trusted coordinator paths, the
        # canonical job-derived name and the immutable image digest.
        return (
            self.docker_executable,
            "run",
            "--rm",
            "--init",
            "--name",
            container_name,
            "--pull=never",
            "--network=none",
            "--read-only",
            "--user=10001:10001",
            "--cap-drop=ALL",
            "--security-opt=no-new-privileges:true",
            "--pids-limit=32",
            "--memory=768m",
            "--memory-swap=768m",
            "--cpus=1",
            "--ulimit",
            "nofile=64:64",
            "--ulimit",
            "core=0:0",
            "--ulimit",
            "fsize=268435456:268435456",
            "--log-driver=none",
            "--tmpfs=/tmp:rw,noexec,nosuid,nodev,size=16m,mode=1777",
            "--tmpfs=/work:rw,noexec,nosuid,nodev,size=512m,uid=10001,gid=10001,mode=0700",
            "--mount",
            f"type=bind,source={source},target=/input/source.media,readonly,bind-propagation=rprivate",
            "--mount",
            f"type=bind,source={staging},target=/output,bind-propagation=rprivate",
            "--entrypoint=python",
            self.image_ref,
            "-c",
            _CONTAINER_PROGRAM,
        )

    def _invoke(self, command: Sequence[str], container_name: str) -> None:
        if self._runner is not None:
            self._runner(command, container_name, self.timeout_seconds)
            return
        environment = _safe_environment()
        try:
            process = subprocess.Popen(  # noqa: S603 -- fixed argv, no shell
                list(command),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                env=environment,
                creationflags=int(getattr(subprocess, "CREATE_NO_WINDOW", 0)),
            )
        except OSError:
            raise NativeRuntimeError("native_runtime_docker_unavailable") from None
        try:
            try:
                process.wait(timeout=self.timeout_seconds)
            except subprocess.TimeoutExpired:
                process.kill()
                with suppress(OSError, subprocess.TimeoutExpired):
                    process.wait(timeout=5)
                raise NativeRuntimeError("native_runtime_timeout") from None
            if process.returncode != 0:
                raise NativeRuntimeError("native_runtime_failed")
        finally:
            self._remove_container(container_name)

    def _remove_container(self, container_name: str) -> None:
        try:
            subprocess.run(  # noqa: S603 -- fixed argv, no shell
                [self.docker_executable, "rm", "--force", container_name],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
                timeout=10,
                env=_safe_environment(),
                creationflags=int(getattr(subprocess, "CREATE_NO_WINDOW", 0)),
            )
            remaining = subprocess.run(  # noqa: S603 -- one fixed container name, no shell
                [
                    self.docker_executable,
                    "container",
                    "ls",
                    "--all",
                    "--filter",
                    f"name={container_name}",
                    "--format",
                    "{{.ID}}",
                ],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                check=False,
                timeout=10,
                env=_safe_environment(),
                creationflags=int(getattr(subprocess, "CREATE_NO_WINDOW", 0)),
            )
            if remaining.returncode != 0 or remaining.stdout.strip():
                raise NativeRuntimeError("native_runtime_container_cleanup_failed")
        except (OSError, subprocess.TimeoutExpired):
            raise NativeRuntimeError("native_runtime_container_cleanup_failed") from None

    @staticmethod
    def _validate_output(
        checkpoint: Path, *, source_sha256: str, source_bytes: int
    ) -> dict[str, Any]:
        try:
            _directory(checkpoint)
            names = {entry.name for entry in checkpoint.iterdir()}
        except OSError:
            raise NativeRuntimeError("native_runtime_checkpoint_invalid") from None
        if names != _CHECKPOINT_FILES:
            raise NativeRuntimeError("native_runtime_checkpoint_invalid")
        checkpoint_json = checkpoint / "checkpoint.json"
        features = checkpoint / "features.aaf"
        _regular(checkpoint_json, max_bytes=MAX_CHECKPOINT_BYTES)
        feature_info = _regular(features, max_bytes=MAX_OUTPUT_BYTES)
        try:
            if feature_info.st_size + checkpoint_json.lstat().st_size > MAX_OUTPUT_BYTES:
                raise NativeRuntimeError("native_runtime_output_invalid")
        except OSError:
            raise NativeRuntimeError("native_runtime_output_invalid") from None
        try:
            raw = checkpoint_json.read_bytes()
            if not raw.endswith(b"\n"):
                raise NativeRuntimeError("native_runtime_checkpoint_not_canonical")
            payload = json.loads(
                raw[:-1].decode("utf-8"),
                object_pairs_hook=_object_pairs,
                parse_constant=_reject_json_constant,
            )
        except NativeRuntimeError:
            raise
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError):
            raise NativeRuntimeError("native_runtime_checkpoint_invalid") from None
        if not isinstance(payload, dict) or _canonical_json(payload) != raw[:-1]:
            raise NativeRuntimeError("native_runtime_checkpoint_not_canonical")
        acoustics = payload.get("acoustics")
        timebase = payload.get("timebase")
        feature_sha256 = payload.get("feature_sha256")
        if (
            payload.get("schema") != "ac.sales-xray.signal-checkpoint/1"
            or payload.get("stage") != "C1"
            or payload.get("source_sha256") != source_sha256
            or payload.get("source_bytes") != source_bytes
            or not isinstance(acoustics, dict)
            or acoustics.get("rate") != HOSTED_C1_RATE
            or not isinstance(timebase, dict)
            or timebase.get("rate") != HOSTED_C1_RATE
            or not isinstance(feature_sha256, str)
            or _DIGEST.fullmatch(feature_sha256) is None
            or _file_sha256(features) != feature_sha256
        ):
            raise NativeRuntimeError("native_runtime_source_binding_mismatch")
        try:
            expected_size = int(acoustics["header_bytes"]) + int(
                acoustics["uncompressed_payload_bytes"]
            )
        except (KeyError, TypeError, ValueError, OverflowError):
            raise NativeRuntimeError("native_runtime_feature_invalid") from None
        if expected_size != feature_info.st_size or not 0 < expected_size <= MAX_OUTPUT_BYTES:
            raise NativeRuntimeError("native_runtime_feature_invalid")
        try:
            frames = iter_features(features)
            for _ in frames:
                pass
        except (OSError, ValueError, RuntimeError):
            raise NativeRuntimeError("native_runtime_feature_invalid") from None
        return payload


__all__ = [
    "DockerNativeRuntime",
    "HOSTED_C1_RATE",
    "NATIVE_RUNTIME_SCHEMA",
    "NativeRuntime",
    "NativeRuntimeError",
    "SocketNativeRuntime",
]
