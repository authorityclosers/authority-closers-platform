"""The one-pass trial's host wrapper and systemd unit: development only, never a backfill."""

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "infra/application/scripts/ac-one-pass"
SERVICE = ROOT / "infra/application/systemd/ac-one-pass@.service"


def test_wrapper_parses_reads_only_new_calls_and_holds_no_key() -> None:
    subprocess.run(["bash", "-n", str(SCRIPT)], check=True, timeout=30)  # noqa: S603, S607
    text = SCRIPT.read_text()
    assert '--not-before "$since" --recent-hours 2 --loop --apply' in text
    assert "--recording" not in text and "--bench" not in text and "--force" not in text
    assert "GEMINI_API_KEY" not in text


def test_wrapper_refuses_staging_and_production() -> None:
    for environment in ("staging", "production"):
        result = subprocess.run(  # noqa: S603
            ["bash", str(SCRIPT), environment],  # noqa: S607
            capture_output=True,
            text=True,
            timeout=30,
            env={"PATH": "/usr/bin:/bin", "ONE_PASS_STATE": "/nonexistent/never-created"},
        )
        assert result.returncode == 2
        assert "development only" in result.stderr


def test_service_restarts_picks_up_releases_and_stays_in_the_background() -> None:
    text = SERVICE.read_text()
    assert "ExecStart=/usr/local/sbin/ac-one-pass %i" in text
    assert "Restart=always" in text and "RuntimeMaxSec=" in text
    assert "Nice=10" in text and "CPUQuota=" in text and "MemoryMax=" in text
