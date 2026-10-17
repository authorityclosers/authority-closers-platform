"""The partner webhooks host wrapper and its systemd units (files only; nothing is run)."""

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "infra/application/scripts/ac-partner-events"
SERVICE = ROOT / "infra/application/systemd/ac-partner-events@.service"
TIMER = ROOT / "infra/application/systemd/ac-partner-events@.timer"


def test_wrapper_is_valid_bash_and_runs_the_module_for_each_environment() -> None:
    subprocess.run(["bash", "-n", str(SCRIPT)], check=True)  # noqa: S603, S607
    text = SCRIPT.read_text()
    assert text.startswith("#!/bin/bash\n") and "set -euo pipefail" in text
    assert "module=ac_platform.partner_events.cli" in text
    assert "run --apply --seconds 55 --interval 5" in text
    # Each environment keeps its own service config and database; dev uses the live slot.
    assert "/etc/authority-closers/development/service-live.json" in text
    assert "/etc/authority-closers/development/database-url-live" in text
    assert "ac-application-$env_name-sales-xray-worker-1" in text
    assert "production) cap=300" in text
    # A release that lacks the runner exits quietly.
    assert 'grep -q -- "register-endpoint"' in text


def test_unit_and_timer_run_the_wrapper_every_minute() -> None:
    service = SERVICE.read_text()
    assert "ExecStart=/usr/local/sbin/ac-partner-events %i" in service
    assert "Type=oneshot" in service
    timer = TIMER.read_text()
    assert "OnCalendar=minutely" in timer
    assert "WantedBy=timers.target" in timer
