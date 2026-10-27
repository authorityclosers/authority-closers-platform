"""wb-ci waits by itself while a release is cutting or shipping (orchestrator, 27 Oct 2026: session
runs shared the cut's ci-prerequisites concurrency group and cancelled its checks on two nights)."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
WB_CI = ROOT / "scripts/ci/wb-ci"
BASH = shutil.which("bash") or "/bin/bash"
HOLD = "c4dd6f9f6d0ed6a1e8642a5185add44b7e0a8376"
OTHER = "3ed5ba2b5aa1c2d3e4f5061728394a5b6c7d8e9f"

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="bash and /proc")


def _wait_code() -> str:
    """The marker and the wait, exactly as wb-ci has them."""
    text = WB_CI.read_text(encoding="utf-8")
    found = re.search(
        r"^CUT_MARKER=.*?^wait_for_release\(\) \{.*?^\}\n", text, re.MULTILINE | re.DOTALL
    )
    assert found, "wb-ci lost its release wait"
    return found.group(0) + 'wait_for_release "$1"; echo "exit $?"\n'


def _env(marker: Path, limit: int) -> dict[str, str]:
    return {
        **os.environ,
        "WB_CI_CUT_MARKER": str(marker),
        "WB_CI_CUT_WAIT_S": str(limit),
        "WB_CI_CUT_POLL_S": "1",
    }


def _run(tmp_path: Path, marker: str | None, sha: str) -> subprocess.CompletedProcess[str]:
    path = tmp_path / "ac-release-cut.active"
    if marker is not None:
        path.write_text(marker, encoding="utf-8")
    return subprocess.run(  # noqa: S603 - the script's own lines, fixed executable
        [BASH, "-c", _wait_code(), "wb-ci", sha],
        capture_output=True,
        text=True,
        env=_env(path, 1),
        timeout=30,
        check=False,
    )


def test_no_marker_no_wait(tmp_path: Path) -> None:
    done = _run(tmp_path, None, OTHER)
    assert done.stdout.strip() == "exit 0"
    assert done.stderr == ""


def test_the_cuts_own_runs_pass_and_others_wait_then_fail_clearly(tmp_path: Path) -> None:
    alive = os.getpid()
    own = _run(tmp_path, f"v1.00.0 {HOLD} {alive}\n", HOLD)
    assert own.stdout.strip() == "exit 0"
    assert "waiting" not in own.stderr
    # A short hold sha matches the full one.
    assert _run(tmp_path, f"v1.00.0 {HOLD[:9]} {alive}\n", HOLD).stdout.strip() == "exit 0"
    other = _run(tmp_path, f"v1.00.0 {HOLD} {alive}\n", OTHER)
    assert other.stdout.strip() == "exit 75"
    assert "waiting for the v1.00.0 release to finish" in other.stderr
    assert "still cutting or shipping" in other.stderr
    # Before the hold is known, every run waits, the cut's own included.
    pending = _run(tmp_path, f"v1.00.0 - {alive}\n", HOLD)
    assert pending.stdout.strip() == "exit 75"


def test_a_run_goes_on_once_the_cut_ends(tmp_path: Path) -> None:
    path = tmp_path / "ac-release-cut.active"
    path.write_text(f"v1.00.0 {HOLD} {os.getpid()}\n", encoding="utf-8")
    waiting = subprocess.Popen(  # noqa: S603 - the script's own lines, fixed executable
        [BASH, "-c", _wait_code(), "wb-ci", OTHER],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=_env(path, 30),
    )
    assert waiting.stderr is not None
    assert "waiting for the v1.00.0 release" in waiting.stderr.readline()
    path.unlink()  # the cut script's exit trap
    out, _ = waiting.communicate(timeout=20)
    assert out.strip() == "exit 0"


def test_a_marker_left_by_a_killed_cut_is_ignored(tmp_path: Path) -> None:
    ended = subprocess.run(  # noqa: S603 - fixed executable and arguments
        [BASH, "-c", "echo $$"], capture_output=True, text=True, check=True
    )
    done = _run(tmp_path, f"v1.00.0 {HOLD} {ended.stdout.strip()}\n", OTHER)
    assert done.stdout.strip() == "exit 0"
    # A marker without a newline or a pid still counts; an empty one does not.
    assert _run(tmp_path, f"v1.00.0 {HOLD}", OTHER).stdout.strip() == "exit 75"
    assert _run(tmp_path, "", OTHER).stdout.strip() == "exit 0"


def test_wb_ci_waits_before_it_takes_a_slot_or_pushes() -> None:
    text = WB_CI.read_text(encoding="utf-8")
    wait = text.index('wait_for_release "$sha" || exit $?')
    assert text.index("short=${sha:0:8}") < wait < text.index('exec 9>"$LOCKS/slot-$n.lock"')
    assert wait < text.index("push()")
    assert "CUT_MARKER=${WB_CI_CUT_MARKER:-/run/ac-release-cut.active}" in text
