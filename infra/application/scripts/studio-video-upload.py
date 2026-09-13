#!/usr/bin/env python3
"""Stream one local Studio video through the canonical authenticated API.

The operator runs this from a trusted workstation after signing in on Coach.
The video is never copied to the VPS: its bytes are piped through ``ssh ac``
to the loopback Caddy route, which preserves the normal upload intent, audit,
scanner, processing and catalog boundaries.  The session cookie is read from
hidden input (or a private, ephemeral environment variable) and is sent only
as the first line of the SSH stdin stream; it is never an argument, log line,
or persisted file.

This is deliberately a whole-object uploader.  The application contract has
no resumable or range upload operation, so an interrupted PUT must restart
from byte zero with a still-valid upload intent.
"""

from __future__ import annotations

import argparse
import getpass
import hashlib
import json
import math
import os
import re
import shlex
import stat
import subprocess
import sys
import threading
import time
import uuid
import warnings
from collections.abc import Mapping, Sequence
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import BinaryIO
from urllib.parse import urlsplit

MAX_SOURCE_BYTES = 2_000_000_000
MAX_RESPONSE_BYTES = 1 * 1024 * 1024
REMOTE_CONTROL_TIMEOUT_SECONDS = 30.0
REMOTE_VIDEO_TIMEOUT_SECONDS = 1800.0
REMOTE_COMPLETION_OVERHEAD_SECONDS = 120.0
REMOTE_COMPLETION_TIMEOUT_SECONDS = (
    REMOTE_VIDEO_TIMEOUT_SECONDS + REMOTE_COMPLETION_OVERHEAD_SECONDS
)
REMOTE_EXIT_GRACE_SECONDS = 30.0
MAX_POLL_SECONDS = 60.0
MAX_POLL_TIMEOUT_SECONDS = 3600.0
SESSION_COOKIE_ENV = "AC_STUDIO_SESSION_COOKIE"
SESSION_PATTERN = re.compile(r"[A-Za-z0-9_-]{43,512}\Z")
UUID_PATTERN = re.compile(r"[0-9a-fA-F]{8}-(?:[0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}\Z")
SAFE_IDEMPOTENCY_PATTERN = re.compile(r"[A-Za-z0-9_-]{1,128}\Z")
ALLOWED_TYPES = {".mp4": "video/mp4", ".webm": "video/webm"}


class UploadOperatorError(RuntimeError):
    """A local validation or canonical API operation failed."""


@dataclass(frozen=True, slots=True)
class EdgeProfile:
    origin: str
    host: str
    loopback_base: str = "http://127.0.0.1:8080"


PROFILES: Mapping[str, EdgeProfile] = {
    "https://coach.authorityclosers.com": EdgeProfile(
        "https://coach.authorityclosers.com", "coach.authorityclosers.com"
    ),
    "https://coach-staging.authorityclosers.com": EdgeProfile(
        "https://coach-staging.authorityclosers.com", "coach-staging.authorityclosers.com"
    ),
}


@dataclass(frozen=True, slots=True)
class FileEnvelope:
    path: Path
    byte_length: int
    checksum_sha256: str
    stat_identity: tuple[int, int, int, int]


@dataclass(frozen=True, slots=True)
class UploadIntent:
    upload_id: str
    upload_path: str
    headers: dict[str, str]
    expires_at: datetime
    max_bytes: int


def _require_uuid(value: object, label: str) -> str:
    if not isinstance(value, str) or UUID_PATTERN.fullmatch(value) is None:
        raise UploadOperatorError(f"{label} must be a UUID.")
    return str(uuid.UUID(value))


def _require_idempotency(value: str) -> str:
    if SAFE_IDEMPOTENCY_PATTERN.fullmatch(value) is None:
        raise UploadOperatorError("The idempotency key is invalid.")
    return value


def edge_profile(origin: str) -> EdgeProfile:
    profile = PROFILES.get(origin)
    if profile is None:
        raise UploadOperatorError(
            "Origin must be the exact production or staging Coach origin; "
            "arbitrary hosts and public API URLs are refused."
        )
    return profile


def _safe_filename(value: str) -> str:
    value = value.strip()
    if (
        not value
        or len(value) > 255
        or value in {".", ".."}
        or any(
            character in "/\\" or ord(character) < 32 or ord(character) == 127
            for character in value
        )
    ):
        raise UploadOperatorError("The video filename is invalid.")
    return value


def _content_type(filename: str, explicit: str | None) -> str:
    if explicit is not None:
        if explicit not in {"video/mp4", "video/webm"}:
            raise UploadOperatorError("Content type must be video/mp4 or video/webm.")
        return explicit
    try:
        return ALLOWED_TYPES[Path(filename).suffix.lower()]
    except KeyError as error:
        raise UploadOperatorError(
            "Use an .mp4 or .webm file, or supply its exact content type."
        ) from error


def _path_identity(info: os.stat_result) -> tuple[int, int, int, int]:
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns)


def inspect_file(path: Path) -> FileEnvelope:
    try:
        info = path.stat()
    except OSError as error:
        raise UploadOperatorError("The video file cannot be inspected.") from error
    if not stat.S_ISREG(info.st_mode) or info.st_nlink < 1:
        raise UploadOperatorError("The video must be a regular file.")
    if not 0 < info.st_size <= MAX_SOURCE_BYTES:
        raise UploadOperatorError(
            "The video is empty or exceeds the 2,000,000,000-byte source cap."
        )
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            remaining = info.st_size
            while remaining:
                chunk = stream.read(min(1024 * 1024, remaining))
                if not chunk:
                    raise UploadOperatorError(
                        "The video changed while its checksum was calculated."
                    )
                digest.update(chunk)
                remaining -= len(chunk)
            if stream.read(1):
                raise UploadOperatorError("The video changed while its checksum was calculated.")
    except OSError as error:
        raise UploadOperatorError(
            "The video could not be read for checksum calculation."
        ) from error
    after = path.stat()
    if _path_identity(info) != _path_identity(after):
        raise UploadOperatorError("The video changed while its checksum was calculated.")
    return FileEnvelope(path, info.st_size, digest.hexdigest(), _path_identity(info))


def validate_upload_intent(
    payload: object,
    *,
    program_id: str,
    file: FileEnvelope,
    content_type: str,
    now: datetime | None = None,
) -> UploadIntent:
    """Validate the server response before using any returned upload target."""

    if not isinstance(payload, dict):
        raise UploadOperatorError("The upload-intent response is not an object.")
    upload_id = _require_uuid(payload.get("upload_id"), "upload_id")
    normalized_program = _require_uuid(program_id, "program_id")
    raw_url = payload.get("upload_url")
    if not isinstance(raw_url, str):
        raise UploadOperatorError("The upload-intent response has no upload URL.")
    parsed = urlsplit(raw_url)
    expected_path = (
        f"/v1/admin/studio/programs/{normalized_program}/video-uploads/{upload_id}/bytes"
    )
    if (
        parsed.scheme
        or parsed.netloc
        or parsed.query
        or parsed.fragment
        or parsed.path != expected_path
    ):
        raise UploadOperatorError("The API returned an unsafe or unexpected upload URL.")

    raw_headers = payload.get("upload_headers")
    if not isinstance(raw_headers, dict):
        raise UploadOperatorError("The upload-intent response has no upload headers.")
    headers: dict[str, str] = {}
    for key, value in raw_headers.items():
        if not isinstance(key, str) or not isinstance(value, str):
            raise UploadOperatorError("The upload-intent headers are malformed.")
        lowered = key.lower()
        if lowered in headers:
            raise UploadOperatorError("The upload-intent headers contain duplicate names.")
        headers[lowered] = value
    expected_headers = {
        "content-type": content_type,
        "content-length": str(file.byte_length),
        "x-content-sha256": file.checksum_sha256,
    }
    if headers != expected_headers:
        raise UploadOperatorError("The API returned headers that do not match the local file.")

    max_bytes = payload.get("max_bytes")
    if type(max_bytes) is not int or not 1 <= max_bytes <= MAX_SOURCE_BYTES:
        raise UploadOperatorError("The API returned an invalid upload limit.")
    if file.byte_length > max_bytes:
        raise UploadOperatorError("The API upload limit is smaller than the local file.")
    raw_expiry = payload.get("expires_at")
    if not isinstance(raw_expiry, str):
        raise UploadOperatorError("The upload intent has no expiry.")
    try:
        expiry = datetime.fromisoformat(raw_expiry.replace("Z", "+00:00"))
    except ValueError as error:
        raise UploadOperatorError("The upload intent expiry is malformed.") from error
    if expiry.tzinfo is None:
        raise UploadOperatorError("The upload intent expiry has no timezone.")
    current = now or datetime.now(UTC)
    if expiry <= current:
        raise UploadOperatorError("The upload intent has already expired.")
    return UploadIntent(upload_id, expected_path, expected_headers, expiry, max_bytes)


def _curl_config_command() -> str:
    # AC_SESSION is read from the first stdin line. The value reaches curl via
    # an anonymous descriptor, so neither ssh nor curl receives it in argv.
    return 'exec 3< <(printf \'cookie = \\"__Host-ac_session=%s\\"\\n\' "$AC_SESSION")'


def _remote_command(
    *,
    method: str,
    profile: EdgeProfile,
    path: str,
    headers: Mapping[str, str],
    idempotency_key: str | None = None,
    read_body_line: bool = False,
    upload: bool = False,
    timeout_seconds: int = int(REMOTE_CONTROL_TIMEOUT_SECONDS),
) -> str:
    if method not in {"GET", "POST", "PUT"}:
        raise UploadOperatorError("Unsupported canonical API method.")
    _require_idempotency(idempotency_key) if idempotency_key is not None else None
    prefix = [
        "set -euo pipefail",
        "IFS= read -r AC_SESSION",
        _curl_config_command(),
    ]
    if read_body_line:
        prefix.append("IFS= read -r AC_BODY")
    curl = [
        "curl --disable --noproxy '*' --config /dev/fd/3 --http1.1 --silent --show-error "
        "--write-out '\\n%{http_code}' --connect-timeout 15 "
        f"--max-time {int(timeout_seconds)} --max-filesize {MAX_RESPONSE_BYTES} "
        f"--request {shlex.quote(method)}",
        f"--header {shlex.quote(f'Host: {profile.host}')} "
        f"--header {shlex.quote(f'Origin: {profile.origin}')} "
        "--header 'Expect:'",
    ]
    for name, value in headers.items():
        curl.append(shlex.quote(f"--header={name}: {value}"))
    if idempotency_key is not None:
        curl.append(shlex.quote(f"--header=Idempotency-Key: {idempotency_key}"))
    if read_body_line:
        curl.append('--data-binary "$AC_BODY"')
    elif method == "POST":
        curl.append("--data-binary ''")
    if upload:
        curl.append("--upload-file -")
        curl.append("--output /dev/null")
    curl.append(shlex.quote(profile.loopback_base + path))
    return "; ".join(prefix) + "; " + " ".join(curl)


def _status_from_output(output: bytes) -> tuple[int, bytes]:
    marker = b"\n"
    code_line = output.rsplit(marker, 1)[-1].strip()
    try:
        code = int(code_line)
    except ValueError as error:
        raise UploadOperatorError("The SSH API response had no HTTP status.") from error
    body = output[: -(len(code_line) + 1)] if marker in output else b""
    return code, body


def _run_remote(
    *,
    ssh_target: str,
    command: str,
    cookie: str,
    body: bytes = b"",
    ssh_binary: str = "ssh",
    stream: BinaryIO | None = None,
    stream_bytes: int | None = None,
    wait_timeout_seconds: float = REMOTE_CONTROL_TIMEOUT_SECONDS + REMOTE_EXIT_GRACE_SECONDS,
) -> tuple[int, bytes]:
    if ssh_target != "ac":
        raise UploadOperatorError("The operator tool permits only the reviewed SSH alias 'ac'.")
    if stream is not None and (type(stream_bytes) is not int or stream_bytes < 0):
        raise UploadOperatorError("The streamed video length is required.")
    if not math.isfinite(wait_timeout_seconds) or not 0 < wait_timeout_seconds <= 3600:
        raise UploadOperatorError("The SSH/API wait deadline is outside bounded limits.")
    # OpenSSH joins remote arguments into one login-shell command. Quote the
    # complete payload so semicolons and process substitution are interpreted
    # only by the intended ``bash -c`` process on the reviewed host.
    remote_argv = [
        ssh_binary,
        "-T",
        "-o",
        "BatchMode=yes",
        "-o",
        "ConnectTimeout=15",
        "-o",
        "ServerAliveInterval=30",
        "-o",
        "ServerAliveCountMax=2",
        ssh_target,
        "bash",
        "-c",
        shlex.quote(command),
    ]
    process = subprocess.Popen(  # noqa: S603 - the SSH alias and command are pinned above
        remote_argv,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    assert process.stdin is not None
    assert process.stdout is not None
    stdin = process.stdin
    stdout_buffer = bytearray()
    stdout_overflow = False
    stdout_error: BaseException | None = None
    deadline_expired = threading.Event()

    def expire_process() -> None:
        deadline_expired.set()
        with suppress(Exception):
            process.kill()

    deadline_timer = threading.Timer(wait_timeout_seconds, expire_process)
    deadline_timer.daemon = True
    deadline_timer.start()

    def collect_stdout() -> None:
        nonlocal stdout_overflow, stdout_error
        try:
            while True:
                remaining = MAX_RESPONSE_BYTES + 1 - len(stdout_buffer)
                chunk = process.stdout.read(min(64 * 1024, remaining))
                if not chunk:
                    return
                stdout_buffer.extend(chunk)
                if len(stdout_buffer) > MAX_RESPONSE_BYTES:
                    stdout_overflow = True
                    with suppress(Exception):
                        process.kill()
                    return
        except BaseException as error:
            stdout_error = error
            with suppress(Exception):
                process.kill()

    reader = threading.Thread(target=collect_stdout, daemon=True)
    reader.start()

    def stop_process() -> None:
        deadline_timer.cancel()
        with suppress(Exception):
            process.kill()
        with suppress(Exception):
            process.wait(timeout=10)
        reader.join(timeout=10)

    try:
        stdin.write(cookie.encode("ascii") + b"\n")
        if body:
            stdin.write(body + b"\n")
        if stream is not None:
            remaining = stream_bytes
            assert remaining is not None
            while remaining:
                chunk = stream.read(min(1024 * 1024, remaining))
                if not chunk:
                    raise UploadOperatorError("The video changed during streaming.")
                stdin.write(chunk)
                remaining -= len(chunk)
            if stream.read(1):
                raise UploadOperatorError("The video changed during streaming.")
        stdin.close()
        # Detach the closed handle from Popen's lifecycle before waiting.
        process.stdin = None
    except (BrokenPipeError, OSError) as error:
        timed_out = deadline_expired.is_set()
        stop_process()
        if timed_out:
            raise UploadOperatorError("The SSH/API command timed out.") from error
        raise UploadOperatorError(
            "The SSH/API stream closed before the upload completed."
        ) from error
    except UploadOperatorError:
        stop_process()
        raise
    try:
        process.wait(timeout=wait_timeout_seconds)
    except subprocess.TimeoutExpired as error:
        stop_process()
        raise UploadOperatorError("The SSH/API command timed out.") from error
    if deadline_expired.is_set():
        stop_process()
        raise UploadOperatorError("The SSH/API command timed out.")
    deadline_timer.cancel()
    reader.join(timeout=10)
    if reader.is_alive():
        raise UploadOperatorError("The SSH API response reader did not finish.")
    if stdout_error is not None:
        raise UploadOperatorError("The SSH API response could not be read.") from stdout_error
    if stdout_overflow:
        raise UploadOperatorError("The SSH API response exceeded the bounded response limit.")
    if process.returncode not in {0, 22}:
        raise UploadOperatorError("The SSH/API command failed before a canonical response arrived.")
    return _status_from_output(bytes(stdout_buffer))


def _json_response(code: int, body: bytes, operation: str) -> object:
    if not 200 <= code < 300:
        raise UploadOperatorError(f"The canonical {operation} request returned HTTP {code}.")
    try:
        return json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise UploadOperatorError(f"The canonical {operation} response was not JSON.") from error


def create_intent(
    *,
    profile: EdgeProfile,
    program_id: str,
    filename: str,
    content_type: str,
    file: FileEnvelope,
    cookie: str,
    ssh_target: str,
    ssh_binary: str,
) -> UploadIntent:
    key = uuid.uuid4().hex
    body = json.dumps(
        {
            "filename": filename,
            "content_type": content_type,
            "content_length": file.byte_length,
            "checksum_sha256": file.checksum_sha256,
        },
        separators=(",", ":"),
    ).encode("utf-8")
    path = f"/v1/admin/studio/programs/{_require_uuid(program_id, 'program_id')}/video-uploads"
    command = _remote_command(
        method="POST",
        profile=profile,
        path=path,
        headers={"Content-Type": "application/json"},
        idempotency_key=key,
        read_body_line=True,
    )
    code, response = _run_remote(
        ssh_target=ssh_target,
        command=command,
        cookie=cookie,
        body=body,
        ssh_binary=ssh_binary,
    )
    payload = _json_response(code, response, "upload-intent")
    return validate_upload_intent(
        payload,
        program_id=program_id,
        file=file,
        content_type=content_type,
    )


def put_video(
    *,
    profile: EdgeProfile,
    program_id: str,
    intent: UploadIntent,
    file: FileEnvelope,
    cookie: str,
    ssh_target: str,
    ssh_binary: str,
) -> None:
    if intent.expires_at <= datetime.now(UTC):
        raise UploadOperatorError("The upload intent expired before byte streaming began.")
    current = file.path.stat()
    if _path_identity(current) != file.stat_identity:
        raise UploadOperatorError(
            "The video changed after intent admission; refusing to stream it."
        )
    headers = {
        "Content-Type": intent.headers["content-type"],
        "Content-Length": intent.headers["content-length"],
        "X-Content-SHA256": intent.headers["x-content-sha256"],
    }
    command = _remote_command(
        method="PUT",
        profile=profile,
        path=intent.upload_path,
        headers=headers,
        upload=True,
        timeout_seconds=int(REMOTE_VIDEO_TIMEOUT_SECONDS),
    )
    try:
        with file.path.open("rb") as stream:
            code, _ = _run_remote(
                ssh_target=ssh_target,
                command=command,
                cookie=cookie,
                ssh_binary=ssh_binary,
                stream=stream,
                stream_bytes=file.byte_length,
                wait_timeout_seconds=REMOTE_VIDEO_TIMEOUT_SECONDS + REMOTE_EXIT_GRACE_SECONDS,
            )
    except OSError as error:
        raise UploadOperatorError("The video could not be opened for streaming.") from error
    if code != 204:
        raise UploadOperatorError(f"The canonical byte PUT returned HTTP {code}.")


def _json_command(
    *,
    profile: EdgeProfile,
    path: str,
    cookie: str,
    ssh_target: str,
    ssh_binary: str,
    method: str = "GET",
    idempotency_key: str | None = None,
    timeout_seconds: float = REMOTE_CONTROL_TIMEOUT_SECONDS,
) -> object:
    if not math.isfinite(timeout_seconds) or not 0 < timeout_seconds <= 3600:
        raise UploadOperatorError("The SSH/API request deadline is outside bounded limits.")
    command = _remote_command(
        method=method,
        profile=profile,
        path=path,
        headers={},
        idempotency_key=idempotency_key,
        timeout_seconds=int(timeout_seconds),
    )
    code, body = _run_remote(
        ssh_target=ssh_target,
        command=command,
        cookie=cookie,
        ssh_binary=ssh_binary,
        wait_timeout_seconds=timeout_seconds + REMOTE_EXIT_GRACE_SECONDS,
    )
    return _json_response(code, body, method.lower())


def complete_and_poll(
    *,
    profile: EdgeProfile,
    program_id: str,
    intent: UploadIntent,
    cookie: str,
    ssh_target: str,
    ssh_binary: str,
    poll_seconds: float,
    poll_timeout: float,
) -> dict[str, object]:
    if (
        not math.isfinite(poll_seconds)
        or not 0 < poll_seconds <= MAX_POLL_SECONDS
        or not math.isfinite(poll_timeout)
        or not 0 < poll_timeout <= MAX_POLL_TIMEOUT_SECONDS
    ):
        raise UploadOperatorError("Polling intervals and timeout exceed bounded limits.")
    key = uuid.uuid4().hex
    path = (
        f"/v1/admin/studio/programs/{_require_uuid(program_id, 'program_id')}"
        f"/video-uploads/{intent.upload_id}/complete"
    )
    response = _json_command(
        profile=profile,
        path=path,
        cookie=cookie,
        ssh_target=ssh_target,
        ssh_binary=ssh_binary,
        method="POST",
        idempotency_key=key,
        timeout_seconds=REMOTE_COMPLETION_TIMEOUT_SECONDS,
    )
    if not isinstance(response, dict):
        raise UploadOperatorError("The completion response was not an object.")
    state = response.get("state")
    status: dict[str, object] = response
    if state in {"failed", "retired"}:
        raise UploadOperatorError(f"Video completion ended in state {state}.")
    status_path = (
        f"/v1/admin/studio/programs/{_require_uuid(program_id, 'program_id')}"
        f"/video-uploads/{intent.upload_id}"
    )
    deadline = time.monotonic() + poll_timeout
    while state not in {"ready", "failed", "retired"}:
        if time.monotonic() >= deadline:
            raise UploadOperatorError("Timed out while polling video processing status.")
        time.sleep(poll_seconds)
        status = _json_command(
            profile=profile,
            path=status_path,
            cookie=cookie,
            ssh_target=ssh_target,
            ssh_binary=ssh_binary,
        )
        if not isinstance(status, dict):
            raise UploadOperatorError("The upload-status response was not an object.")
        state = status.get("state")
    if state != "ready":
        raise UploadOperatorError(f"Video processing ended in state {state}.")
    return status


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--video", type=Path, required=True)
    parser.add_argument("--program-id", required=True)
    parser.add_argument("--origin", default="https://coach.authorityclosers.com")
    parser.add_argument("--content-type")
    parser.add_argument("--filename")
    parser.add_argument("--ssh-target", default="ac")
    parser.add_argument("--ssh-binary", default="ssh")
    parser.add_argument("--poll-seconds", type=float, default=10.0)
    parser.add_argument("--poll-timeout", type=float, default=1800.0)
    return parser


def _read_session_cookie() -> str:
    cookie = os.environ.get(SESSION_COOKIE_ENV)
    if cookie is not None:
        return cookie
    # Refuse getpass's no-terminal fallback before it echoes the value on
    # ordinary stdin.
    with warnings.catch_warnings():
        warnings.simplefilter("error", getpass.GetPassWarning)
        try:
            return getpass.getpass("Coach session cookie (hidden; never logged): ")
        except getpass.GetPassWarning as error:
            raise UploadOperatorError(
                "Hidden session input is unavailable; use the private ephemeral environment."
            ) from error


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        profile = edge_profile(args.origin)
        filename = _safe_filename(args.filename or args.video.name)
        content_type = _content_type(filename, args.content_type)
        file = inspect_file(args.video)
        cookie = _read_session_cookie()
        if SESSION_PATTERN.fullmatch(cookie) is None:
            raise UploadOperatorError("The Coach session cookie is malformed.")
        intent = create_intent(
            profile=profile,
            program_id=args.program_id,
            filename=filename,
            content_type=content_type,
            file=file,
            cookie=cookie,
            ssh_target=args.ssh_target,
            ssh_binary=args.ssh_binary,
        )
        put_video(
            profile=profile,
            program_id=args.program_id,
            intent=intent,
            file=file,
            cookie=cookie,
            ssh_target=args.ssh_target,
            ssh_binary=args.ssh_binary,
        )
        status = complete_and_poll(
            profile=profile,
            program_id=args.program_id,
            intent=intent,
            cookie=cookie,
            ssh_target=args.ssh_target,
            ssh_binary=args.ssh_binary,
            poll_seconds=args.poll_seconds,
            poll_timeout=args.poll_timeout,
        )
        print(
            f"Studio video ready: upload_id={intent.upload_id} "
            f"bytes={file.byte_length} state={status.get('state')}"
        )
        return 0
    except (UploadOperatorError, OSError, ValueError) as error:
        print(f"Studio video upload refused: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
