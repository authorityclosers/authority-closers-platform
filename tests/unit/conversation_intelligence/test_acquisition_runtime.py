"""Acquisition is optional; missing config cannot disable the existing API."""

from __future__ import annotations

import secrets
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ac_platform.application.settings import Settings
from ac_platform.http.conversation_acquisition_runtime import _challenge_secret


@pytest.mark.parametrize("enabled", [False, True])
def test_missing_guest_config_preserves_core_api(
    monkeypatch: pytest.MonkeyPatch, enabled: bool
) -> None:
    import ac_platform.http.app as app_module

    settings = Settings(
        _env_file=None,
        environment="test",
        sales_xray_app_url="https://salesxray.example.test",
        sales_xray_acquisition_enabled=enabled,
    )
    monkeypatch.setattr(app_module, "settings", settings)
    application = app_module.create_app()
    assert application.state.sales_xray_acquisition_configured is False
    paths = application.openapi()["paths"]
    assert "/v1/learning/home" in paths
    assert "/v1/conversation/acquisition/submissions/{submission_id}/source" not in paths
    with TestClient(application, base_url="https://salesxray.example.test") as client:
        entry = client.get("/v1/conversation/acquisition/entry")
        assert entry.status_code == 200
        assert entry.json() == {
            "enabled": False,
            "site_key": None,
            "challenge_action": None,
            "policy_revision": None,
            "allowance_seconds": None,
        }


def test_narrow_challenge_file_is_redacted_and_never_reads_env_bundle(tmp_path: Path) -> None:
    path = tmp_path / "challenge.secret"
    value = secrets.token_urlsafe(32)
    path.write_text(value + "\n", encoding="ascii")
    path.chmod(0o600)
    secret = _challenge_secret(path)
    assert secret.get_secret_value() == value
    assert value not in repr(secret)
    path.write_text("TURNSTILE_SECRET=" + value, encoding="ascii")
    with pytest.raises(ValueError, match="^acquisition_challenge_unavailable$") as caught:
        _challenge_secret(path)
    assert value not in str(caught.value)


@pytest.mark.parametrize("kind", ["absent", "oversized", "directory", "repository", "relative"])
def test_secret_reference_rejects_unsafe_or_unavailable_file(tmp_path: Path, kind: str) -> None:
    path = tmp_path / "challenge.secret"
    if kind == "oversized":
        path.write_bytes(b"a" * 259)
        path.chmod(0o600)
    elif kind == "directory":
        path.mkdir()
    elif kind == "repository":
        (tmp_path / ".git").mkdir()
        path.write_bytes(b"synthetic-placeholder-only")
        path.chmod(0o600)
    elif kind == "relative":
        path = Path("unconfigured.secret")
    with pytest.raises(ValueError, match="^acquisition_challenge_unavailable$"):
        _challenge_secret(path)
