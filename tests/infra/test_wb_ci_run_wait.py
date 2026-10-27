"""wb-ci waits until GitHub says a run is completed (orchestrator, 27 Oct 2026).

`gh run watch` returned early, wb-ci printed an empty result and freed its slot, and the next
request in that slot cancelled run 40530203131. A dropped watch must never read as success.
"""

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
WATCH = 'gh run watch "$1"'

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="bash")

# A gh whose watch drops at once. `run view` answers in_progress until call GH_DONE_AT, and fails
# outright on the calls listed in GH_FAIL (a transient API error).
FAKE_GH = """#!/bin/bash
echo "$*" >> "$GH_LOG"
case "$1 $2" in
  "run watch") exit 1 ;;
  "run view")
    n=$(( $(cat "$GH_COUNT" 2>/dev/null || echo 0) + 1 )); echo "$n" > "$GH_COUNT"
    case " $GH_FAIL " in *" $n "*) exit 1 ;; esac
    if [ "$n" -ge "$GH_DONE_AT" ]; then echo completed; else echo in_progress; fi ;;
  *) exit 2 ;;
esac
"""


def _wait_code() -> str:
    """The run wait, exactly as wb-ci has it."""
    text = WB_CI.read_text(encoding="utf-8")
    found = re.search(r"^wait_for_run\(\) \{.*?^\}\n", text, re.MULTILINE | re.DOTALL)
    assert found, "wb-ci lost its run wait"
    setup = "REPO=owner/repo; tmp=$(mktemp -d)\n"
    return setup + found.group(0) + 'wait_for_run 123; echo "exit $?"\n'


def _run(
    tmp_path: Path, done_at: int, *, fail: str = "", limit: int = 30
) -> tuple[subprocess.CompletedProcess[str], list[str]]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    gh = bin_dir / "gh"
    gh.write_text(FAKE_GH, encoding="utf-8")
    gh.chmod(0o755)
    log = tmp_path / "gh.log"
    done = subprocess.run(  # noqa: S603 - the script's own lines, fixed executable
        [BASH, "-c", _wait_code()],
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
            "GH_LOG": str(log),
            "GH_COUNT": str(tmp_path / "count"),
            "GH_DONE_AT": str(done_at),
            "GH_FAIL": fail,
            "WB_CI_RUN_POLL_S": "1",
            "WB_CI_RUN_WAIT_S": str(limit),
        },
        timeout=60,
        check=False,
    )
    calls = log.read_text(encoding="utf-8").splitlines() if log.exists() else []
    return done, calls


def _views(calls: list[str]) -> list[str]:
    return [call for call in calls if call.startswith("run view 123")]


def test_a_dropped_watch_waits_until_github_says_completed(tmp_path: Path) -> None:
    done, calls = _run(tmp_path, done_at=3)
    assert done.stdout.strip() == "exit 0"
    assert calls[0].startswith("run watch 123 -R owner/repo")
    assert len(_views(calls)) == 3
    assert all("--json status --jq .status" in call for call in _views(calls))
    assert "the watch ended but run 123 is in_progress; checking every 1s" in done.stderr


def test_a_completed_run_is_read_at_once(tmp_path: Path) -> None:
    done, calls = _run(tmp_path, done_at=1)
    assert done.stdout.strip() == "exit 0"
    assert len(_views(calls)) == 1
    assert done.stderr == ""


def test_an_unreadable_status_is_not_completed_and_the_wait_goes_on(tmp_path: Path) -> None:
    done, calls = _run(tmp_path, done_at=3, fail="1 2")
    assert done.stdout.strip() == "exit 0"
    assert "is unreadable" in done.stderr
    assert len(_views(calls)) == 3


def test_a_run_still_going_at_the_limit_is_no_result(tmp_path: Path) -> None:
    done, _ = _run(tmp_path, done_at=10_000, limit=2)
    assert done.stdout.strip() == "exit 1"
    assert "run 123 is still in_progress after 0 min of waiting; no result" in done.stderr


def test_wb_ci_reads_the_result_and_frees_the_slot_only_after_the_run_is_done() -> None:
    text = WB_CI.read_text(encoding="utf-8")
    # The only watch is inside the wait.
    assert text.count("gh run watch ") == 1
    wait = text.index('if ! wait_for_run "$run"; then')
    assert text.index("wait_for_run() {") < text.index(WATCH) < wait
    # Still running: an unknown result and a failure, the branch left for the run.
    after = text[wait : text.index("fi\n", wait)]
    assert 'echo "result: unknown (still running: $url)"' in after
    assert "exit 1" in after
    assert "cleanup" not in after
    # The summary, the cleanup and the success check all come after the wait.
    cleanup = text.rindex("\ncleanup\n")
    assert wait < text.index("--json conclusion,jobs") < cleanup
    assert cleanup < text.index("grep -q '^result: success$'")
