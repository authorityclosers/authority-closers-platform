"""The worker reads pinned references and a DB-only credential, never API env."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from ac_platform.conversation_intelligence.service_config import (
    load_database_url,
    load_service_config,
    verify_installed_release,
)


def manifest(tmp_path: Path) -> dict[str, Any]:
    return {
        "schema_version": "ac.sales_xray.worker_service/1",
        "environment": "staging",
        "release_id": "a" * 40,
        "operations_tenant_id": "10000000-0000-4000-8000-000000000001",
        "sales_xray_approval_path": str(tmp_path / "approval.json"),
        "sales_xray_approval_sha256": "b" * 64,
        "sales_xray_storage_root": str(tmp_path / "storage"),
        "sales_xray_scratch_root": str(tmp_path / "scratch"),
        "database_url_file": str(tmp_path / "db-url"),
        "native_socket_path": str(tmp_path / "native" / "worker.sock"),
        "native_image_ref": "sha256:" + "c" * 64,
        "providers": [
            {
                "credential_ref": "ref:credential/groq/v1",
                "provider_id": "groq",
                "executable": str(tmp_path / "infisical"),
                "project_ref": "sales-xray-test",
                "environment_ref": "dev",
                "secret_path_ref": "/sales-xray-test/groq",
                "token_file_ref": str(tmp_path / "groq-token"),
            }
        ],
    }


def write_config(tmp_path: Path, value: dict[str, Any]) -> tuple[Path, str]:
    path = tmp_path / "service.json"
    raw = json.dumps(value).encode()
    path.write_bytes(raw)
    path.chmod(0o600)
    return path, hashlib.sha256(raw).hexdigest()


def test_configuration_check_reads_no_credential_or_dotenv(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AC_DATABASE_URL", "must-not-be-read")
    monkeypatch.setenv("GROQ_API_KEY", "synthetic-must-not-be-read")
    path, digest = write_config(tmp_path, manifest(tmp_path))
    config = load_service_config(path, digest)
    assert config.environment == "staging"
    assert not Path(config.database_url_file).exists()
    assert not Path(config.providers[0].token_file_ref).exists()
    marker = tmp_path / "release"
    marker.write_text(config.release_id + "\n")
    marker.chmod(0o444)
    verify_installed_release(config, marker)
    mismatch = tmp_path / "wrong-release"
    mismatch.write_text("c" * 40 + "\n")
    mismatch.chmod(0o444)
    with pytest.raises(ValueError, match="worker_release_mismatch"):
        verify_installed_release(config, mismatch)


@pytest.mark.parametrize("change", ["tamper", "duplicate", "unexpected", "local", "alias"])
def test_rejects_modified_or_ambiguous_configuration(tmp_path: Path, change: str) -> None:
    value = manifest(tmp_path)
    if change == "unexpected":
        value["api_key"] = "synthetic-not-a-credential"
    elif change == "local":
        value["environment"] = "local"
    elif change == "alias":
        value["providers"][0]["token_file_ref"] = value["database_url_file"]
    path, digest = write_config(tmp_path, value)
    if change == "tamper":
        path.write_bytes(path.read_bytes() + b" ")
    elif change == "duplicate":
        raw = path.read_bytes().replace(
            b'"environment": "staging"', b'"environment":"production","environment":"staging"'
        )
        path.write_bytes(raw)
        digest = hashlib.sha256(raw).hexdigest()
    with pytest.raises(ValueError, match="^worker_config_invalid$"):
        load_service_config(path, digest)


@pytest.mark.parametrize("field", ["sales_xray_storage_root", "sales_xray_scratch_root"])
def test_rejects_credentials_inside_audio_storage(tmp_path: Path, field: str) -> None:
    value = manifest(tmp_path)
    value["providers"][0]["token_file_ref"] = str(Path(value[field]) / "token")
    with pytest.raises(ValueError, match="^worker_config_invalid$"):
        load_service_config(*write_config(tmp_path, value))


@pytest.mark.parametrize("control", [None, "", "not-a-uuid", 123])
def test_worker_requires_an_explicit_canonical_operations_tenant(
    tmp_path: Path, control: Any
) -> None:
    value = manifest(tmp_path)
    if control is None:
        value.pop("operations_tenant_id")
    else:
        value["operations_tenant_id"] = control
    with pytest.raises(ValueError, match="^worker_config_invalid$"):
        load_service_config(*write_config(tmp_path, value))


def test_database_read_uses_only_bounded_external_file_and_redacts_errors(tmp_path: Path) -> None:
    path = tmp_path / "database-url"
    # Synthetic credential exercises URL handling; no production service is contacted.
    path.write_text("postgresql+psycopg://ac_runtime:synthetic-test-value@db/ac_platform")
    path.chmod(0o600)
    url = load_database_url(path)
    assert url.username == "ac_runtime"
    assert url.host == "db"
    path.write_text("postgresql+psycopg://postgres:synthetic-test-value@db/ac_platform")
    with pytest.raises(ValueError) as caught:
        load_database_url(path)
    assert str(caught.value) == "worker_database_configuration_invalid"
    assert "synthetic-test-value" not in str(caught.value)


def test_oversized_config_fails_before_parsing(tmp_path: Path) -> None:
    path = tmp_path / "service.json"
    path.write_bytes(b" " * (65536 + 1))
    path.chmod(0o600)
    with pytest.raises(ValueError, match="^worker_config_invalid$"):
        load_service_config(path, hashlib.sha256(path.read_bytes()).hexdigest())
