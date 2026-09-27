from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "packages" / "python"))

from ac_platform.conversation_intelligence.native_runtime import NativeRuntimeError  # noqa: E402

SPEC = importlib.util.spec_from_file_location(
    "hosted_native_linux_smoke", ROOT / "scripts" / "test_hosted_native_linux.py"
)
if SPEC is None or SPEC.loader is None:
    raise ImportError("hosted native smoke script is unavailable")
SMOKE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = SMOKE
SPEC.loader.exec_module(SMOKE)

IMAGE = "sha256:" + "a" * 64


class _FakeRuntime:
    calls: list[tuple[str, str]] = []

    def __init__(
        self,
        socket_path: Path,
        *,
        workspace_root: Path,
        expected_image_ref: str,
    ) -> None:
        assert socket_path
        self.workspace_root = workspace_root
        self.expected_image_ref = expected_image_ref

    def _check(self, operation: str, source: Path, outdir: Path) -> None:
        self.calls.append((operation, self.expected_image_ref))
        if self.expected_image_ref != IMAGE:
            raise NativeRuntimeError("native_runtime_image_not_immutable")
        outdir.mkdir(mode=0o700)
        (outdir / "checkpoint.json").write_text("{}\n", encoding="utf-8")
        if operation == "inspect":
            (outdir / "features.aaf").write_bytes(b"synthetic")

    def validate_source(
        self, source: Path, outdir: Path, *, job_id: UUID, rate: int
    ) -> dict[str, object]:
        assert job_id
        assert rate == 16000
        self._check("validate", source, outdir)
        return {
            "schema": "ac.sales-xray.source-validation/1",
            "source_sha256": SMOKE.hashlib.sha256(source.read_bytes()).hexdigest(),
            "source_bytes": source.stat().st_size,
            "media_duration_ms": 1000,
            "decoded": {"sample_count": 16000, "channels": 1},
        }

    def inspect(self, source: Path, outdir: Path, *, job_id: UUID, rate: int) -> dict[str, object]:
        assert job_id
        assert rate == 16000
        self._check("inspect", source, outdir)
        return {
            "source_sha256": SMOKE.hashlib.sha256(source.read_bytes()).hexdigest(),
            "source_bytes": source.stat().st_size,
            "media_duration_ms": 1000,
            "timebase": {"rate": 16000},
            "native_receipt": {"rows": 100},
            "feature_sha256": "b" * 64,
        }


def _run_smoke(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, runtime_type: type[_FakeRuntime] = _FakeRuntime
) -> SimpleNamespace:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    receipt = tmp_path / "receipt.json"
    monkeypatch.setattr(SMOKE.sys, "platform", "linux")
    monkeypatch.setattr(SMOKE.os, "getuid", lambda: 10001, raising=False)
    monkeypatch.setattr(SMOKE.os, "getgid", lambda: 10001, raising=False)
    monkeypatch.setattr(SMOKE, "SocketNativeRuntime", runtime_type)
    monkeypatch.setattr(SMOKE, "NativeUploadPreflight", None)
    monkeypatch.setattr(
        SMOKE.sys,
        "argv",
        [
            "test_hosted_native_linux.py",
            "--socket",
            str(tmp_path / "native.sock"),
            "--workspace-root",
            str(workspace),
            "--image-ref",
            IMAGE,
            "--receipt",
            str(receipt),
        ],
    )
    status = SMOKE.main()
    return SimpleNamespace(status=status, receipt=receipt, workspace=workspace)


def test_smoke_exercises_validate_inspect_and_image_mismatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _FakeRuntime.calls = []
    result = _run_smoke(tmp_path, monkeypatch)

    assert result.status == 0
    payload = json.loads(result.receipt.read_text(encoding="utf-8"))
    assert payload["validated"] is True
    assert payload["inspected"] is True
    assert payload["upload_preflight_measured"] is False
    assert payload["wrong_image_rejected"] is True
    assert payload["native_runs"] == 3
    assert _FakeRuntime.calls == [
        ("validate", IMAGE),
        ("inspect", IMAGE),
        ("validate", "sha256:" + "0" * 64),
        ("inspect", "sha256:" + "0" * 64),
        ("inspect", IMAGE),
    ]


def test_smoke_rejects_a_malformed_validate_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class MalformedRuntime(_FakeRuntime):
        def validate_source(
            self, source: Path, outdir: Path, **kwargs: object
        ) -> dict[str, object]:
            self._check("validate", source, outdir)
            return {"schema": "ac.sales-xray.signal-checkpoint/1"}

    result = _run_smoke(tmp_path, monkeypatch, MalformedRuntime)

    assert result.status == 1
    assert not result.receipt.exists()
