"""The call data engine's host wrapper and systemd unit (fast pipeline runner)."""

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "infra/application/scripts/ac-call-data"
SERVICE = ROOT / "infra/application/systemd/ac-call-data@.service"


def test_wrapper_parses_and_never_backfills() -> None:
    subprocess.run(["bash", "-n", str(SCRIPT)], check=True, timeout=30)  # noqa: S603, S607
    text = SCRIPT.read_text()
    # Automatic mode: a since-marker recorded once, then only newer transcripts.
    assert '--not-before "$since" --loop --apply' in text
    assert "--recording" not in text and "--recent-hours" not in text
    # The provider key only ever lives in the runner's own infisical child.
    assert "GEMINI_API_KEY" not in text


def test_service_restarts_and_picks_up_releases() -> None:
    text = SERVICE.read_text()
    assert "ExecStart=/usr/local/sbin/ac-call-data %i" in text
    assert "Restart=always" in text and "RuntimeMaxSec=" in text
