"""Offline usage-guard coverage; only fictional state and mocked dependencies."""

from __future__ import annotations

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


def load_guard():
    spec = importlib.util.spec_from_file_location("offline_ac_usage_guard", SOURCE)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def guard(monkeypatch, tmp_path):
    def forbidden(*args, **kwargs):
        raise AssertionError("Live usage-guard dependency called")

    state_path = tmp_path / "state.json"
    read_text = Path.read_text

    def fixture_read(path, *args, **kwargs):
        if path != state_path:
            forbidden()
        return read_text(path, *args, **kwargs)

    monkeypatch.setattr(subprocess, "run", forbidden)
    monkeypatch.setattr(urllib.request, "urlopen", forbidden)
    monkeypatch.setattr(Path, "read_text", fixture_read)
    module = load_guard()
    monkeypatch.setattr(module, "STATE", state_path)
    monkeypatch.setattr(module, "time", SimpleNamespace(time=lambda: 10_000.0))
    monkeypatch.setattr(module, "log", Mock())
    return module


def test_existing_model_policy_is_preserved(guard):
    assert guard.CODEX_FAILOVER_AT == 1000
    assert guard.CODEX_ALERT_AT == 90
    assert guard.SOL_MODEL == "gpt-6.1-sol"
    assert guard.CLAUDE_MODEL == "claude-opus-5-5"


def test_alert_deduplicates_jitter_after_restart_and_posts_on_new_window(guard, monkeypatch):
    monkeypatch.setattr(guard, "keep_token_fresh", Mock())
    monkeypatch.setattr(guard, "claude_usage_cached", Mock(return_value={}))
    monkeypatch.setattr(guard, "codex_usage", Mock())
    monkeypatch.setattr(guard, "api", Mock(return_value={"id": "fictional-issue"}))
    guard.save({"unrelated": {"preserved": True}})

    def poll(module, resets):
        module.codex_usage.side_effect = [{"used": 90, "resets_at": reset} for reset in resets]
        for _ in resets:
            module.check()
        return [c.args[2]["body"] for c in module.api.call_args_list if c.args[0] == "POST"]

    alerts = poll(guard, [1791581522, 1791581522, 1791581523, 1791581522, 1791581523])
    assert len(alerts) == 1
    assert guard.state()["alerted_reset"] == 1791581522
    reloaded = load_guard()
    for name in (
        "STATE",
        "time",
        "log",
        "keep_token_fresh",
        "claude_usage_cached",
        "codex_usage",
        "api",
    ):
        monkeypatch.setattr(reloaded, name, getattr(guard, name))
    assert len(poll(reloaded, [1791581523, 1791581522])) == 1
    alerts = poll(reloaded, [1792186322, 1792186322])
    assert len(alerts) == 2
    assert reloaded.state()["alerted_reset"] == 1792186322
    assert reloaded.state()["unrelated"] == {"preserved": True}
    assert reloaded.ALERT_ISSUE == "AUT-991"
    guard.api.assert_any_call("GET", "/api/issues/AUT-991")
    for text in alerts:
        assert "Usage guard (ac server):" in text
        assert "100% Codex work pauses until the weekly reset" in text
        assert "Paid credits are not used" in text
        assert "1000%" not in text
        assert "laptop" not in text


@pytest.mark.parametrize("delta", [-3601, -3600, -1, 0, 1, 3600, 3601])
@pytest.mark.parametrize("used", [89, 90])
def test_alert_window_tolerance_and_threshold(guard, delta, used):
    guard.save({"alerted_reset": 1791581522})
    steps = guard.decide({}, {"used": used, "resets_at": 1791581522 + delta})
    assert ("alert" in steps) == (used >= 90 and abs(delta) > 3600)


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
