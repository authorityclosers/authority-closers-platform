from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_SCRIPT = (
    Path(__file__).parents[2]
    / "infra"
    / "application"
    / "scripts"
    / "prepare-sales-xray-native-activation.py"
)
_SPEC = importlib.util.spec_from_file_location("prepare_sales_xray_native_activation", _SCRIPT)
assert _SPEC is not None and _SPEC.loader is not None
_MODULE = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = _MODULE
_SPEC.loader.exec_module(_MODULE)


def test_prepare_rejects_native_artifact_from_different_release(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    target_release = "a" * 40
    descriptor = {"environment": "staging"}
    env: dict[str, str] = {}
    service: dict[str, object] = {}
    approval: dict[str, object] = {}

    monkeypatch.setattr(
        _MODULE,
        "_load_source",
        lambda _path: (descriptor, b"", env, service, b"", approval, b""),
    )
    monkeypatch.setattr(
        _MODULE,
        "_load_native_manifest",
        lambda _path, _digest: ("b" * 40, "sha256:" + "1" * 64, "sha256:" + "2" * 64),
    )

    with pytest.raises(
        _MODULE.PrepareError,
        match="native artifact source commit differs from target release",
    ):
        _MODULE.prepare(
            source_activation=tmp_path / "source.json",
            target_release_id=target_release,
            native_artifact_manifest=tmp_path / "native.json",
            native_artifact_sha256="c" * 64,
            output_dir=tmp_path / "output",
        )

    assert not (tmp_path / "output").exists()
