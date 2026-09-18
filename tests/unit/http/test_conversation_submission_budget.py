"""The guest upload request cannot outlive its edge-safe admission window."""

from __future__ import annotations

import hashlib
from pathlib import Path
from uuid import uuid4

import pytest

from ac_platform.conversation_intelligence.acquisition_source import (
    NativePreflightTimeout,
    NativeUploadPreflight,
)
from ac_platform.conversation_intelligence.native_runtime import (
    NativeRuntimeError,
    SocketNativeRuntime,
)
from ac_platform.http.conversation_submissions import (
    _MIN_NATIVE_TIMEOUT_SECONDS,
    _preflight_with_deadline,
)

IMAGE = "sha256:" + "a" * 64


def test_socket_preflight_uses_only_remaining_request_budget(tmp_path: Path) -> None:
    def exchange(_: bytes) -> bytes:
        return b"{}"

    runtime = SocketNativeRuntime(
        tmp_path / "native.sock",
        workspace_root=tmp_path,
        expected_image_ref=IMAGE,
        timeout_seconds=750,
        exchange=exchange,
    )
    bounded = _preflight_with_deadline(NativeUploadPreflight(runtime), deadline=100, now=lambda: 35)

    assert isinstance(bounded.runtime, SocketNativeRuntime)
    assert bounded.runtime.timeout_seconds == 65
    assert bounded.runtime._exchange is exchange
    assert runtime.timeout_seconds == 750


def test_expired_request_budget_fails_before_native_call(tmp_path: Path) -> None:
    runtime = SocketNativeRuntime(
        tmp_path / "native.sock",
        workspace_root=tmp_path,
        expected_image_ref=IMAGE,
        exchange=lambda _: b"{}",
    )

    with pytest.raises(NativePreflightTimeout) as error:
        _preflight_with_deadline(
            NativeUploadPreflight(runtime),
            deadline=100,
            now=lambda: 100 - (_MIN_NATIVE_TIMEOUT_SECONDS - 0.1),
        )

    assert error.value.status == 408


def test_native_timeout_is_actionable_before_any_reservation(tmp_path: Path) -> None:
    source = tmp_path / "source.ogg"
    source.write_bytes(b"OggS test source")

    class TimedOutRuntime:
        def inspect(self, *_: object, **__: object) -> dict[str, object]:
            raise NativeRuntimeError("native_runtime_timeout")

        def validate_source(self, *_: object, **__: object) -> dict[str, object]:
            raise NativeRuntimeError("native_runtime_timeout")

    with pytest.raises(NativePreflightTimeout, match="too long to verify") as error:
        digest = hashlib.sha256(source.read_bytes()).hexdigest()
        NativeUploadPreflight(TimedOutRuntime()).measure(source, uuid4(), digest)

    assert error.value.status == 408
