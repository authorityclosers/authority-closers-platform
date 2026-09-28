"""Behaviour of the single-track work gate (scripts/ac_task.py)."""

from __future__ import annotations

import importlib.util
import json
import sys
from collections.abc import Sequence
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("ac_task", ROOT / "scripts/ac_task.py")
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules["ac_task"] = MODULE
SPEC.loader.exec_module(MODULE)

MAIN = "a" * 40


class FakeRepo:
    """Answers the git and gh commands the gate issues."""

    def __init__(self) -> None:
        self.branches = ["main"]
        self.prs: list[dict[str, object]] = []
        self.main_runs = [{"run_number": 1, "status": "completed", "conclusion": "success"}]
        self.current = "main"
        self.dirty = False
        self.calls: list[list[str]] = []

    def __call__(self, argv: Sequence[str]) -> str:
        argv = list(argv)
        self.calls.append(argv)
        if argv[:3] == ["git", "ls-remote", "--heads"]:
            return "".join(f"{MAIN}\trefs/heads/{name}\n" for name in self.branches)
        if argv[:3] == ["git", "ls-remote", "origin"]:
            return f"{MAIN}\trefs/heads/main\n"
        if argv[:2] == ["gh", "pr"]:
            return json.dumps(self.prs)
        if argv[:2] == ["gh", "api"]:
            return json.dumps({"workflow_runs": self.main_runs})
        if argv[:2] == ["git", "rev-parse"]:
            return self.current + "\n"
        if argv[:2] == ["git", "status"]:
            return " M file.py\n" if self.dirty else ""
        if argv[:2] == ["git", "switch"]:
            self.current = argv[-2] if "--create" in argv else argv[-1]
            return ""
        if argv[:2] == ["git", "push"]:
            self.branches.append(argv[-1])
            return ""
        if argv[:2] in (["git", "fetch"], ["git", "merge"], ["git", "branch"]):
            return ""
        raise AssertionError(f"unexpected command {argv}")


def gate(repo: FakeRepo):
    return MODULE.Gate(runner=repo)


def test_free_when_only_main_exists_and_is_green() -> None:
    verdict = gate(FakeRepo()).assess()
    assert verdict.free and verdict.main_state == "green"


def test_another_task_branch_blocks_new_work() -> None:
    repo = FakeRepo()
    repo.branches.append("task/75-design-engineer-launcher")
    verdict = gate(repo).assess()
    assert not verdict.free
    assert "task/75-design-engineer-launcher" in verdict.reasons[0]


def test_open_pull_request_blocks_new_work() -> None:
    repo = FakeRepo()
    repo.prs = [{"number": 80, "headRefName": "task/80-x", "title": "Something"}]
    assert "#80 Something" in gate(repo).assess().open_prs


@pytest.mark.parametrize(
    ("runs", "state"),
    [
        ([], "running"),
        ([{"run_number": 3, "status": "in_progress", "conclusion": None}], "running"),
        ([{"run_number": 3, "status": "completed", "conclusion": "failure"}], "red"),
        (
            [
                {"run_number": 2, "status": "completed", "conclusion": "failure"},
                {"run_number": 3, "status": "completed", "conclusion": "success"},
            ],
            "green",
        ),
    ],
)
def test_main_must_be_green_to_start(runs, state) -> None:
    repo = FakeRepo()
    repo.main_runs = runs
    verdict = gate(repo).assess()
    assert verdict.main_state == state
    assert verdict.free is (state == "green")


def test_start_claims_the_lock_from_latest_main() -> None:
    repo = FakeRepo()
    branch = gate(repo).start("76-single-track-gate")
    assert branch == "task/76-single-track-gate"
    assert ["git", "switch", "--quiet", "--create", branch, "origin/main"] in repo.calls
    assert branch in repo.branches


def test_start_refuses_while_busy_and_touches_nothing() -> None:
    repo = FakeRepo()
    repo.branches.append("task/75-other")
    with pytest.raises(MODULE.BusyError):
        gate(repo).start("76-single-track-gate")
    assert not any(call[:2] in (["git", "switch"], ["git", "push"]) for call in repo.calls)


@pytest.mark.parametrize("name", ["single-track", "76", "76_Fix", "76-Fix", "../76-x"])
def test_start_requires_issue_prefixed_names(name) -> None:
    with pytest.raises(MODULE.TaskError, match="task name"):
        gate(FakeRepo()).start(name)


def test_start_refuses_uncommitted_changes() -> None:
    repo = FakeRepo()
    repo.dirty = True
    with pytest.raises(MODULE.TaskError, match="uncommitted"):
        gate(repo).start("76-single-track-gate")


def test_the_active_task_may_keep_working_while_main_moves_on() -> None:
    repo = FakeRepo()
    repo.branches.append("task/76-gate")
    repo.prs = [{"number": 77, "headRefName": "task/76-gate", "title": "Gate"}]
    repo.main_runs = [{"run_number": 9, "status": "in_progress", "conclusion": None}]
    repo.current = "task/76-gate"
    assert gate(repo).check().free


def test_check_blocks_a_second_task_and_unclaimed_branches() -> None:
    repo = FakeRepo()
    repo.branches += ["task/76-gate", "task/77-other"]
    repo.current = "task/76-gate"
    assert not gate(repo).check().free
    repo.current = "task/78-unclaimed"
    assert "not claimed" in gate(repo).check().reasons[0]
    repo.current = "feature/x"
    assert "task/* branches" in gate(repo).check().reasons[0]


def test_done_requires_the_branch_to_be_merged_away() -> None:
    repo = FakeRepo()
    repo.branches.append("task/76-gate")
    repo.current = "task/76-gate"
    with pytest.raises(MODULE.TaskError, match="still exists"):
        gate(repo).done()
    repo.branches.remove("task/76-gate")
    assert gate(repo).done() == "task/76-gate"
    assert repo.current == "main"


def test_cli_exit_codes(capsys) -> None:
    repo = FakeRepo()
    assert MODULE.main(["status"], gate(repo)) == 0
    repo.branches.append("task/75-other")
    assert MODULE.main(["status"], gate(repo)) == MODULE.EXIT_BUSY
    assert MODULE.main(["start", "76-x"], gate(repo)) == MODULE.EXIT_BUSY
    assert "one task at a time" in capsys.readouterr().err
