"""Supervised Unix-socket bridge for the isolated Sales Xray native helper.

This process is intended to run under the release owner's host supervisor. It is
the only process in this slice that owns the Docker CLI. The database/credential
worker connects through SocketNativeRuntime and never receives Docker access.
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import socket
import stat
import struct
import sys
import threading
import time
from contextlib import suppress
from pathlib import Path
from typing import Any
from uuid import UUID

from ac_platform.conversation_intelligence.native_runtime import (
    HOSTED_C1_RATE,
    MAX_REQUEST_BYTES,
    NATIVE_GID,
    NATIVE_RUNTIME_SCHEMA,
    NATIVE_UID,
    DockerNativeRuntime,
    NativeRuntimeError,
    _canonical_json,
    _file_sha256,
    _object_pairs,
    _path_is_safe,
    _validate_request_paths,
)

_MAX_PEER_FRAME = MAX_REQUEST_BYTES
_REQUEST_DEADLINE_SECONDS = 10.0


def _recv_exact(channel: socket.socket, length: int, *, deadline: float | None = None) -> bytes:
    data = bytearray()
    while len(data) < length:
        if deadline is not None:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise NativeRuntimeError("native_runtime_timeout")
            channel.settimeout(remaining)
        block = channel.recv(length - len(data))
        if not block:
            raise NativeRuntimeError("native_runtime_failed")
        data.extend(block)
    return bytes(data)


def _read_request(channel: socket.socket) -> dict[str, Any]:
    deadline = time.monotonic() + _REQUEST_DEADLINE_SECONDS
    header = _recv_exact(channel, 4, deadline=deadline)
    length = struct.unpack(">I", header)[0]
    if not 0 < length <= _MAX_PEER_FRAME:
        raise NativeRuntimeError("native_runtime_failed")
    try:
        request = json.loads(
            _recv_exact(channel, length, deadline=deadline).decode("utf-8"),
            object_pairs_hook=_object_pairs,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError):
        raise NativeRuntimeError("native_runtime_failed") from None
    if not isinstance(request, dict):
        raise NativeRuntimeError("native_runtime_failed")
    return request


def _response(channel: socket.socket, *, ok: bool, error: str | None = None) -> None:
    data: dict[str, Any] = {"schema": NATIVE_RUNTIME_SCHEMA, "ok": ok}
    if error is not None:
        data["error"] = error
    raw = _canonical_json(data)
    channel.sendall(struct.pack(">I", len(raw)) + raw)


def _safe_response(channel: socket.socket, *, ok: bool, error: str | None = None) -> None:
    # A client can disconnect after sending a request. That per-peer transport
    # failure must not terminate the supervised helper.
    with suppress(OSError):
        _response(channel, ok=ok, error=error)


def _peer_uid(channel: socket.socket) -> int:
    if not hasattr(socket, "SO_PEERCRED"):
        raise NativeRuntimeError("native_runtime_configuration_invalid")
    try:
        raw = channel.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i"))
        # Linux ucred is ordered as pid, uid, gid.
        return int(struct.unpack("3i", raw)[1])
    except (OSError, struct.error):
        raise NativeRuntimeError("native_runtime_configuration_invalid") from None


def _handle(
    channel: socket.socket,
    *,
    runtime: DockerNativeRuntime,
    workspace_root: Path,
    image_ref: str,
    peer_uid: int,
) -> None:
    try:
        channel.settimeout(_REQUEST_DEADLINE_SECONDS)
        if _peer_uid(channel) != peer_uid:
            raise NativeRuntimeError("native_runtime_failed")
        request = _read_request(channel)
        channel.settimeout(runtime.timeout_seconds + 10)
        expected = {
            "schema",
            "operation",
            "source",
            "outdir",
            "job_id",
            "image_ref",
            "rate",
            "source_sha256",
            "source_bytes",
        }
        if set(request) != expected or request.get("schema") != NATIVE_RUNTIME_SCHEMA:
            raise NativeRuntimeError("native_runtime_failed")
        if (
            request.get("operation") not in {"inspect", "validate"}
            or request.get("image_ref") != image_ref
            or request.get("rate") != HOSTED_C1_RATE
            or not isinstance(request.get("source"), str)
            or not isinstance(request.get("outdir"), str)
            or not isinstance(request.get("source_sha256"), str)
            or not isinstance(request.get("source_bytes"), int)
        ):
            raise NativeRuntimeError("native_runtime_failed")
        try:
            job_id = UUID(request["job_id"])
        except (TypeError, ValueError):
            raise NativeRuntimeError("native_runtime_failed") from None
        source, outdir = Path(request["source"]), Path(request["outdir"])
        source_sha256, source_bytes = _validate_request_paths(source, outdir, workspace_root)
        if source_sha256 != request["source_sha256"] or source_bytes != request["source_bytes"]:
            raise NativeRuntimeError("native_runtime_source_binding_mismatch")
        if request["operation"] == "inspect":
            result = runtime.inspect(source, outdir, job_id=job_id, rate=HOSTED_C1_RATE)
        else:
            result = runtime.validate_source(source, outdir, job_id=job_id, rate=HOSTED_C1_RATE)
        if (
            result.get("source_sha256") != request["source_sha256"]
            or result.get("source_bytes") != request["source_bytes"]
            or _file_sha256(source) != request["source_sha256"]
            or source.stat().st_size != request["source_bytes"]
        ):
            raise NativeRuntimeError("native_runtime_source_binding_mismatch")
        _safe_response(channel, ok=True)
    except NativeRuntimeError as error:
        _safe_response(channel, ok=False, error=error.code)
    except (OSError, ValueError, TypeError):
        _safe_response(channel, ok=False, error="native_runtime_failed")


def _parse() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Sales Xray native runtime helper")
    parser.add_argument("--socket", type=Path, required=True)
    parser.add_argument("--workspace-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--image-ref", required=True)
    parser.add_argument("--peer-uid", type=int, required=True)
    parser.add_argument("--peer-gid", type=int, required=True)
    parser.add_argument("--timeout-seconds", type=float, default=750.0)
    args = parser.parse_args()
    if (
        not args.socket.is_absolute()
        or len(os.fsencode(args.socket)) > 107
        or not args.workspace_root.is_absolute()
        or not args.output_root.is_absolute()
        or args.peer_uid < 0
        or args.peer_gid < 0
    ):
        parser.error("invalid native helper path or peer identity")
    return args


def main() -> int:
    args = _parse()
    try:
        workspace = args.workspace_root
        if not _path_is_safe(workspace, None):
            raise NativeRuntimeError("native_runtime_configuration_invalid")
        info = workspace.lstat()
        if not stat.S_ISDIR(info.st_mode):
            raise NativeRuntimeError("native_runtime_configuration_invalid")
        if not _path_is_safe(args.output_root, workspace):
            raise NativeRuntimeError("native_runtime_configuration_invalid")
        DockerNativeRuntime._validate_output_root(
            args.output_root, expected_owner=(NATIVE_UID, NATIVE_GID)
        )
        if args.socket.exists() or args.socket.is_symlink():
            raise NativeRuntimeError("native_runtime_output_exists")
        runtime = DockerNativeRuntime(
            args.image_ref,
            workspace_root=workspace,
            output_root=args.output_root,
            native_owner=(NATIVE_UID, NATIVE_GID),
            timeout_seconds=args.timeout_seconds,
        )
        unix_family = getattr(socket, "AF_UNIX", None)
        if not isinstance(unix_family, int):
            raise NativeRuntimeError("native_runtime_configuration_invalid")
        server = socket.socket(unix_family, socket.SOCK_STREAM)
        stopping = threading.Event()

        def request_stop(_signum: int, _frame: Any) -> None:
            stopping.set()

        try:
            signal.signal(signal.SIGTERM, request_stop)
            signal.signal(signal.SIGINT, request_stop)
            server.bind(str(args.socket))
            os.chmod(args.socket, 0o660)
            if hasattr(os, "chown"):
                os.chown(args.socket, -1, args.peer_gid)
            server.listen(1)
            server.settimeout(1.0)
            while not stopping.is_set():
                try:
                    channel, _ = server.accept()
                except TimeoutError:
                    continue
                with channel:
                    _handle(
                        channel,
                        runtime=runtime,
                        workspace_root=workspace,
                        image_ref=args.image_ref,
                        peer_uid=args.peer_uid,
                    )
        finally:
            server.close()
            try:
                socket_path_info = args.socket.lstat()
                if stat.S_ISSOCK(socket_path_info.st_mode) and socket_path_info.st_nlink == 1:
                    args.socket.unlink()
            except FileNotFoundError:
                pass
        return 0
    except NativeRuntimeError as error:
        # Keep startup failures observable to the release smoke and supervisor
        # without exposing paths, command output, credentials, or audio data.
        print(f"native_helper_start_failed:{error.code}", file=sys.stderr)
        return 78
    except (OSError, ValueError, TypeError) as error:
        print(f"native_helper_start_failed:{type(error).__name__}", file=sys.stderr)
        return 78


if __name__ == "__main__":
    raise SystemExit(main())
