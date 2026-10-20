"""Admin's dev server watchdog: restart after two minutes of failing pages, never sooner and
never twice within five minutes (orchestrator, 20 Oct 2026)."""

from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEV = ROOT / "infra/application/development"
SCRIPT = DEV / "acdev-admin-dev-watchdog.sh"


def _fake(tmp_path: Path, name: str, body: str) -> Path:
    path = tmp_path / name
    path.write_text("#!/bin/bash\n" + body)
    path.chmod(0o755)
    return path


def _probe(tmp_path: Path, code: str, now: int) -> str:
    curl = _fake(tmp_path, "curl", f"printf '%s' '{code}'\n")
    restarts = tmp_path / "restarts.txt"
    systemctl = _fake(tmp_path, "systemctl", f"printf '%s\\n' \"$*\" >> '{restarts}'\n")
    result = subprocess.run(  # noqa: S603
        ["bash", str(SCRIPT)],  # noqa: S607
        env={
            "PATH": "/usr/bin:/bin",
            "HOME": str(tmp_path),
            "WATCHDOG_STATE_DIR": str(tmp_path / "state"),
            "WATCHDOG_NOW": str(now),
            "WATCHDOG_CURL": str(curl),
            "WATCHDOG_SYSTEMCTL": str(systemctl),
        },
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return restarts.read_text() if restarts.exists() else ""


def test_script_parses() -> None:
    subprocess.run(["bash", "-n", str(SCRIPT)], check=True, timeout=30)  # noqa: S603, S607


def test_two_minutes_of_5xx_restart_once_and_good_pages_clear_the_clock(tmp_path: Path) -> None:
    assert _probe(tmp_path, "500", 1_000) == ""
    assert _probe(tmp_path, "502", 1_090) == ""  # 90 s bad: not yet
    assert _probe(tmp_path, "200", 1_100) == ""  # good: the clock clears
    assert _probe(tmp_path, "000", 1_130) == ""  # no answer counts as bad, from here
    assert _probe(tmp_path, "504", 1_240) == ""  # 110 s
    assert _probe(tmp_path, "503", 1_250) == "--user restart acdev-admin-dev.service\n"
    # Still failing after the restart: no second restart within five minutes.
    assert _probe(tmp_path, "500", 1_300).count("restart") == 1
    assert _probe(tmp_path, "500", 1_430).count("restart") == 1
    assert _probe(tmp_path, "500", 1_560).count("restart") == 2


def test_redirects_and_client_errors_are_not_failures(tmp_path: Path) -> None:
    for now, code in enumerate(("307", "404", "401", "200"), start=1):
        assert _probe(tmp_path, code, now * 200) == ""
    assert not (tmp_path / "state" / "bad-since").exists()


def test_units_run_the_installed_script_every_30_seconds() -> None:
    service = (DEV / "acdev-admin-dev-watchdog.service").read_text()
    timer = (DEV / "acdev-admin-dev-watchdog.timer").read_text()
    assert "ExecStart=%h/.local/bin/acdev-admin-dev-watchdog" in service
    assert "Type=oneshot" in service
    assert "OnUnitActiveSec=30s" in timer and "WantedBy=timers.target" in timer
