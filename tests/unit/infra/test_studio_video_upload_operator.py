"""Secret-safe contract tests for the bounded SSH Studio uploader."""

from __future__ import annotations

import importlib.util
import io
import json
import os
import shlex
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest


@pytest.fixture(scope="module")
def uploader() -> ModuleType:
    path = Path(__file__).parents[3] / "infra/application/scripts/studio-video-upload.py"
    spec = importlib.util.spec_from_file_location("studio_video_upload_operator", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _file(module: ModuleType) -> Any:
    return module.FileEnvelope(
        Path("film.mp4"),
        123,
        "a" * 64,
        (1, 2, 123, 4),
    )


def _intent_payload(module: ModuleType) -> dict[str, object]:
    upload_id = "22222222-2222-4222-8222-222222222222"
    program_id = "11111111-1111-4111-8111-111111111111"
    return {
        "upload_id": upload_id,
        "upload_url": (f"/v1/admin/studio/programs/{program_id}/video-uploads/{upload_id}/bytes"),
        "upload_headers": {
            "content-type": "video/mp4",
            "content-length": "123",
            "x-content-sha256": "a" * 64,
        },
        "expires_at": (datetime.now(UTC) + timedelta(minutes=10)).isoformat(),
        "max_bytes": module.MAX_SOURCE_BYTES,
    }


def test_intent_validation_pins_relative_route_and_exact_file_headers(uploader: ModuleType) -> None:
    intent = uploader.validate_upload_intent(
        _intent_payload(uploader),
        program_id="11111111-1111-4111-8111-111111111111",
        file=_file(uploader),
        content_type="video/mp4",
    )

    assert intent.upload_path.endswith("/bytes")
    assert intent.headers["content-length"] == "123"
    assert intent.max_bytes == 2_000_000_000


@pytest.mark.parametrize(
    "change",
    [
        lambda payload: payload.update({"upload_url": "https://evil.example/bytes"}),
        lambda payload: payload["upload_headers"].update({"content-length": "124"}),
        lambda payload: payload["upload_headers"].update({"content-encoding": "gzip"}),
    ],
)
def test_intent_validation_rejects_untrusted_server_transport(uploader: ModuleType, change) -> None:
    payload = _intent_payload(uploader)
    change(payload)
    with pytest.raises(uploader.UploadOperatorError):
        uploader.validate_upload_intent(
            payload,
            program_id="11111111-1111-4111-8111-111111111111",
            file=_file(uploader),
            content_type="video/mp4",
        )


def test_remote_command_pins_loopback_host_and_never_contains_cookie(uploader: ModuleType) -> None:
    profile = uploader.edge_profile("https://coach.authorityclosers.com")
    command = uploader._remote_command(
        method="PUT",
        profile=profile,
        path="/v1/admin/studio/programs/11111111-1111-4111-8111-111111111111/"
        "video-uploads/22222222-2222-4222-8222-222222222222/bytes",
        headers={
            "Content-Type": "video/mp4",
            "Content-Length": "123",
            "X-Content-SHA256": "a" * 64,
        },
        upload=True,
        idempotency_key="synthetic-header-fix",
    )

    assert "http://127.0.0.1:8080" in command
    assert "Host: coach.authorityclosers.com" in command
    assert "Origin: https://coach.authorityclosers.com" in command
    assert "curl --disable --noproxy '*'" in command
    assert "--header 'Content-Type: video/mp4'" in command
    assert "--header 'Idempotency-Key: synthetic-header-fix'" in command
    assert "--header=Content-Type:" not in command
    assert "--header=Idempotency-Key:" not in command
    assert "AC_SESSION" in command
    assert "secret" not in command

    tokens = shlex.split(command)
    headers = [
        tokens[index + 1] for index, argument in enumerate(tokens[:-1]) if argument == "--header"
    ]
    assert "Content-Type: video/mp4" in headers
    assert "Idempotency-Key: synthetic-header-fix" in headers

    with pytest.raises(uploader.UploadOperatorError):
        uploader.edge_profile("https://api.authorityclosers.com")


@pytest.mark.skipif(
    os.name != "nt" or os.environ.get("AC_RUN_OPERATOR_NETWORK_PROOF") != "1",
    reason="opt-in Windows staging SSH proof",
)
def test_real_windows_staging_post_rejects_synthetic_cookie_without_admission(
    uploader: ModuleType,
) -> None:
    program_id = "189cec59-e302-4fe3-8215-a34c68e394a9"
    profile = uploader.edge_profile("https://coach-staging.authorityclosers.com")
    command = uploader._remote_command(
        method="POST",
        profile=profile,
        path=f"/v1/admin/studio/programs/{program_id}/video-uploads",
        headers={"Content-Type": "application/json"},
        idempotency_key="synthetic-header-fix-proof",
        read_body_line=True,
    )
    body = json.dumps(
        {
            "filename": "synthetic-header-fix.mp4",
            "content_type": "video/mp4",
            "content_length": 1,
            "checksum_sha256": "0" * 64,
        },
        separators=(",", ":"),
    ).encode("ascii")

    code, _response = uploader._run_remote(
        ssh_target="ac",
        command=command,
        cookie="synthetic-no-secret-" + "S" * 43,
        body=body,
        ssh_binary=r"C:\Windows\System32\OpenSSH\ssh.exe",
        wait_timeout_seconds=60,
    )

    assert code in {401, 403}


class _FakeStdin:
    def __init__(self, *, fail_after: int | None = None) -> None:
        self.data = bytearray()
        self.fail_after = fail_after
        self.closed = False

    def write(self, value: bytes) -> int:
        if self.fail_after is not None and len(self.data) >= self.fail_after:
            raise BrokenPipeError
        self.data.extend(value)
        return len(value)

    def close(self) -> None:
        self.closed = True


class _FakeProcess:
    def __init__(self, *, fail_after: int | None = None, returncode: int = 0) -> None:
        self.stdin = _FakeStdin(fail_after=fail_after)
        self.stdout = io.BytesIO(b"\n204")
        self.stderr = io.BytesIO()
        self.returncode = returncode
        self.killed = False

    def communicate(self, timeout: int | None = None) -> tuple[bytes, bytes]:
        return b"\n204", b""

    def kill(self) -> None:
        self.killed = True

    def wait(self, timeout: int) -> int:
        return self.returncode


def test_stream_sends_cookie_line_then_bytes_without_putting_cookie_in_argv(
    uploader: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    token = "A" * 43
    process = _FakeProcess()
    process_stdin = process.stdin
    argv: list[list[str]] = []
    monkeypatch.setattr(
        uploader.subprocess,
        "Popen",
        lambda args, **kwargs: (argv.append(args), process)[1],
    )

    code, _body = uploader._run_remote(
        ssh_target="ac",
        command="safe-command",
        cookie=token,
        stream=io.BytesIO(b"video-bytes"),
        stream_bytes=len(b"video-bytes"),
    )

    assert code == 204
    assert bytes(process_stdin.data) == token.encode() + b"\nvideo-bytes"
    assert token not in " ".join(argv[0])
    assert argv[0][-1] == shlex.quote("safe-command")
    assert process_stdin.closed


def test_remote_command_shell_metacharacters_are_contained_in_bash_c_argument(
    uploader: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    process = _FakeProcess()
    argv: list[list[str]] = []
    monkeypatch.setattr(
        uploader.subprocess,
        "Popen",
        lambda args, **kwargs: (argv.append(args), process)[1],
    )

    uploader._run_remote(
        ssh_target="ac",
        command="printf 'safe; command'",
        cookie="A" * 43,
    )

    assert argv[0][-1] == shlex.quote("printf 'safe; command'")


def test_stream_failure_is_bounded_and_does_not_echo_cookie(
    uploader: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    token = "B" * 43
    process = _FakeProcess(fail_after=len(token) + 1)
    monkeypatch.setattr(uploader.subprocess, "Popen", lambda *args, **kwargs: process)

    with pytest.raises(uploader.UploadOperatorError, match="stream closed") as error:
        uploader._run_remote(
            ssh_target="ac",
            command="safe-command",
            cookie=token,
            stream=io.BytesIO(b"video-bytes"),
            stream_bytes=len(b"video-bytes"),
        )

    assert token not in str(error.value)
    assert process.killed


def test_stream_rejects_bytes_beyond_admitted_length_and_kills_process(
    uploader: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    process = _FakeProcess()
    monkeypatch.setattr(uploader.subprocess, "Popen", lambda *args, **kwargs: process)

    with pytest.raises(uploader.UploadOperatorError, match="changed during streaming"):
        uploader._run_remote(
            ssh_target="ac",
            command="safe-command",
            cookie="B" * 43,
            stream=io.BytesIO(b"video-bytes-extra"),
            stream_bytes=len(b"video-bytes"),
        )

    assert process.killed


def test_hidden_cookie_prompt_refuses_echo_fallback(
    uploader: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(uploader.SESSION_COOKIE_ENV, raising=False)

    def echoing_prompt(_prompt: str) -> str:
        raise uploader.getpass.GetPassWarning("echo fallback")

    monkeypatch.setattr(uploader.getpass, "getpass", echoing_prompt)
    with pytest.raises(uploader.UploadOperatorError, match="Hidden session input"):
        uploader._read_session_cookie()


def test_real_subprocess_accepts_detached_closed_stdin(
    uploader: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    real_popen = uploader.subprocess.Popen

    def local_process(_args, **kwargs):
        return real_popen(
            [
                sys.executable,
                "-c",
                "import sys; sys.stdin.buffer.read(); sys.stdout.buffer.write(b'\\n204')",
            ],
            **kwargs,
        )

    monkeypatch.setattr(uploader.subprocess, "Popen", local_process)
    code, body = uploader._run_remote(
        ssh_target="ac",
        command="safe-command",
        cookie="C" * 43,
        stream=io.BytesIO(b"video-bytes"),
        stream_bytes=len(b"video-bytes"),
    )

    assert code == 204
    assert body == b""


def test_real_subprocess_timeout_is_injected_and_bounded(
    uploader: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    real_popen = uploader.subprocess.Popen

    def local_process(_args, **kwargs):
        return real_popen(
            [
                sys.executable,
                "-c",
                "import time; time.sleep(0.2); print('\\n204', end='')",
            ],
            **kwargs,
        )

    monkeypatch.setattr(uploader.subprocess, "Popen", local_process)
    with pytest.raises(uploader.UploadOperatorError, match="timed out"):
        uploader._run_remote(
            ssh_target="ac",
            command="safe-command",
            cookie="D" * 43,
            wait_timeout_seconds=0.05,
        )


def test_real_subprocess_deadline_covers_blocking_stdin_write(
    uploader: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    real_popen = uploader.subprocess.Popen

    def local_process(_args, **kwargs):
        return real_popen(
            [sys.executable, "-c", "import time; time.sleep(1)"],
            **kwargs,
        )

    monkeypatch.setattr(uploader.subprocess, "Popen", local_process)
    with pytest.raises(uploader.UploadOperatorError, match="timed out"):
        uploader._run_remote(
            ssh_target="ac",
            command="safe-command",
            cookie="F" * 43,
            stream=io.BytesIO(b"x" * (2 * 1024 * 1024)),
            stream_bytes=2 * 1024 * 1024,
            wait_timeout_seconds=0.05,
        )


def test_real_subprocess_response_is_stopped_at_bounded_limit(
    uploader: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    real_popen = uploader.subprocess.Popen

    def local_process(_args, **kwargs):
        return real_popen(
            [
                sys.executable,
                "-c",
                (
                    "import sys; "
                    f"sys.stdout.buffer.write(b'x' * {uploader.MAX_RESPONSE_BYTES + 1}); "
                    "sys.stdout.flush()"
                ),
            ],
            **kwargs,
        )

    monkeypatch.setattr(uploader.subprocess, "Popen", local_process)
    with pytest.raises(uploader.UploadOperatorError, match="bounded response"):
        uploader._run_remote(
            ssh_target="ac",
            command="safe-command",
            cookie="E" * 43,
            wait_timeout_seconds=1,
        )
