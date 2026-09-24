"""Synthetic tests for the fixed, bounded inference subprocess boundary."""

from __future__ import annotations

import asyncio
import hashlib
import os
import sys
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from ac_platform.conversation_intelligence.checkpoints import SourceBinding, canonical
from ac_platform.conversation_intelligence.entitlements import (
    ExecutionPermission,
    Quote,
    Reservation,
)
from ac_platform.conversation_intelligence.inference_broker import (
    BROKER_MODULE,
    BROKER_SCHEMA,
    CHILD_IDENTITY_MODULE,
    CHILD_TOKEN_FILE_ENV,
    BrokerLimits,
    InferenceBrokerError,
    InfisicalLauncher,
    ProcessInferenceBroker,
    _child_execute,
    _decode_frame,
    _encode_frame,
    _request_header,
    _run_subprocess,
)
from ac_platform.conversation_intelligence.providers import ProviderError, ProviderResult


def _reservation(payload: bytes, *, provider: str = "gemini") -> Reservation:
    digest = hashlib.sha256(payload).hexdigest()
    model = "gemini-2.5-flash" if provider == "gemini" else "openai/gpt-oss-120b"
    quote = Quote(
        "quote-1",
        SourceBinding("tenant-1", "recording-1", digest, "source-1"),
        "account-1",
        "scope-1",
        provider,
        model,
        "recipe-1",
        "extract_context_evidence",
        digest,
        "privacy-1",
        "permission-1",
        "terms-1",
        "retention-1",
        "professional-1",
        "pricing-zero",
        0,
        0,
        100,
        300,
    )
    return Reservation(
        "reservation-1",
        quote,
        ExecutionPermission("authority-1", quote.fingerprint, "owner", 300),
        "in_flight",
        "attempt-1",
    )


def _response(
    reservation: Reservation,
    payload: bytes,
    raw_json: bytes,
    **changes: Any,
) -> bytes:
    response_sha = hashlib.sha256(raw_json).hexdigest()
    header: dict[str, Any] = {
        "schema": BROKER_SCHEMA,
        "kind": "response",
        "status": "ok",
        "provider": reservation.quote.provider_id,
        "model": reservation.quote.provider_model,
        "request_id": "synthetic-request-1",
        "input_sha256": hashlib.sha256(payload).hexdigest(),
        "response_sha256": response_sha,
        "payload_len": len(raw_json),
        "usage": {"total_tokens": 3},
    }
    header.update(changes)
    return _encode_frame(header, raw_json)


class FakeRunner:
    def __init__(self, response_factory):
        self.response_factory = response_factory
        self.calls: list[tuple[tuple[str, ...], bytes, dict[str, str]]] = []

    async def run(self, argv, request, *, environment, timeout_seconds, max_output_bytes):
        del timeout_seconds, max_output_bytes
        self.calls.append((tuple(argv), request, dict(environment)))
        header, payload = _decode_frame(request, maximum_payload=32 * 1024 * 1024)
        return self.response_factory(header, payload)


@pytest.mark.asyncio
async def test_execute_binds_route_and_deserializes_only_raw_response() -> None:
    body = canonical({"model": "synthetic", "input": "private source stays in the pipe"})
    reservation = _reservation(body)
    raw = b'{"answer":"synthetic"}'
    runner = FakeRunner(lambda _header, payload: _response(reservation, payload, raw))

    result = await ProcessInferenceBroker(
        python_executable=sys.executable,
        runner=runner,
    ).execute(reservation, body)

    assert result.provider == "gemini"
    assert result.model == "gemini-2.5-flash"
    assert result.input_sha256 == hashlib.sha256(body).hexdigest()
    assert result.raw_json == raw
    assert result.data == {"answer": "synthetic"}
    assert BROKER_MODULE in runner.calls[0][0]
    assert set(runner.calls[0][2]).isdisjoint(
        {"GEMINI_API_KEY", "GROQ_API_KEY", "OPENAI_API_KEY", "ELEVENLABS_API_KEY"}
    )


@pytest.mark.asyncio
async def test_execute_rejects_changed_input_before_child_launch() -> None:
    body = canonical({"input": "original"})
    reservation = _reservation(body)
    runner = FakeRunner(lambda _header, payload: _response(reservation, payload, b"{}"))

    with pytest.raises(InferenceBrokerError, match="broker_input_sha256_mismatch"):
        await ProcessInferenceBroker(python_executable=sys.executable, runner=runner).execute(
            reservation, canonical({"input": "changed"})
        )
    assert runner.calls == []


@pytest.mark.asyncio
async def test_launcher_passes_only_token_file_reference_to_sterile_child_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    body = canonical({"input": "synthetic"})
    reservation = _reservation(body, provider="groq")
    token_file = (Path.cwd() / "synthetic" / "groq-token").resolve()
    launcher = InfisicalLauncher(
        executable="infisical",
        provider_id="groq",
        project_ref="sales-xray-test",
        environment_ref="dev",
        secret_path_ref="/sales-xray-test/groq",  # noqa: S106 - synthetic path reference
        token_file_ref=token_file,
    )
    runner = FakeRunner(lambda _header, payload: _response(reservation, payload, b"{}"))
    monkeypatch.setenv("INFISICAL_TOKEN", "coordinator-token-must-not-reach-child")
    monkeypatch.setenv("GROQ_API_KEY", "provider-key-must-not-reach-parent-child")
    monkeypatch.setenv("AC_DATABASE_URL", "database-must-not-reach-parent-child")

    await ProcessInferenceBroker(
        python_executable=sys.executable,
        infisical=launcher,
        runner=runner,
    ).execute(reservation, body)

    argv, _, environment = runner.calls[0]
    assert argv[:4] == (sys.executable, "-m", CHILD_IDENTITY_MODULE, "--child")
    assert environment[CHILD_TOKEN_FILE_ENV] == str(token_file)
    assert "INFISICAL_TOKEN" not in environment
    assert "GROQ_API_KEY" not in environment
    assert "AC_DATABASE_URL" not in environment


@pytest.mark.asyncio
async def test_execute_caps_input_without_echoing_source() -> None:
    body = canonical({"input": "synthetic"})
    reservation = _reservation(body)
    runner = FakeRunner(lambda _header, payload: _response(reservation, payload, b"{}"))
    broker = ProcessInferenceBroker(
        python_executable=sys.executable,
        limits=BrokerLimits(max_input_bytes=len(body) - 1),
        runner=runner,
    )

    with pytest.raises(InferenceBrokerError, match="broker_input_too_large") as caught:
        await broker.execute(reservation, body)
    assert "synthetic" not in repr(caught.value)
    assert runner.calls == []


@pytest.mark.asyncio
async def test_response_route_digest_and_duplicate_data_are_untrusted() -> None:
    body = canonical({"input": "synthetic"})
    reservation = _reservation(body)
    raw = b'{"answer":"from raw"}'

    cases = [
        {"provider": "other"},
        {"response_sha256": "a" * 64},
        {"data": {"answer": "untrusted duplicate"}},
    ]
    for change in cases:
        runner = FakeRunner(
            lambda _header, payload, change=change: _response(reservation, payload, raw, **change)
        )
        with pytest.raises(InferenceBrokerError):
            await ProcessInferenceBroker(python_executable=sys.executable, runner=runner).execute(
                reservation, body
            )


@pytest.mark.asyncio
async def test_child_reads_only_the_exact_provider_credential_and_returns_raw_frame(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    body = canonical({"input": "synthetic"})
    reservation = _reservation(body)
    frame = _encode_frame(_request_header(reservation, body), body)
    observed: dict[str, Any] = {}
    raw = b'{"choices":[]}'

    class FakeProviders:
        def __init__(self, *, credentials, authorize):
            observed["credentials"] = credentials
            observed["authorize"] = authorize
            # Capture the adapter boundary itself: the provider adapter must
            # never observe Infisical identity or launcher metadata.
            observed["environment"] = dict(os.environ)

        def generate(self, current, request_body):
            observed["body"] = request_body
            return ProviderResult(
                "gemini",
                "gemini-2.5-flash",
                "child-request",
                hashlib.sha256(raw).hexdigest(),
                raw,
                {"choices": []},
                {"total_tokens": 1},
                hashlib.sha256(body).hexdigest(),
            )

    parent_environment_id = id(os.environ)
    parent_environment_names = frozenset(os.environ)
    # This entry point scrubs its disposable child environment. Invoking it in
    # pytest must never unset variables in the actual test-runner process.
    with monkeypatch.context() as child_scope:
        child_scope.setattr(
            os,
            "environ",
            {
                "GEMINI_API_KEY": "synthetic-child-key",
                "GROQ_API_KEY": "must-not-be-read",
                "ELEVENLABS_API_KEY": "must-not-be-read",
                "AC_PARENT_SETTING_FIXTURE": "must-not-reach-adapter",
                "INFISICAL_TOKEN": "synthetic-service-token",
                CHILD_TOKEN_FILE_ENV: "synthetic-token-file-reference",
                "INFISICAL_API_URL": "https://app.infisical.com",
                "INFISICAL_DISABLE_UPDATE_CHECK": "true",
                "AC_INFISICAL_PROJECT_ID": "synthetic-launcher-project",
            },
        )
        child_scope.setattr(
            "ac_platform.conversation_intelligence.inference_broker.BoundedProviders", FakeProviders
        )
        output = _child_execute(frame)
        assert "GEMINI_API_KEY" not in os.environ
        assert "GROQ_API_KEY" not in os.environ
        assert "ELEVENLABS_API_KEY" not in os.environ
        assert "AC_PARENT_SETTING_FIXTURE" not in os.environ

    environment_restored = (
        id(os.environ) == parent_environment_id
        and frozenset(os.environ) == parent_environment_names
    )
    assert environment_restored, "Child fixture must preserve the test-runner environment."
    result = await ProcessInferenceBroker(
        python_executable=sys.executable,
        runner=FakeRunner(lambda _header, _payload: output),
    ).execute(reservation, body)
    assert result.raw_json == raw
    assert observed["credentials"] == {"gemini": "synthetic-child-key"}
    assert observed["body"] == {"input": "synthetic"}
    assert observed["environment"] == {}
    assert "must-not-be-read" not in repr(output)


@pytest.mark.parametrize("code", ["provider_http_400", "provider_http_429", "provider_http_503"])
def test_child_preserves_allowlisted_provider_http_error_code(
    monkeypatch: pytest.MonkeyPatch, code: str
) -> None:
    body = canonical({"input": "synthetic"})
    reservation = _reservation(body)
    frame = _encode_frame(_request_header(reservation, body), body)

    class FailingProviders:
        def __init__(self, *, credentials, authorize):
            del credentials, authorize

        def generate(self, current, request_body):
            del current, request_body
            raise ProviderError(code)

    with monkeypatch.context() as child_scope:
        child_scope.setattr(
            "ac_platform.conversation_intelligence.inference_broker.BoundedProviders",
            FailingProviders,
        )
        child_scope.setattr(os, "environ", {"GEMINI_API_KEY": "synthetic-child-key"})
        output = _child_execute(frame)

    header, payload = _decode_frame(output, maximum_payload=4 * 1024 * 1024)
    assert payload == b""
    assert header["status"] == "error"
    assert header["error_code"] == code


def test_child_collapses_unallowlisted_provider_error_without_echoing_remote_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    body = canonical({"input": "synthetic"})
    reservation = _reservation(body)
    frame = _encode_frame(_request_header(reservation, body), body)
    malicious = "provider_http_429 raw provider body bearer sk_live_child_secret"

    class FailingProviders:
        def __init__(self, *, credentials, authorize):
            del credentials, authorize

        def generate(self, current, request_body):
            del current, request_body
            raise ProviderError(malicious)

    with monkeypatch.context() as child_scope:
        child_scope.setattr(
            "ac_platform.conversation_intelligence.inference_broker.BoundedProviders",
            FailingProviders,
        )
        child_scope.setattr(os, "environ", {"GEMINI_API_KEY": "synthetic-child-key"})
        output = _child_execute(frame)

    header, payload = _decode_frame(output, maximum_payload=4 * 1024 * 1024)
    assert payload == b""
    assert header["status"] == "error"
    assert header["error_code"] == "provider_dispatch_failed"
    assert malicious.encode() not in output
    assert b"sk_live_child_secret" not in output


@pytest.mark.asyncio
async def test_runner_exception_is_stable_and_does_not_echo_secret() -> None:
    body = canonical({"input": "synthetic"})
    reservation = _reservation(body)

    async def failing(*args, **kwargs):
        del args, kwargs
        raise RuntimeError("provider secret synthetic-child-key")

    with pytest.raises(InferenceBrokerError, match="^broker_process_failed$") as caught:
        await ProcessInferenceBroker(python_executable=sys.executable, runner=failing).execute(
            reservation, body
        )
    assert "synthetic-child-key" not in repr(caught.value)


@pytest.mark.asyncio
async def test_real_subprocess_timeout_terminates_and_joins_child() -> None:
    with pytest.raises(InferenceBrokerError, match="^broker_timeout$"):
        await _run_subprocess(
            (sys.executable, "-c", "import time; time.sleep(10)"),
            b"synthetic",
            environment={"PYTHONUTF8": "1"},
            timeout_seconds=0.05,
            max_output_bytes=1024,
        )


@pytest.mark.asyncio
async def test_timeout_kills_wrapper_spawned_descendant(tmp_path) -> None:
    marker = tmp_path / "descendant-would-have-written"
    wrapper = (
        "import subprocess,sys\n"
        "child=subprocess.Popen([sys.executable,'-c',"
        "'import pathlib,sys,time; time.sleep(.5); "
        'pathlib.Path(sys.argv[1]).write_text("leaked")\',sys.argv[1]])\n'
        "child.wait()\n"
    )
    with pytest.raises(InferenceBrokerError, match="^broker_timeout$"):
        await _run_subprocess(
            (sys.executable, "-c", wrapper, str(marker)),
            b"start",
            environment={"PYTHONUTF8": "1"},
            timeout_seconds=0.05,
            max_output_bytes=1024,
        )
    await asyncio.sleep(0.7)
    assert not marker.exists()


@pytest.mark.asyncio
async def test_real_subprocess_cancellation_joins_child() -> None:
    task = asyncio.create_task(
        _run_subprocess(
            (sys.executable, "-c", "import time; time.sleep(10)"),
            b"synthetic",
            environment={"PYTHONUTF8": "1"},
            timeout_seconds=5.0,
            max_output_bytes=1024,
        )
    )
    await asyncio.sleep(0.05)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert task.done()


@pytest.mark.asyncio
async def test_cancellation_kills_wrapper_spawned_descendant(tmp_path) -> None:
    marker = tmp_path / "cancelled-descendant-would-have-written"
    wrapper = (
        "import subprocess,sys\n"
        "sys.stdin.buffer.read()\n"
        "child=subprocess.Popen([sys.executable,'-c',"
        "'import pathlib,sys,time; time.sleep(.5); "
        'pathlib.Path(sys.argv[1]).write_text("leaked")\',sys.argv[1]])\n'
        "child.wait()\n"
    )
    task = asyncio.create_task(
        _run_subprocess(
            (sys.executable, "-c", wrapper, str(marker)),
            b"start",
            environment={"PYTHONUTF8": "1"},
            timeout_seconds=5.0,
            max_output_bytes=1024,
        )
    )
    await asyncio.sleep(0.05)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    await asyncio.sleep(0.7)
    assert not marker.exists()


@pytest.mark.asyncio
async def test_repeated_cancellation_waits_for_process_tree_join() -> None:
    task = asyncio.create_task(
        _run_subprocess(
            (
                sys.executable,
                "-c",
                "import signal,time; "
                "signal.signal(signal.SIGTERM, lambda *_: None); time.sleep(10)",
            ),
            b"start",
            environment={"PYTHONUTF8": "1"},
            timeout_seconds=5.0,
            max_output_bytes=1024,
        )
    )
    await asyncio.sleep(0.05)
    task.cancel()
    await asyncio.sleep(0)
    # The first cancellation starts a deliberately non-immediate cleanup;
    # this second one must not release the caller before the kill/join finishes.
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert task.done()


@pytest.mark.asyncio
async def test_input_write_is_inside_whole_execution_deadline() -> None:
    with pytest.raises(InferenceBrokerError, match="^broker_timeout$"):
        await _run_subprocess(
            (sys.executable, "-c", "import time; time.sleep(10)"),
            b"x" * 1_000_000,
            environment={"PYTHONUTF8": "1"},
            timeout_seconds=0.05,
            max_output_bytes=1024,
        )


def test_infisical_launcher_is_fixed_and_rejects_secret_like_references() -> None:
    token_file = (Path.cwd() / "synthetic" / "infisical-token").resolve()
    launcher = InfisicalLauncher(
        executable="infisical",
        provider_id="gemini",
        project_ref="sales-xray",
        environment_ref="test",
        secret_path_ref="/provider-runtime/gemini",  # noqa: S106 - synthetic reference, never a value
        token_file_ref=token_file,
    )
    argv = launcher.argv(sys.executable)
    assert argv[:4] == (sys.executable, "-m", CHILD_IDENTITY_MODULE, "--child")
    assert argv[4:] == (
        "--infisical-executable",
        "infisical",
        "--project-id",
        "sales-xray",
        "--environment",
        "test",
        "--path",
        "/provider-runtime/gemini",
    )
    assert str(token_file) not in argv
    assert launcher.child_environment() == {CHILD_TOKEN_FILE_ENV: str(token_file)}
    assert launcher.provider_argv(sys.executable)[-4:] == (
        sys.executable,
        "-m",
        BROKER_MODULE,
        "--child",
    )
    with pytest.raises(ValueError):
        InfisicalLauncher(
            "infisical",
            "gemini",
            "project?token=secret",
            "test",
            "/provider-runtime/gemini",
            token_file,
        )
    with pytest.raises(ValueError):
        InfisicalLauncher(
            "infisical", "gemini", "project", "test", "/provider-runtime/gemini", "sk-live-secret"
        )
    with pytest.raises(ValueError, match="service token file reference required"):
        InfisicalLauncher(
            "infisical", "gemini", "project", "test", "/provider-runtime/gemini"
        ).argv(sys.executable)


def test_frame_rejects_truncated_or_oversized_payload() -> None:
    with pytest.raises(InferenceBrokerError, match="^broker_frame_invalid$"):
        _decode_frame(b"\x00\x00", maximum_payload=100)
    frame = _encode_frame({"payload_len": 5}, b"12345")
    with pytest.raises(InferenceBrokerError, match="^broker_frame_invalid$"):
        _decode_frame(frame, maximum_payload=4)


def test_error_response_does_not_accept_credential_shaped_code() -> None:
    frame = _encode_frame(
        {
            "schema": BROKER_SCHEMA,
            "kind": "response",
            "status": "error",
            "error_code": "provider_sk_live_secret",
            "payload_len": 0,
        },
        b"",
    )
    body = canonical({"input": "synthetic"})
    with pytest.raises(InferenceBrokerError, match="^broker_child_failed$"):
        from ac_platform.conversation_intelligence.inference_broker import _decode_response

        _decode_response(frame, _reservation(body), body, maximum_payload=1024)


def test_stale_reservation_is_rejected_without_launch() -> None:
    body = canonical({"input": "synthetic"})
    reservation = _reservation(body)
    stale = replace(reservation, state="reserved", attempt_id=None)
    with pytest.raises(InferenceBrokerError, match="broker_reservation_not_in_flight"):
        _request_header(stale, body)
