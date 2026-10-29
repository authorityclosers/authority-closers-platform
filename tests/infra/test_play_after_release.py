"""ac-play-after-release: a live release starts its Play build (alpha only; approved if allowed)."""

from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "infra/application/scripts/ac-play-after-release"
SERVICE = ROOT / "infra/application/systemd/ac-play-after-release.service"
TIMER = ROOT / "infra/application/systemd/ac-play-after-release.timer"

FULL = "4a6564b53e7a818649d4b023153473d415123408"
SHIP_LOG = (
    "2026-10-28T06:49:56Z v1.2.0 merged to main as 4a6564b. Building images.\n"
    "2026-10-28T07:39:00Z v1.2.0 is live on production and its canary passed: https://sx.example\n"
)

# A fake gh: logs every call and answers the few the hook makes.
# The run list shows run 100 until a dispatch, then 101.
GH = """
import json, os, sys
here = os.path.dirname(sys.argv[0])
args = sys.argv[1:]
with open(os.path.join(here, "gh.log"), "a") as log:
    log.write(json.dumps(args) + "\\n")
dispatched = os.path.join(here, "dispatched")
if args[:2] == ["workflow", "run"]:
    if os.environ.get("FAKE_GH_REFUSE"):
        sys.exit(1)
    open(dispatched, "w").close()
elif args[:2] == ["run", "list"]:
    print("101" if os.path.exists(dispatched) else "100")
elif args[0] == "api" and "-X" in args:
    pass
elif args[0] == "api" and args[1].endswith("/commits/4a6564b"):
    print("FULL_SHA")
elif args[0] == "api" and "/commits/" in args[1]:
    print("Release v1.2.0 (Sales Xray v1.2: logos in the switcher)")
    print("")
    print("Body text.")
elif args[0] == "api" and args[1].endswith("/environments/android-release"):
    print("777")
elif args[0] == "api" and args[1].endswith("/pending_deployments"):
    print("777")
""".replace("FULL_SHA", FULL)


def _fake(path: Path, body: str) -> None:
    path.write_text(f"#!{sys.executable}\n{body}")
    path.chmod(path.stat().st_mode | stat.S_IEXEC)


def _run(
    tmp_path: Path,
    *,
    ship_log: str = SHIP_LOG,
    state: str | None = None,
    auto: int = 0,
    refuse: bool = False,
    conf: str = "",
) -> subprocess.CompletedProcess[str]:
    _fake(tmp_path / "gh", GH)
    _fake(
        tmp_path / "notify",
        "import sys\nopen(sys.argv[0] + '.log', 'a').write(sys.argv[1] + '\\n')\n",
    )
    (tmp_path / "ac-ship.log").write_text(ship_log)
    (tmp_path / "conf").write_text(f"AUTO_APPROVE={auto}\n{conf}")
    if state is not None:
        (tmp_path / "state").mkdir(exist_ok=True)
        (tmp_path / "state" / "last").write_text(state + "\n")
    env = dict(os.environ)
    env.update(
        AC_PLAY_SHIP_LOG=str(tmp_path / "ac-ship.log"),
        AC_PLAY_LOG=str(tmp_path / "hook.log"),
        AC_PLAY_STATE=str(tmp_path / "state" / "last"),
        AC_PLAY_CONF=str(tmp_path / "conf"),
        AC_PLAY_NOTIFY=str(tmp_path / "notify"),
        AC_PLAY_GH=str(tmp_path / "gh"),
        AC_PLAY_PAUSE="0",
        AC_PLAY_NOTES_DIR=str(tmp_path / "notes"),
    )
    if refuse:
        env["FAKE_GH_REFUSE"] = "1"
    return subprocess.run(  # noqa: S603
        ["/bin/bash", str(SCRIPT)], env=env, capture_output=True, text=True, timeout=60, check=False
    )


def _calls(tmp_path: Path) -> list[list[str]]:
    log = tmp_path / "gh.log"
    return [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []


def _field(call: list[str], name: str) -> str:
    values = [
        call[i + 1]
        for i, a in enumerate(call[:-1])
        if a == "-f" and call[i + 1].startswith(name + "=")
    ]
    assert len(values) == 1, call
    return values[0].split("=", 1)[1]


def test_nothing_live_does_nothing(tmp_path: Path) -> None:
    result = _run(tmp_path, ship_log="2026-10-28T06:49:56Z v1.2.0 merged to main as 4a6564b.\n")
    assert result.returncode == 0
    assert _calls(tmp_path) == []


def test_a_release_already_built_is_not_built_again(tmp_path: Path) -> None:
    result = _run(tmp_path, state="v1.2.0")
    assert result.returncode == 0
    assert _calls(tmp_path) == []


def test_a_new_release_dispatches_alpha_with_its_full_main_commit_and_waits_for_the_owner(
    tmp_path: Path,
) -> None:
    result = _run(tmp_path, state="v1.1.0", auto=0)
    assert result.returncode == 0, result.stderr
    dispatches = [c for c in _calls(tmp_path) if c[:2] == ["workflow", "run"]]
    assert len(dispatches) == 1
    call = dispatches[0]
    assert call[2] == "play.yml" and call[call.index("--ref") + 1] == "main"
    assert _field(call, "web_ref") == FULL
    assert _field(call, "track") == "alpha"
    assert _field(call, "notes") == "Sales Xray v1.2: logos in the switcher"
    assert _field(call, "update_priority") == "0"
    assert not any("-X" in c for c in _calls(tmp_path)), "no approval without AUTO_APPROVE=1"
    assert (tmp_path / "state" / "last").read_text().strip() == "v1.2.0"
    told = (tmp_path / "notify.log").read_text()
    assert (
        "Approve it here: https://github.com/authorityclosers/sales-xray-apps/actions/runs/101"
        in told
    )


def test_auto_approve_approves_only_its_own_run_in_android_release(tmp_path: Path) -> None:
    result = _run(tmp_path, state="v1.1.0", auto=1)
    assert result.returncode == 0, result.stderr
    approvals = [c for c in _calls(tmp_path) if "-X" in c]
    assert len(approvals) == 1
    call = approvals[0]
    assert call[call.index("-X") + 1] == "POST"
    assert any(a.endswith("/actions/runs/101/pending_deployments") for a in call)
    assert "environment_ids[]=777" in call and "state=approved" in call
    assert "building for Play closed testing" in (tmp_path / "notify.log").read_text()


def test_a_refused_dispatch_keeps_the_release_pending_for_the_next_tick(tmp_path: Path) -> None:
    result = _run(tmp_path, state="v1.1.0", refuse=True)
    assert result.returncode == 1
    assert (tmp_path / "state" / "last").read_text().strip() == "v1.1.0"
    assert "dispatch refused" in (tmp_path / "hook.log").read_text()


@pytest.mark.parametrize("track", ["internal", "beta", "production"])
def test_the_hook_never_dispatches_any_other_track(track: str) -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    assert "-f track=alpha" in text
    assert f"track={track}" not in text


def test_units_run_the_installed_hook_every_five_minutes() -> None:
    service = SERVICE.read_text(encoding="utf-8")
    timer = TIMER.read_text(encoding="utf-8")
    assert "Type=oneshot" in service
    assert "ExecStart=/usr/local/sbin/ac-play-after-release" in service
    assert "OnCalendar=*:0/5" in timer
    assert "WantedBy=timers.target" in timer


def test_written_notes_and_a_dated_update_priority_go_with_the_build(tmp_path: Path) -> None:
    (tmp_path / "notes").mkdir()
    (tmp_path / "notes" / "v1.2.0.txt").write_text("Your logo now shows in the workspace switcher.")
    result = _run(
        tmp_path, state="v1.1.0", conf="PLAY_UPDATE_PRIORITY=4\nPLAY_PRIORITY_UNTIL=2999-01-01\n"
    )
    assert result.returncode == 0, result.stderr
    call = next(c for c in _calls(tmp_path) if c[:2] == ["workflow", "run"])
    assert _field(call, "notes") == "Your logo now shows in the workspace switcher."
    assert _field(call, "update_priority") == "4"


def test_the_update_priority_lapses_after_its_date(tmp_path: Path) -> None:
    result = _run(
        tmp_path, state="v1.1.0", conf="PLAY_UPDATE_PRIORITY=4\nPLAY_PRIORITY_UNTIL=2000-01-01\n"
    )
    assert result.returncode == 0, result.stderr
    call = next(c for c in _calls(tmp_path) if c[:2] == ["workflow", "run"])
    assert _field(call, "update_priority") == "0"
