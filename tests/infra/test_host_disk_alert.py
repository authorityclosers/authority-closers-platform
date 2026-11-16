"""Fictional threshold and notification-failure checks; never contacts Telegram."""

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

SOURCE = Path(__file__).resolve().parents[2] / "infra/host-disk/ac_disk_alert.py"
SPEC = importlib.util.spec_from_file_location("host_disk_alert", SOURCE)
assert SPEC and SPEC.loader
ALERT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ALERT)


@pytest.mark.parametrize(
    ("previous", "percent", "expected"),
    [
        (0, 84, (0, None)),
        (0, 85, (85, "warning")),
        (85, 94, (85, None)),
        (85, 95, (95, "critical")),
        (95, 99, (95, None)),
        (85, 82, (85, None)),
        (95, 79, (0, "recovered")),
        (0, 79, (0, None)),
    ],
)
def test_thresholds_and_hysteresis(previous, percent, expected):
    assert ALERT.transition(previous, percent) == expected


def test_usage_accounts_for_reserved_blocks_and_rounds_like_df(monkeypatch):
    monkeypatch.setattr(
        ALERT.os,
        "statvfs",
        lambda _: SimpleNamespace(f_blocks=1100, f_bfree=256, f_bavail=156, f_frsize=4096),
    )
    assert ALERT.usage() == {
        "percent": 85,
        "available_bytes": 156 * 4096,
        "total_bytes": 1100 * 4096,
    }


def test_dry_run_never_sends_or_writes(tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("notification during dry run")

    monkeypatch.setattr(ALERT.subprocess, "run", forbidden)
    state = tmp_path / "state.json"
    result = ALERT.check(state, {"percent": 99, "available_bytes": 100}, apply=False)
    assert result["event"] == "critical"
    assert not state.exists()


def test_send_failure_keeps_state_then_success_deduplicates(tmp_path, monkeypatch):
    state = tmp_path / "state.json"
    state.write_text('{"level": 0}')
    calls = []

    def send(args, **kwargs):
        calls.append((args, kwargs))
        return SimpleNamespace(returncode=1 if len(calls) == 1 else 0)

    monkeypatch.setattr(ALERT.subprocess, "run", send)
    figures = {"percent": 85, "available_bytes": 1024**3}
    with pytest.raises(RuntimeError, match="state unchanged"):
        ALERT.check(state, figures, apply=True)
    assert json.loads(state.read_text()) == {"level": 0}
    ALERT.check(state, figures, apply=True)
    ALERT.check(state, figures, apply=True)
    assert len(calls) == 2
    assert calls[0][0] == [ALERT.NOTIFY]
    assert "85% used" in calls[0][1]["input"]
    assert json.loads(state.read_text())["level"] == 85


def test_invalid_state_refuses_without_send(tmp_path, monkeypatch):
    state = tmp_path / "state.json"
    state.write_text('{"level": "85"}')
    with pytest.raises(ValueError, match="invalid disk alert state"):
        ALERT.check(state, {"percent": 99}, apply=True)


@pytest.fixture
def cache_module():
    spec = importlib.util.spec_from_file_location(
        "idle_next_cache", SOURCE.with_name("clear_idle_next_cache.py")
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_idle_cache_cleanup_preserves_compiled_output_and_supports_dry_run(tmp_path, cache_module):
    cache = tmp_path / "app/.next/cache"
    cache.mkdir(parents=True)
    (cache / "fixture.pack").write_bytes(b"fictional cache")
    compiled = cache.parent / "compiled.js"
    compiled.write_text("fictional compiled output")
    assert cache_module.clear(cache, set(), apply=False)["status"] == "eligible"
    assert cache.exists()
    assert cache_module.clear(cache, set(), apply=True)["status"] == "cleared"
    assert not cache.exists()
    assert compiled.exists()
    assert cache_module.clear(cache, set(), apply=True)["status"] == "absent"


def test_active_app_cache_and_symlinks_are_preserved(tmp_path, cache_module):
    cache = tmp_path / "app/.next/cache"
    cache.mkdir(parents=True)
    assert cache_module.clear(cache, {tmp_path / "app"}, apply=True)["status"] == "in_use"
    outside = tmp_path / "private"
    outside.write_text("fictional retained data")
    (cache / "link").symlink_to(outside)
    with pytest.raises(ValueError, match="symlink"):
        cache_module.clear(cache, set(), apply=True)
    assert outside.read_text() == "fictional retained data"


def test_a_missing_native_image_alerts_once_and_once_back(tmp_path, monkeypatch):
    """16 Nov 2026: the native C1 image went missing and every upload failed its audio check."""
    sent = []
    monkeypatch.setattr(
        ALERT.subprocess,
        "run",
        lambda argv, **kwargs: sent.append(kwargs.get("input")) or SimpleNamespace(returncode=0),
    )
    state = tmp_path / "state.json"
    figures = {"percent": 50, "available_bytes": 100}
    gone = ALERT.check(state, figures, apply=True, native={"staging": False, "production": True})
    assert gone["native_missing"] == ["staging"]
    assert len(sent) == 1 and "missing from Docker on ac for staging" in sent[0]
    ALERT.check(state, figures, apply=True, native={"staging": False, "production": True})
    assert len(sent) == 1  # once
    ALERT.check(state, figures, apply=True, native={"staging": True, "production": True})
    assert len(sent) == 2 and "back in Docker for staging" in sent[1]
    # A dry run reports without sending; an old state file without the key still reads.
    state.write_text(json.dumps({"level": 0}))
    dry = ALERT.check(state, figures, apply=False, native={"production": False})
    assert dry["native_missing"] == ["production"] and len(sent) == 2


def test_native_images_reads_each_units_image_ref(tmp_path, monkeypatch):
    ref = "sha256:" + "a" * 64
    (tmp_path / "ac-sales-xray-native-staging.service").write_text(
        f"ExecStart=helper --image-ref {ref}\n"
    )
    (tmp_path / "ac-sales-xray-native-production.service").write_text("ExecStart=helper\n")
    seen = []

    def inspect(argv, **kwargs):
        seen.append(argv)
        return SimpleNamespace(returncode=1)

    monkeypatch.setattr(ALERT.subprocess, "run", inspect)
    assert ALERT.native_images(tmp_path) == {"staging": False}
    assert seen == [[ALERT.DOCKER, "image", "inspect", "--format", "{{.Id}}", ref]]


def test_a_docker_timeout_is_unknown_and_the_disk_alert_still_goes(tmp_path, monkeypatch):
    """Release PR #627 review (P2): an image inspection that takes over 20 s must not stop the
    disk alerts; the native check is unknown and keeps its last known state."""
    ref = "sha256:" + "b" * 64
    (tmp_path / "ac-sales-xray-native-staging.service").write_text(
        f"ExecStart=helper --image-ref {ref}\n"
    )

    def slow(argv, **kwargs):
        raise ALERT.subprocess.TimeoutExpired(argv, kwargs["timeout"])

    monkeypatch.setattr(ALERT.subprocess, "run", slow)
    assert ALERT.native_images(tmp_path) == {"staging": None}

    sent = []
    monkeypatch.setattr(
        ALERT.subprocess,
        "run",
        lambda argv, **kwargs: sent.append(kwargs.get("input")) or SimpleNamespace(returncode=0),
    )
    state = tmp_path / "state.json"
    figures = {"percent": 90, "available_bytes": 100}
    result = ALERT.check(state, figures, apply=True, native={"staging": None})
    assert result["event"] == "warning" and len(sent) == 1 and "disk warning" in sent[0]
    assert result["native_missing"] == [] and result["native_unknown"] == ["staging"]
    # A known-missing image stays missing while unknown: no "back" alert, no second one.
    ALERT.check(state, figures, apply=True, native={"staging": False})
    assert len(sent) == 2 and "missing from Docker" in sent[1]
    unknown = ALERT.check(state, figures, apply=True, native={"staging": None})
    assert unknown["native_missing"] == ["staging"] and len(sent) == 2
