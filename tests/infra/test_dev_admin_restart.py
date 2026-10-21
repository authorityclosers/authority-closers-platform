"""Admin dev server nightly restart (21 Oct 2026): the recorded units run acdev-dev-restart on the
Admin dev server's own Turbopack cache, with a cap that a busy day cannot push past the unit's
MemoryHigh, the watchdog's probe and its own watchdog, ten minutes after the Sales Xray run. The
script itself is tested in test_dev_restart.py."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEV = ROOT / "infra/application/development"
SCRIPT = DEV / "acdev-dev-restart.sh"
ADMIN = DEV / "acdev-admin-dev"
UNIT = "acdev-admin-dev.service"
WATCHDOG = "acdev-dev-watchdog@acdev-admin-dev.timer"
URL = "http://127.0.0.1:3028/login"
HOST = "admin-dev.authorityclosers.com"
CAP = 512
BUSY_DAY_MIB = 490  # what the cache grew on 19 and 20 Oct


def _directives(path: Path) -> dict[str, str]:
    pairs = (line.split("=", 1) for line in path.read_text().splitlines() if "=" in line)
    return {key: value for key, value in pairs if not key.startswith("#")}


def _restart_args() -> list[str]:
    return _directives(ADMIN / "acdev-admin-dev-restart.service")["ExecStart"].split()


def _minutes(on_calendar: str) -> int:
    hours, minutes, _ = on_calendar.split()[1].split(":")
    return int(hours) * 60 + int(minutes)


def _fake(tmp_path: Path, name: str, body: str) -> Path:
    path = tmp_path / name
    path.write_text("#!/bin/bash\n" + body)
    path.chmod(0o755)
    return path


def test_the_admin_restart_unit_names_its_own_cache_cap_and_the_watchdog_probe() -> None:
    service = _directives(ADMIN / "acdev-admin-dev-restart.service")
    workdir = _directives(ADMIN / UNIT)["WorkingDirectory"]
    probe = _directives(DEV / "acdev-dev-watchdog/acdev-admin-dev.env")
    assert workdir == "%h/src/dev-live/authority-closers-platform"
    assert _restart_args() == [
        "%h/.local/bin/acdev-dev-restart",
        UNIT,
        f"{workdir}/apps/admin-web/.next/dev/cache/turbopack",
        str(CAP),
        probe["PROBE_URL"],
        probe["PROBE_HOST"],
    ]
    assert (probe["PROBE_URL"], probe["PROBE_HOST"]) == (URL, HOST)
    assert (service["Type"], service["IOSchedulingClass"]) == ("oneshot", "idle")
    assert service["TimeoutStartSec"] == "20min"


def test_the_cap_plus_a_busy_day_stays_below_the_units_memory_high() -> None:
    unit = _directives(ADMIN / UNIT)
    assert "--hostname 127.0.0.1 --port 3028" in unit["ExecStart"]
    assert (unit["MemoryHigh"], unit["MemoryMax"], unit["MemorySwapMax"]) == (
        "1200M",
        "1600M",
        "256M",
    )
    # The cap is checked once a night, so the cache can reach the cap plus one busy day.
    assert int(unit["MemoryHigh"].removesuffix("M")) > CAP + BUSY_DAY_MIB


def test_the_admin_restart_runs_ten_minutes_after_the_sales_xray_one() -> None:
    timer = _directives(ADMIN / "acdev-admin-dev-restart.timer")
    assert timer["OnCalendar"] == "*-*-* 22:40:00 UTC"  # 04:10 IST
    assert timer["Persistent"] == "false"
    assert timer["WantedBy"] == "timers.target"
    xray = _directives(DEV / "acdev-xray-dev/acdev-xray-dev-restart.timer")["OnCalendar"]
    assert _minutes(timer["OnCalendar"]) - _minutes(xray) >= 10


def test_the_folder_records_the_unit_without_drop_ins_and_its_restart_units() -> None:
    # The live unit has no drop-ins (systemctl --user show: DropInPaths empty, 21 Oct).
    assert sorted(path.name for path in ADMIN.iterdir()) == [
        "acdev-admin-dev-restart.service",
        "acdev-admin-dev-restart.timer",
        UNIT,
    ]


def test_the_recorded_arguments_restart_admin_under_its_own_watchdog(tmp_path: Path) -> None:
    args = [arg.replace("%h", str(tmp_path)) for arg in _restart_args()[1:]]
    cache = Path(args[1])
    (cache / "v16.3.8-b0fad0d4").mkdir(parents=True)
    (cache / "v16.3.8-b0fad0d4/00000001.sst").write_bytes(b"\0" * 1_048_576)
    calls = tmp_path / "calls.txt"
    systemctl = _fake(
        tmp_path,
        "systemctl",
        f"""case "$2" in
  is-active) [[ "$3" == --quiet ]] || printf 'active\\n' ;;
  show) printf '%s\\n' 1064726528 ;;
  start|stop) printf '%s %s\\n' "$2" "$3" >> '{calls}' ;;
esac
""",
    )
    curl = _fake(tmp_path, "curl", f"printf 'curl %s\\n' \"$*\" >> '{calls}'\nprintf 200\n")
    sleep = _fake(tmp_path, "sleep", f"printf 'sleep %s\\n' \"$1\" >> '{calls}'\n")
    result = subprocess.run(  # noqa: S603
        ["bash", str(SCRIPT), *args],  # noqa: S607
        env={
            "PATH": "/usr/bin:/bin",
            "HOME": str(tmp_path),
            "RESTART_SYSTEMCTL": str(systemctl),
            "RESTART_CURL": str(curl),
            "RESTART_SLEEP": str(sleep),
            "RESTART_WARMUP_TRIES": "3",
        },
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert calls.read_text().splitlines() == [
        f"stop {WATCHDOG}",
        f"stop {UNIT}",
        f"start {UNIT}",
        f"curl -s -o /dev/null -m 60 -w %{{http_code}} -H Host: {HOST} {URL}",
        f"start {WATCHDOG}",
    ]
    assert (cache / "v16.3.8-b0fad0d4/00000001.sst").stat().st_size == 1_048_576
    assert re.fullmatch(
        rf"acdev-dev-restart: {re.escape(UNIT)} restarted \(memory peak since its last start "
        rf"1015M\); cache [12]M within cap {CAP}M, kept; {re.escape(URL)} answered 200 after "
        r"\d+s; watchdog resumed; memory 1015M\n",
        result.stdout,
    ), result.stdout
