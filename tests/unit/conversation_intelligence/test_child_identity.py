"""Synthetic tests for child-only Infisical service authentication."""

from __future__ import annotations

import io
import os
import stat
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from ac_platform.conversation_intelligence import child_identity
from ac_platform.conversation_intelligence.inference_broker import (
    BROKER_SCHEMA,
    CHILD_TOKEN_FILE_ENV,
    InfisicalLauncher,
    _decode_frame,
    _run_subprocess,
)

PACKAGE_ROOT = Path(__file__).resolve().parents[3] / "packages" / "python"


class _BinaryStdout:
    def __init__(self) -> None:
        self.buffer = io.BytesIO()


def _command(executable: str = "infisical") -> tuple[str, ...]:
    return (
        "--child",
        "--infisical-executable",
        executable,
        "--project-id",
        "b421c44e-4599-4394-8df6-758ed8aedfed",
        "--environment",
        "dev",
        "--path",
        "/sales-xray-test/groq",
    )


def _frame_from(output: _BinaryStdout) -> tuple[dict[str, Any], bytes]:
    return _decode_frame(output.buffer.getvalue(), maximum_payload=64 * 1024)


def test_child_reads_one_external_token_file_and_execs_only_fixed_command(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    token_file = tmp_path / "infisical-token"
    token_file.write_text("synthetic-child-service-token\n", encoding="ascii")
    if os.name == "posix":
        token_file.chmod(0o600)
    observed: dict[str, Any] = {}
    output = _BinaryStdout()

    def fake_exec(path: str, argv: tuple[str, ...], environment: dict[str, str]) -> None:
        observed["path"] = path
        observed["argv"] = tuple(argv)
        observed["environment"] = dict(environment)
        raise OSError("synthetic service token must never be returned")

    with monkeypatch.context() as child_scope:
        child_scope.setattr(
            os,
            "environ",
            {
                CHILD_TOKEN_FILE_ENV: str(token_file),
                "INFISICAL_TOKEN": "coordinator-token-must-not-reach-child",
                "GROQ_API_KEY": "provider-key-must-not-reach-child",
                "AC_DATABASE_URL": "database-must-not-reach-child",
                "PATH": os.environ.get("PATH", ""),
                "PYTHONUTF8": "1",
            },
        )
        child_scope.setattr(os, "execvpe", fake_exec)
        child_scope.setattr(sys, "stdout", output)
        status = child_identity.main(_command())

    assert status == 0
    assert observed["path"] == "infisical"
    provider_argv = observed["argv"]
    assert provider_argv == (
        "infisical",
        "run",
        "--include-imports=false",
        "--expand=false",
        "--silent",
        "--telemetry=false",
        "--log-level=error",
        "--projectId",
        "b421c44e-4599-4394-8df6-758ed8aedfed",
        "--env",
        "dev",
        "--path",
        "/sales-xray-test/groq",
        "--",
        sys.executable,
        "-m",
        "ac_platform.conversation_intelligence.inference_broker_cli",
        "--child",
    )
    child_environment = observed["environment"]
    assert child_environment["INFISICAL_TOKEN"] == "synthetic-child-service-token"  # noqa: S105 - synthetic test value
    assert CHILD_TOKEN_FILE_ENV not in child_environment
    assert "GROQ_API_KEY" not in child_environment
    assert "AC_DATABASE_URL" not in child_environment
    assert child_environment["INFISICAL_API_URL"] == "https://app.infisical.com"
    assert child_environment["INFISICAL_DISABLE_UPDATE_CHECK"] == "true"
    header, payload = _frame_from(output)
    assert payload == b""
    assert header == {
        "schema": BROKER_SCHEMA,
        "kind": "response",
        "status": "error",
        "error_code": "broker_service_identity_unavailable",
        "payload_len": 0,
    }
    assert b"synthetic-child-service-token" not in output.buffer.getvalue()


def test_missing_or_malformed_identity_file_returns_stable_redacted_frame(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    missing = tmp_path / "missing-token"
    malformed = tmp_path / "malformed-token"
    malformed.write_text(
        "AC_DATABASE_URL=postgresql://coordinator-secret\nGROQ_API_KEY=provider-secret\n",
        encoding="ascii",
    )
    if os.name == "posix":
        malformed.chmod(0o600)

    for reference, expected in (
        (missing, "broker_service_identity_unavailable"),
        (malformed, "broker_service_identity_file_invalid"),
    ):
        output = _BinaryStdout()
        with monkeypatch.context() as child_scope:
            child_scope.setattr(
                os,
                "environ",
                {CHILD_TOKEN_FILE_ENV: str(reference), "PATH": os.environ.get("PATH", "")},
            )
            child_scope.setattr(sys, "stdout", output)
            assert child_identity.main(_command()) == 0
        header, payload = _frame_from(output)
        assert payload == b""
        assert header["error_code"] == expected
        encoded = output.buffer.getvalue()
        assert b"coordinator-secret" not in encoded
        assert b"provider-secret" not in encoded
        assert str(reference).encode() not in encoded


def test_identity_file_rejects_symlinks_and_multiline_values(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "target-token"
    target.write_text("synthetic-child-service-token", encoding="ascii")
    if os.name == "posix":
        target.chmod(0o600)
    symlink = tmp_path / "token-link"
    linked_parent = tmp_path / "linked-parent"
    linked_parent.mkdir()
    nested_token = linked_parent / "nested-token"
    nested_token.write_text("synthetic-child-service-token", encoding="ascii")
    if os.name == "posix":
        nested_token.chmod(0o600)
    parent_link = tmp_path / "parent-link"
    try:
        symlink.symlink_to(target)
        parent_link.symlink_to(linked_parent, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation is unavailable on this Windows runner")

    multiline = tmp_path / "multiline-token"
    multiline.write_text("synthetic-child-service-token\nsecond-line", encoding="ascii")
    if os.name == "posix":
        multiline.chmod(0o600)
    for reference in (symlink, parent_link / nested_token.name, multiline):
        output = _BinaryStdout()
        with monkeypatch.context() as child_scope:
            child_scope.setattr(
                os,
                "environ",
                {CHILD_TOKEN_FILE_ENV: str(reference), "PATH": os.environ.get("PATH", "")},
            )
            child_scope.setattr(sys, "stdout", output)
            assert child_identity.main(_command()) == 0
        header, _ = _frame_from(output)
        assert header["error_code"] == "broker_service_identity_file_invalid"

    # Synthetic metadata proof keeps this boundary explicit on platforms
    # where creating a hard link is unavailable to the test runner.
    real_fstat = os.fstat

    def fake_fstat(file_descriptor: int) -> SimpleNamespace:
        metadata = real_fstat(file_descriptor)
        return SimpleNamespace(
            st_mode=stat.S_IFREG | 0o600,
            st_nlink=2,
            st_size=metadata.st_size,
        )

    monkeypatch.setattr(child_identity.os, "fstat", fake_fstat)
    with pytest.raises(
        child_identity.InferenceBrokerError,
        match="broker_service_identity_file_invalid",
    ):
        child_identity._read_token_file(target)


def test_launcher_missing_identity_fails_closed_before_process_runner() -> None:
    launcher = InfisicalLauncher(
        executable="infisical",
        provider_id="groq",
        project_ref="sales-xray-test",
        environment_ref="dev",
        secret_path_ref="/sales-xray-test/groq",  # noqa: S106 - synthetic path reference
    )
    with pytest.raises(ValueError, match="service token file reference required"):
        launcher.argv(sys.executable)
    with pytest.raises(ValueError, match="service token file reference required"):
        launcher.child_environment()


@pytest.mark.asyncio
async def test_real_child_identity_failure_is_bounded_and_redacted(tmp_path: Path) -> None:
    missing = tmp_path / "missing-token"
    environment = {
        "PYTHONUTF8": "1",
        "PYTHONPATH": str(PACKAGE_ROOT),
        CHILD_TOKEN_FILE_ENV: str(missing),
    }
    for name in (
        "PATH",
        "SystemRoot",
        "WINDIR",
        "TEMP",
        "TMP",
        "TMPDIR",
        "HOME",
        "USERPROFILE",
        "LOCALAPPDATA",
        "APPDATA",
    ):
        if name in os.environ:
            environment[name] = os.environ[name]
    output = await _run_subprocess(
        (
            sys.executable,
            "-m",
            "ac_platform.conversation_intelligence.child_identity",
            *_command(),
        ),
        b"",
        environment=environment,
        # Windows may cold-start the interpreter and import asyncio lazily;
        # timeout behavior itself is covered by the broker timeout tests.
        timeout_seconds=10.0,
        max_output_bytes=64 * 1024,
    )
    header, payload = _decode_frame(output, maximum_payload=64 * 1024)
    assert payload == b""
    assert header["error_code"] == "broker_service_identity_unavailable"
    assert str(missing).encode() not in output
