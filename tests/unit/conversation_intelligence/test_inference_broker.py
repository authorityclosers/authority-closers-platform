"""Synthetic tests for the fixed, bounded inference subprocess boundary."""

from __future__ import annotations

import asyncio
import hashlib
import os
import sys
from dataclasses import replace
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
from ac_platform.conversation_intelligence.providers import ProviderResult


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
        {"GEMINI_API_KEY", "GROQ_API_KEY", "ELEVENLABS_API_KEY"}
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
        runner = FakeRunner(lambda _header, payload, change=change: _response(
            reservation, payload, raw, **change
        ))
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

    monkeypatch.setenv("GEMINI_API_KEY", "synthetic-child-key")
    monkeypatch.setenv("GROQ_API_KEY", "must-not-be-read")
    monkeypatch.setenv("ELEVENLABS_API_KEY", "must-not-be-read")
    monkeypatch.setattr(
        "ac_platform.conversation_intelligence.inference_broker.BoundedProviders", FakeProviders
    )

    output = _child_execute(frame)
    result = await ProcessInferenceBroker(
        python_executable=sys.executable,
        runner=FakeRunner(lambda _header, _payload: output),
    ).execute(reservation, body)
    assert result.raw_json == raw
    assert observed["credentials"] == {"gemini": "synthetic-child-key"}
    assert observed["body"] == {"input": "synthetic"}
    assert "must-not-be-read" not in repr(output)
    assert "GROQ_API_KEY" not in os.environ
    assert "ELEVENLABS_API_KEY" not in os.environ


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
        "pathlib.Path(sys.argv[1]).write_text(\"leaked\")',sys.argv[1]])\n"
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
        "pathlib.Path(sys.argv[1]).write_text(\"leaked\")',sys.argv[1]])\n"
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
    launcher = InfisicalLauncher(
        executable="infisical",
        provider_id="gemini",
        project_ref="sales-xray",
        environment_ref="test",
        secret_path_ref="/provider-runtime/gemini",  # noqa: S106 - synthetic reference, never a value
    )
    argv = launcher.argv(sys.executable)
    assert argv[:13] == (
        "infisical",
        "run",
        "--include-imports=false",
        "--expand=false",
        "--silent",
        "--telemetry=false",
        "--log-level=error",
        "--projectId",
        "sales-xray",
        "--env",
        "test",
        "--path",
        "/provider-runtime/gemini",
    )
    assert argv[-4:] == (sys.executable, "-m", BROKER_MODULE, "--child")
    with pytest.raises(ValueError):
        InfisicalLauncher(
            "infisical", "gemini", "project?token=secret", "test", "/provider-runtime/gemini"
        )
    with pytest.raises(ValueError):
        InfisicalLauncher("infisical", "gemini", "project", "test", "sk-live-secret")


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
