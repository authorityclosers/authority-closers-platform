"""Offline coverage for the usage guard's previously failing token-refresh branch."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import urllib.request
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "infra/watchdog/ac_usage_guard.py"
EXPORT_SHA256 = "d9a6eab0ad5618ed087b4bf92c5d4b29aed3821f740a5b5f8640b39e6aeebb0f"


@pytest.fixture
def guard(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Live usage-guard dependency called")

    monkeypatch.setattr(subprocess, "run", forbidden)
    monkeypatch.setattr(urllib.request, "urlopen", forbidden)
    monkeypatch.setattr(Path, "read_text", forbidden)
    spec = importlib.util.spec_from_file_location("offline_ac_usage_guard", SOURCE)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "time", SimpleNamespace(time=lambda: 10_000.0))
    monkeypatch.setattr(module, "log", Mock())
    return module


def test_source_changes_only_the_missing_subprocess_import():
    source = SOURCE.read_bytes()
    assert source.count(b"import subprocess\n") == 1
    original = source.replace(b"import subprocess\n", b"", 1)
    assert hashlib.sha256(original).hexdigest() == EXPORT_SHA256


@pytest.mark.parametrize("returncode", [0, 1])
def test_refresh_required_runs_existing_subscription_command(guard, monkeypatch, returncode):
    credentials = Mock(return_value=json.dumps({"claudeAiOauth": {"expiresAt": 10_000_000}}))
    monkeypatch.setattr(guard, "CREDENTIALS", SimpleNamespace(read_text=credentials))
    refresh = Mock(return_value=SimpleNamespace(returncode=returncode, stderr="fictional failure"))
    monkeypatch.setattr(subprocess, "run", refresh)
    state = {"token_refreshed": 1.0, "unrelated": {"preserved": True}}

    guard.keep_token_fresh(state)

    credentials.assert_called_once_with()
    refresh.assert_called_once_with(
        [
            "sudo",
            "-u",
            "acdev",
            "-H",
            "bash",
            "-lc",
            "export PATH=/home/acdev/.local/bin:/home/acdev/.local/opt/node/bin:$PATH; "
            "unset ANTHROPIC_API_KEY ANTHROPIC_AUTH_TOKEN; cd /tmp && "
            "timeout 120 claude -p 'Reply with the single word OK.' "
            "--model claude-haiku-4-5-20251001 --max-turns 1",
        ],
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert state == {"token_refreshed": 10_000.0, "unrelated": {"preserved": True}}
    expected = "ok" if returncode == 0 else "failed fictional failure"
    guard.log.assert_called_once_with(f"Claude token refresh: {expected}")


@pytest.mark.parametrize(
    ("expires_at", "last_refresh"),
    [(10_601_000, 0), (10_000_000, 6_401.0)],
    ids=["token-still-valid", "hourly-refresh-cooldown"],
)
def test_refresh_skips_when_existing_guard_conditions_hold(
    guard, monkeypatch, expires_at, last_refresh
):
    credentials = Mock(return_value=json.dumps({"claudeAiOauth": {"expiresAt": expires_at}}))
    monkeypatch.setattr(guard, "CREDENTIALS", SimpleNamespace(read_text=credentials))
    state = {"token_refreshed": last_refresh}

    guard.keep_token_fresh(state)

    assert state == {"token_refreshed": last_refresh}
    guard.log.assert_not_called()
