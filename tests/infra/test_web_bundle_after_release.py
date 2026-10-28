"""ac-web-bundle-after-release: a live release publishes its signed web bundle (off by default)."""

from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "infra/application/scripts/ac-web-bundle-after-release"
TOOL = ROOT / "infra/application/scripts/sx-web-bundle"
SERVICE = ROOT / "infra/application/systemd/ac-web-bundle-after-release.service"
TIMER = ROOT / "infra/application/systemd/ac-web-bundle-after-release.timer"

FULL = "4a6564b53e7a818649d4b023153473d415123408"
SEED = "9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60"
PUBLIC = "d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a"
OTHER_PUBLIC = "3d4017c3e843895a92b70aa74d1b7ebc9c982ccf2ec4968cc0cd55f12af4660c"
SHIP_LOG = (
    "2026-10-28T06:49:56Z v1.2.0 merged to main as 4a6564b. Building images.\n"
    "2026-10-28T07:39:00Z v1.2.0 is live on production and its canary passed: https://sx.example\n"
)

# A fake gh: logs every call; the run list shows run 100 until a dispatch, then 101; run 101 ends as
# FAKE_GH_OUTCOME (default success); its artifact is the bundle packed beforehand in ARTIFACT.
GH = """
import json, os, shutil, sys
here = os.path.dirname(sys.argv[0])
args = sys.argv[1:]
with open(os.path.join(here, "gh.log"), "a") as log:
    log.write(json.dumps(args) + "\\n")
dispatched = os.path.join(here, "dispatched")
if args[:2] == ["workflow", "run"]:
    open(dispatched, "w").close()
elif args[:2] == ["run", "list"]:
    print("101" if os.path.exists(dispatched) else "100")
elif args[:2] == ["run", "view"]:
    print("completed " + os.environ.get("FAKE_GH_OUTCOME", "success"))
elif args[:2] == ["run", "download"]:
    target = args[args.index("-D") + 1]
    os.makedirs(target, exist_ok=True)
    for name in os.listdir(os.environ["ARTIFACT"]):
        shutil.copy(os.path.join(os.environ["ARTIFACT"], name), target)
elif args[0] == "api" and args[1].endswith("/commits/4a6564b"):
    print("FULL_SHA")
""".replace("FULL_SHA", FULL)

# Infisical's run wrapper: only the /app-web path of prod, and the key reaches the command alone.
SECRETS = f"""
import os, sys
assert os.environ.get("AC_INFISICAL_ENVIRONMENT") == "prod"
assert os.environ.get("AC_INFISICAL_PATH") == "/app-web"
args = sys.argv[1:]
assert args[0] == "--", args
os.environ["AC_SX_WEB_BUNDLE_SIGNING_KEY"] = "{SEED}"
os.execvp(args[1], args[1:])
"""

# curl to production: answers with what was published under ROOT.
CURL = """
import os, shutil, sys
args = sys.argv[1:]
shutil.copy(os.path.join(os.environ["PUBLISHED"], "manifest.json"), args[args.index("-o") + 1])
"""


def _fake(path: Path, body: str) -> None:
    path.write_text(f"#!{sys.executable}\n{body}")
    path.chmod(path.stat().st_mode | stat.S_IEXEC)


def _artifact(tmp_path: Path) -> Path:
    export = tmp_path / "export"
    for name in (
        "index.html",
        "dashboard/index.html",
        "leads/index.html",
        "chats/index.html",
        "a.js",
    ):
        (export / name).parent.mkdir(parents=True, exist_ok=True)
        (export / name).write_text(name)
    artifact = tmp_path / "artifact"
    command = [sys.executable, str(TOOL), "pack", str(export), "--out", str(artifact)]
    command += [
        "--host",
        "salesxray.authorityclosers.com",
        "--sha",
        FULL,
        "--commit-at-ms",
        "1761650000000",
    ]
    subprocess.run(command, check=True, capture_output=True, timeout=60)  # noqa: S603
    return artifact


def _run(
    tmp_path: Path,
    *,
    enabled: int = 1,
    public_key: str = PUBLIC,
    state: str | None = None,
    run_file: str | None = None,
    outcome: str = "success",
) -> subprocess.CompletedProcess[str]:
    _fake(tmp_path / "gh", GH)
    _fake(tmp_path / "secrets", SECRETS)
    _fake(tmp_path / "curl", CURL)
    run_tool = f"import runpy, sys\nsys.argv[0] = {str(TOOL)!r}\n"
    run_tool += f"runpy.run_path({str(TOOL)!r}, run_name='__main__')\n"
    _fake(tmp_path / "tool", run_tool)
    _fake(
        tmp_path / "notify",
        "import sys\nopen(sys.argv[0] + '.log', 'a').write(sys.argv[1] + '\\n')\n",
    )
    (tmp_path / "ac-ship.log").write_text(SHIP_LOG)
    published = tmp_path / "app-web"
    (tmp_path / "conf").write_text(
        f'ENABLED={enabled}\nPUBLIC_KEY="{public_key}"\nROOT="{published}"\n'
    )
    state_dir = tmp_path / "state"
    state_dir.mkdir(exist_ok=True)
    if state is not None:
        (state_dir / "last").write_text(state + "\n")
    if run_file is not None:
        (state_dir / "run").write_text(run_file + "\n")
    env = dict(os.environ)
    env.update(
        AC_WEB_BUNDLE_SHIP_LOG=str(tmp_path / "ac-ship.log"),
        AC_WEB_BUNDLE_LOG=str(tmp_path / "hook.log"),
        AC_WEB_BUNDLE_STATE=str(state_dir),
        AC_WEB_BUNDLE_CONF=str(tmp_path / "conf"),
        AC_WEB_BUNDLE_NOTIFY=str(tmp_path / "notify"),
        AC_WEB_BUNDLE_GH=str(tmp_path / "gh"),
        AC_WEB_BUNDLE_SECRETS=str(tmp_path / "secrets"),
        AC_WEB_BUNDLE_TOOL=str(tmp_path / "tool"),
        AC_WEB_BUNDLE_CURL=str(tmp_path / "curl"),
        AC_WEB_BUNDLE_PAUSE="0",
        AC_WEB_BUNDLE_ROUNDS="3",
        ARTIFACT=str(_artifact(tmp_path)),
        PUBLISHED=str(published),
        FAKE_GH_OUTCOME=outcome,
    )
    env.pop("AC_SX_WEB_BUNDLE_SIGNING_KEY", None)
    return subprocess.run(  # noqa: S603
        ["/bin/bash", str(SCRIPT)],
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )


def _calls(tmp_path: Path) -> list[list[str]]:
    log = tmp_path / "gh.log"
    return [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []


def test_off_until_enabled_does_nothing(tmp_path: Path) -> None:
    result = _run(tmp_path, enabled=0)
    assert result.returncode == 0
    assert _calls(tmp_path) == []
    assert not (tmp_path / "app-web").exists()


def test_enabled_without_the_apps_public_key_publishes_nothing(tmp_path: Path) -> None:
    result = _run(tmp_path, public_key="")
    assert result.returncode == 1
    assert _calls(tmp_path) == []
    assert "PUBLIC_KEY" in (tmp_path / "hook.log").read_text()


def test_a_release_already_published_is_not_published_again(tmp_path: Path) -> None:
    result = _run(tmp_path, state="v1.2.0")
    assert result.returncode == 0
    assert _calls(tmp_path) == []


def test_a_new_release_builds_its_exact_commit_signs_and_publishes(tmp_path: Path) -> None:
    result = _run(tmp_path, state="v1.1.0")
    assert result.returncode == 0, (result.stderr, (tmp_path / "hook.log").read_text())
    dispatches = [c for c in _calls(tmp_path) if c[:2] == ["workflow", "run"]]
    assert len(dispatches) == 1
    call = dispatches[0]
    assert call[2] == "sales-xray-web-bundle.yml" and call[call.index("--ref") + 1] == "main"
    assert f"frozen_sha={FULL}" in call and "host=salesxray.authorityclosers.com" in call
    manifest = json.loads((tmp_path / "app-web" / "manifest.json").read_text())
    payload = json.loads(manifest["payload"])
    assert manifest["key"] == PUBLIC
    assert payload["version"] == "1.2.0" and payload["sha"] == FULL and payload["minNative"] == 1
    assert (tmp_path / "app-web" / payload["bundle"]).is_file()
    assert (tmp_path / "state" / "last").read_text().strip() == "v1.2.0"
    assert not (tmp_path / "state" / "run").exists()
    assert "pick up v1.2.0's web app by themselves" in (tmp_path / "notify.log").read_text()
    assert SEED not in (tmp_path / "hook.log").read_text() + result.stdout + result.stderr
    assert not list((tmp_path / "state").glob("work.*")), "the work folder is removed"


def test_a_key_that_isnt_the_apps_pinned_one_publishes_nothing(tmp_path: Path) -> None:
    result = _run(tmp_path, state="v1.1.0", public_key=OTHER_PUBLIC)
    assert result.returncode == 1
    assert "does not open with the apps' pinned key" in (tmp_path / "hook.log").read_text()
    assert not (tmp_path / "app-web" / "manifest.json").exists()
    assert (tmp_path / "state" / "last").read_text().strip() == "v1.1.0"


def test_a_failed_build_is_reported_once_and_nothing_is_published(tmp_path: Path) -> None:
    result = _run(tmp_path, state="v1.1.0", outcome="failure")
    assert result.returncode == 1
    assert not (tmp_path / "app-web").exists()
    assert (tmp_path / "state" / "last").read_text().strip() == "v1.2.0"
    assert "did not build" in (tmp_path / "notify.log").read_text()


def test_a_build_already_started_for_the_release_is_waited_on_not_repeated(tmp_path: Path) -> None:
    result = _run(tmp_path, state="v1.1.0", run_file="v1.2.0 101")
    assert result.returncode == 0, (tmp_path / "hook.log").read_text()
    assert not [c for c in _calls(tmp_path) if c[:2] == ["workflow", "run"]]
    assert _calls(tmp_path)[1][:3] == ["run", "view", "101"]


def test_the_hook_signs_only_through_infisicals_app_web_path() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    assert "AC_INFISICAL_ENVIRONMENT=prod AC_INFISICAL_PATH=/app-web" in text
    assert "AC_SX_WEB_BUNDLE_SIGNING_KEY" not in text.split("set -uo pipefail", 1)[1]


def test_units_run_the_installed_hook_every_five_minutes() -> None:
    service = SERVICE.read_text(encoding="utf-8")
    timer = TIMER.read_text(encoding="utf-8")
    assert "Type=oneshot" in service
    assert "ExecStart=/usr/local/sbin/ac-web-bundle-after-release" in service
    assert "OnCalendar=*:2/5" in timer
    assert "WantedBy=timers.target" in timer
