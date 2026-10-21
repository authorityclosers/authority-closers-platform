"""acdev dev server watchdog: restart a dev server after two minutes of failing pages, never
sooner, never twice within five minutes and never when it was stopped on purpose (orchestrator,
20-21 Oct 2026). One script and one templated unit serve Admin and Sales Xray."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEV = ROOT / "infra/application/development"
SCRIPT = DEV / "acdev-dev-watchdog.sh"
XRAY = (
    "acdev-xray-dev.service",
    "http://127.0.0.1:3026/login",
    "salesxray-dev.authorityclosers.com",
)


def _fake(tmp_path: Path, name: str, body: str) -> Path:
    path = tmp_path / name
    path.write_text("#!/bin/bash\n" + body)
    path.chmod(0o755)
    return path


def _run(
    tmp_path: Path, code: str, now: int, args: tuple[str, ...] = XRAY, *, active: bool = True
) -> subprocess.CompletedProcess[str]:
    curl = _fake(
        tmp_path,
        "curl",
        f"printf '%s\\n' \"$*\" >> '{tmp_path / 'curls.txt'}'\nprintf '%s' '{code}'\n",
    )
    systemctl = _fake(
        tmp_path,
        "systemctl",
        f"""case "$2" in
  is-active) exit {0 if active else 3} ;;
  show) printf '%s\\n' 3221225472 ;;
  *) printf '%s\\n' "$*" >> '{tmp_path / "restarts.txt"}' ;;
esac
""",
    )
    return subprocess.run(  # noqa: S603
        ["bash", str(SCRIPT), *args],  # noqa: S607
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


def _probe(
    tmp_path: Path, code: str, now: int, args: tuple[str, ...] = XRAY, *, active: bool = True
) -> str:
    result = _run(tmp_path, code, now, args, active=active)
    assert result.returncode == 0, result.stderr
    restarts = tmp_path / "restarts.txt"
    return restarts.read_text() if restarts.exists() else ""


def test_script_parses() -> None:
    subprocess.run(["bash", "-n", str(SCRIPT)], check=True, timeout=30)  # noqa: S603, S607


def test_two_minutes_of_5xx_restart_once_and_good_pages_clear_the_clock(tmp_path: Path) -> None:
    assert _probe(tmp_path, "500", 1_000) == ""
    assert _probe(tmp_path, "502", 1_090) == ""  # 90 s bad: not yet
    assert _probe(tmp_path, "200", 1_100) == ""  # good: the clock clears
    assert _probe(tmp_path, "000", 1_130) == ""  # no answer or a timeout counts as bad, from here
    assert _probe(tmp_path, "504", 1_240) == ""  # 110 s
    assert _probe(tmp_path, "503", 1_250) == "--user restart acdev-xray-dev.service\n"
    # Still failing after the restart: no second restart within five minutes.
    assert _probe(tmp_path, "500", 1_300).count("restart") == 1
    assert _probe(tmp_path, "500", 1_430).count("restart") == 1
    assert _probe(tmp_path, "500", 1_560).count("restart") == 2


def test_restart_logs_the_url_code_and_memory(tmp_path: Path) -> None:
    _probe(tmp_path, "000", 1_000)
    result = _run(tmp_path, "000", 1_200)
    assert result.stdout == (
        "acdev-dev-watchdog: http://127.0.0.1:3026/login answered 000 for 200s (memory 3072M); "
        "restarting acdev-xray-dev.service\n"
    )


def test_redirects_and_client_errors_are_not_failures(tmp_path: Path) -> None:
    for now, code in enumerate(("307", "404", "401", "200"), start=1):
        assert _probe(tmp_path, code, now * 200) == ""
    assert not (tmp_path / "state" / "acdev-xray-dev" / "bad-since").exists()


def test_a_stopped_or_failed_unit_is_left_alone(tmp_path: Path) -> None:
    assert _probe(tmp_path, "000", 1_000) == ""
    for now in (1_200, 1_500, 2_000):
        assert _probe(tmp_path, "000", now, active=False) == ""
    assert (tmp_path / "curls.txt").read_text().count("\n") == 1  # inactive: not even probed
    assert not (tmp_path / "state" / "acdev-xray-dev" / "bad-since").exists()


def test_each_unit_keeps_its_own_clock_and_host_header(tmp_path: Path) -> None:
    admin = ("acdev-admin-dev", "http://127.0.0.1:3028/login", "admin-dev.authorityclosers.com")
    assert _probe(tmp_path, "500", 1_000) == ""
    assert _probe(tmp_path, "500", 1_100, admin) == ""
    assert _probe(tmp_path, "500", 1_130) == "--user restart acdev-xray-dev.service\n"
    assert (
        _probe(tmp_path, "500", 1_200, admin) == "--user restart acdev-xray-dev.service\n"
    )  # admin: 100 s
    assert _probe(tmp_path, "500", 1_220, admin).endswith(
        "--user restart acdev-admin-dev.service\n"
    )
    curls = (tmp_path / "curls.txt").read_text()
    assert "-H Host: salesxray-dev.authorityclosers.com http://127.0.0.1:3026/login" in curls
    assert "-H Host: admin-dev.authorityclosers.com http://127.0.0.1:3028/login" in curls


def test_no_host_header_when_none_is_given(tmp_path: Path) -> None:
    assert (
        _probe(tmp_path, "200", 1_000, ("acdev-x-dev.service", "http://127.0.0.1:3999/", "")) == ""
    )
    assert (
        tmp_path / "curls.txt"
    ).read_text() == "-s -o /dev/null -m 20 -w %{http_code} http://127.0.0.1:3999/\n"


def test_bad_arguments_are_refused(tmp_path: Path) -> None:
    for args in (
        (),
        ("acdev-xray-dev.service",),
        ("x;rm -rf ~", "http://127.0.0.1/"),
        ("acdev-xray-dev", "file:///"),
    ):
        result = _run(tmp_path, "000", 1_000, args)
        assert result.returncode == 2, args
    assert not (tmp_path / "restarts.txt").exists()


def test_templated_units_run_the_installed_script_every_30_seconds() -> None:
    service = (DEV / "acdev-dev-watchdog@.service").read_text()
    timer = (DEV / "acdev-dev-watchdog@.timer").read_text()
    assert "Type=oneshot" in service
    assert "EnvironmentFile=%h/.config/acdev-dev-watchdog/%i.env" in service
    assert (
        "ExecStart=%h/.local/bin/acdev-dev-watchdog %i.service ${PROBE_URL} ${PROBE_HOST}"
        in service
    )
    assert "OnUnitActiveSec=30s" in timer and "WantedBy=timers.target" in timer
    # The admin-only copy of 20 Oct is gone: one script, one template.
    assert not list(DEV.glob("acdev-admin-dev-watchdog*"))


def test_each_watched_server_probes_its_own_login_page() -> None:
    def env(name: str) -> dict[str, str]:
        text = (DEV / "acdev-dev-watchdog" / f"{name}.env").read_text()
        return dict(re.findall(r"^([A-Z_]+)=(\S+)$", text, flags=re.MULTILINE))

    assert env("acdev-admin-dev") == {
        "PROBE_URL": "http://127.0.0.1:3028/login",
        "PROBE_HOST": "admin-dev.authorityclosers.com",
    }
    assert env("acdev-xray-dev") == {
        "PROBE_URL": "http://127.0.0.1:3026/login",
        "PROBE_HOST": "salesxray-dev.authorityclosers.com",
    }
