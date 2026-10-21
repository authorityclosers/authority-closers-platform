"""The one-pass runner's host wrapper and systemd unit: every environment the release
runs, inside the worker on staging and production, never a backfill."""

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "infra/application/scripts/ac-one-pass"
SERVICE = ROOT / "infra/application/systemd/ac-one-pass@.service"


def test_wrapper_parses_reads_only_new_calls_and_holds_no_key() -> None:
    subprocess.run(["bash", "-n", str(SCRIPT)], check=True, timeout=30)  # noqa: S603, S607
    text = SCRIPT.read_text()
    assert 'common=(--not-before "$since" --recent-hours 2 --loop --apply)' in text
    assert text.count('"${common[@]}"') == 2
    assert "--recording" not in text and "--bench" not in text and "--force" not in text
    assert "GEMINI_API_KEY" not in text


def test_wrapper_runs_inside_the_worker_on_staging_and_production() -> None:
    text = SCRIPT.read_text()
    assert "container=ac-application-$env_name-sales-xray-worker-1" in text
    assert "--service-config /run/ac-sales-xray/service.json" in text
    # A start first stops a looping runner left in the container; ExecStop does too.
    assert 'stop_container_runner "$container"' in text
    assert "ac_platform.one_pass.runner" in text


def test_wrapper_refuses_an_unknown_environment() -> None:
    result = subprocess.run(  # noqa: S603
        ["bash", str(SCRIPT), "elsewhere"],  # noqa: S607
        capture_output=True,
        text=True,
        timeout=30,
        env={"PATH": "/usr/bin:/bin", "ONE_PASS_STATE": "/nonexistent/never-created"},
    )
    assert result.returncode == 2
    assert "unknown environment" in result.stderr


def test_stop_for_development_does_nothing() -> None:
    result = subprocess.run(  # noqa: S603
        ["bash", str(SCRIPT), "stop", "development-live"],  # noqa: S607
        capture_output=True,
        text=True,
        timeout=30,
        env={"PATH": "/usr/bin:/bin", "ONE_PASS_STATE": "/nonexistent/never-created"},
    )
    assert result.returncode == 0


def test_service_restarts_picks_up_releases_and_stays_in_the_background() -> None:
    text = SERVICE.read_text()
    assert "ExecStart=/usr/local/sbin/ac-one-pass %i" in text
    assert "ExecStop=/usr/local/sbin/ac-one-pass stop %i" in text
    assert "Restart=always" in text and "RuntimeMaxSec=" in text
    assert "Nice=10" in text and "CPUQuota=" in text and "MemoryMax=" in text
