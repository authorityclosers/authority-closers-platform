"""Prepare only fictional, digest-bound artifacts in temporary directories."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from tests.unit.test_prepare_sales_xray_native_activation import (
    _MODULE,
    _patch_target_native,
    _write_source_activation,
)


def _source_for_environment(tmp_path: Path, environment: str) -> Path:
    source, _ = _write_source_activation(tmp_path)
    descriptor = json.loads(source.read_bytes())
    env_path = Path(descriptor["compose_env_file"])
    env = _MODULE._parse_env(env_path.read_bytes())
    for name in ("approval", "service_config"):
        path = Path(descriptor[f"{name}_file"])
        payload = json.loads(path.read_bytes())
        payload["environment"] = environment
        if name == "service_config":
            payload["sales_xray_approval_sha256"] = descriptor["approval_sha256"]
        raw = _MODULE._json_bytes(payload)
        path.write_bytes(raw)
        descriptor[f"{name}_sha256"] = hashlib.sha256(raw).hexdigest()
    env["AC_XRAY_APPROVAL_SHA256"] = descriptor["approval_sha256"]
    env["AC_XRAY_SERVICE_SHA256"] = descriptor["service_config_sha256"]
    env_raw = _MODULE._env_bytes(env)
    env_path.write_bytes(env_raw)
    descriptor.update(
        environment=environment,
        helper_unit=f"ac-sales-xray-native-{environment}.service",
        compose_env_sha256=hashlib.sha256(env_raw).hexdigest(),
    )
    source.write_bytes(_MODULE._json_bytes(descriptor))
    return source


@pytest.mark.parametrize("environment", ["development", "staging", "production", "test", "local"])
def test_prepare_preserves_hosted_environment_and_source_artifacts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, environment: str
) -> None:
    source = _source_for_environment(tmp_path, environment)
    original = {path: path.read_bytes() for path in source.parent.iterdir()}
    target = "2" * 40
    _patch_target_native(monkeypatch, target)
    output = tmp_path / "prepared"
    arguments = {
        "source_activation": source,
        "target_release_id": target,
        "native_artifact_manifest": tmp_path / "native.json",
        "native_artifact_sha256": "a" * 64,
        "output_dir": output,
    }
    if environment in {"test", "local"}:
        with pytest.raises(_MODULE.PrepareError, match="source activation environment is invalid"):
            _MODULE.prepare(**arguments)
        assert not output.exists()
    else:
        result = _MODULE.prepare(**arguments)
        activation, _, _, service, _, approval, _ = _MODULE._load_source(Path(result["activation"]))
        assert result["environment"] == environment
        assert activation["environment"] == service["environment"] == approval["environment"]
        assert activation["environment"] == environment
        assert activation["release_id"] == service["release_id"] == target
        assert result["provider_calls"] == 0
        assert result["approval_replaced"] is False
    assert all(path.read_bytes() == raw for path, raw in original.items())
