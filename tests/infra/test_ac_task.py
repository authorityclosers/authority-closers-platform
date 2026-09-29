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
        self.main_gate_script = Path(MODULE.__file__).read_text(encoding="utf-8")
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
        if argv[:2] == ["git", "show"]:
            assert argv[2] == "origin/main:scripts/ac_task.py"
            return self.main_gate_script
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


def test_start_from_a_merged_task_branch_refuses_and_exits_two(capsys) -> None:
    repo = FakeRepo()
    repo.current = "task/ui/66-shell"

    assert MODULE.main(["start", "platform", "94-stale-gate"], gate(repo)) == 2

    assert capsys.readouterr().err == (
        "ac_task: current task branch task/ui/66-shell is missing from GitHub; "
        "run `python3 scripts/ac_task.py done` first\n"
    )
    assert ["git", "fetch", "--quiet", "--prune", "origin"] in repo.calls
    assert not any(call[:2] in (["git", "switch"], ["git", "push"]) for call in repo.calls)


def test_start_refuses_when_gate_copy_differs_from_fetched_main(capsys) -> None:
    repo = FakeRepo()
    repo.current = "task/platform/94-gate-edit"
    repo.branches.append(repo.current)
    repo.main_gate_script = "stale gate copy\n"

    assert MODULE.main(["start", "platform", "94-stale-gate"], gate(repo)) == 2

    assert capsys.readouterr().err == (
        "ac_task: running scripts/ac_task.py differs from "
        "origin/main:scripts/ac_task.py; run `python3 scripts/ac_task.py done` first\n"
    )
    fetch_index = repo.calls.index(["git", "fetch", "--quiet", "--prune", "origin"])
    show_index = repo.calls.index(["git", "show", "origin/main:scripts/ac_task.py"])
    assert fetch_index < show_index
    assert not any(call[:2] in (["git", "switch"], ["git", "push"]) for call in repo.calls)


def test_start_on_main_with_stale_gate_refuses_with_main_update_remedy(capsys) -> None:
    repo = FakeRepo()
    repo.main_gate_script = "newer main gate\n"

    assert MODULE.main(["start", "platform", "94-stale-gate"], gate(repo)) == 2

    assert capsys.readouterr().err == (
        "ac_task: running scripts/ac_task.py differs from "
        "origin/main:scripts/ac_task.py; run `git switch main && git merge --ff-only "
        "origin/main` first\n"
    )
    assert not any(call[:2] in (["git", "switch"], ["git", "push"]) for call in repo.calls)


def test_start_with_matching_gate_branches_from_origin_main() -> None:
    repo = FakeRepo()

    branch = gate(repo).start("94-stale-gate", "platform")

    assert branch == "task/platform/94-stale-gate"
    fetch_index = repo.calls.index(["git", "fetch", "--quiet", "--prune", "origin"])
    show_index = repo.calls.index(["git", "show", "origin/main:scripts/ac_task.py"])
    assert fetch_index < show_index
    assert ["git", "switch", "--quiet", "--create", branch, "origin/main"] in repo.calls


def test_check_on_gate_edit_branch_does_not_compare_gate_copy() -> None:
    repo = FakeRepo()
    branch = "task/platform/94-gate-edit"
    repo.branches.append(branch)
    repo.current = branch
    repo.main_gate_script = "different from this task branch\n"

    assert gate(repo).check().free
    assert not any(call[:2] == ["git", "show"] for call in repo.calls)


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
    assert "one task per lane" in capsys.readouterr().err


# -- lanes ---------------------------------------------------------------------


def test_lanes_run_in_parallel_but_hold_one_task_each() -> None:
    repo = FakeRepo()
    repo.branches.append("task/platform/23-release-notes")
    repo.prs = [{"number": 91, "headRefName": "task/platform/23-release-notes", "title": "R2"}]
    branch = gate(repo).start("46-plan-accept", "sales-xray")
    assert branch == "task/sales-xray/46-plan-accept"
    assert branch in repo.branches
    with pytest.raises(MODULE.BusyError, match="platform lane"):
        gate(repo).start("24-promote", "platform")


def test_devenv_lane_runs_beside_the_platform_lane() -> None:
    repo = FakeRepo()
    repo.branches.append("task/platform/23-release-notes")
    assert gate(repo).start("260-devenv-lane", "devenv") == "task/devenv/260-devenv-lane"


def test_an_exclusive_task_blocks_every_lane_and_is_blocked_by_any() -> None:
    repo = FakeRepo()
    repo.branches.append("task/83-development-hosted")
    with pytest.raises(MODULE.BusyError):
        gate(repo).start("46-plan-accept", "sales-xray")
    repo.branches = ["main", "task/admin/29-releases-page"]
    with pytest.raises(MODULE.BusyError):
        gate(repo).start("90-parallel-lanes")


def test_unknown_lanes_are_refused() -> None:
    with pytest.raises(MODULE.TaskError, match="unknown lane"):
        gate(FakeRepo()).start("46-x", "mobile")


def test_check_only_counts_the_own_lane_and_exclusive_work() -> None:
    repo = FakeRepo()
    repo.branches += ["task/sales-xray/46-fix", "task/platform/23-notes"]
    repo.current = "task/sales-xray/46-fix"
    assert gate(repo).check().free
    repo.branches.append("task/sales-xray/47-other")
    assert not gate(repo).check().free


def test_status_json_reports_each_lane(capsys) -> None:
    repo = FakeRepo()
    repo.branches.append("task/platform/23-notes")
    assert MODULE.main(["status", "--json"], gate(repo)) == 0
    output = capsys.readouterr().out
    assert output == (
        '{"main": "green", "active_branches": ["task/platform/23-notes"], '
        '"open_prs": [], "lanes": {"sales-xray": {"holder": null, "free": true}, '
        '"platform": {"holder": "task/platform/23-notes", "free": false}, '
        '"admin": {"holder": null, "free": true}, "ui": {"holder": null, "free": true}, '
        '"devenv": {"holder": null, "free": true}}, '
        '"exclusive_free": false}\n'
    )
    status = json.loads(output)
    assert status["lanes"]["platform"] == {"holder": "task/platform/23-notes", "free": False}
    assert status["lanes"]["sales-xray"]["free"] is True
    assert status["exclusive_free"] is False


def test_status_text_labels_each_lane_and_exclusive_verdict(capsys) -> None:
    repo = FakeRepo()
    repo.branches += ["task/sales-xray/81-http-source-readers", "task/ui/66-shell"]
    repo.prs = [
        {
            "number": 104,
            "headRefName": "task/sales-xray/81-http-source-readers",
            "title": "Resolve sources",
        }
    ]

    assert MODULE.main(["status"], gate(repo)) == MODULE.EXIT_BUSY
    output = capsys.readouterr().out
    assert "Start verdicts (BUSY applies to starting new work):" in output
    lines = output.splitlines()
    assert (
        "sales-xray: BUSY: another task is in progress in the sales-xray lane: "
        "task/sales-xray/81-http-source-readers; open pull request(s): #104 Resolve sources"
    ) in lines
    assert "platform: FREE" in lines
    assert "admin: FREE" in lines
    assert "ui: BUSY: another task is in progress in the ui lane: task/ui/66-shell" in lines
    assert any(line.startswith("exclusive: BUSY: ") for line in lines)
    assert sum(line.startswith("exclusive:") for line in lines) == 1


def test_status_text_shows_current_task_check_while_main_runs(capsys) -> None:
    repo = FakeRepo()
    branch = "task/admin/15-agent-scorecard"
    repo.branches.append(branch)
    repo.prs = [{"number": 99, "headRefName": branch, "title": "Scorecard"}]
    repo.main_runs = [{"run_number": 9, "status": "in_progress", "conclusion": None}]
    repo.current = branch

    assert MODULE.main(["status"], gate(repo)) == MODULE.EXIT_BUSY
    output = capsys.readouterr().out
    assert f"your task {branch}: free to continue" in output
    assert "BUSY applies to starting new work" in output
    assert "admin: BUSY: " in output


def test_cli_start_accepts_a_lane(capsys) -> None:
    repo = FakeRepo()
    assert MODULE.main(["start", "admin", "29-releases-page"], gate(repo)) == 0
    assert "task/admin/29-releases-page" in capsys.readouterr().out


def pr(number: int, head: str, *paths: str) -> dict[str, object]:
    return {
        "number": number,
        "headRefName": head,
        "title": f"PR {number}",
        "files": [{"path": path} for path in paths],
    }


def test_pr_check_allows_separate_lanes_with_separate_files() -> None:
    repo = FakeRepo()
    repo.prs = [
        pr(1, "task/sales-xray/46-a", "apps/sales-xray-web/app/a.tsx"),
        pr(2, "task/platform/23-b", "infra/release/ac_release.py"),
    ]
    assert gate(repo).pr_check(1) == []


@pytest.mark.parametrize(
    ("other", "expected"),
    [
        (pr(2, "task/sales-xray/47-b", "docs/b.md"), "already holds the sales-xray lane"),
        (pr(2, "task/platform/23-b", "docs/shared.md"), "same files: docs/shared.md"),
        (pr(2, "task/platform/23-b", "uv.lock"), "shared files"),
        (pr(2, "task/83-exclusive", "docs/b.md"), "exclusive task"),
        (pr(2, "dependabot/npm/x", "docs/b.md"), "exclusive task"),
    ],
)
def test_pr_check_refuses_conflicting_work(other, expected) -> None:
    repo = FakeRepo()
    mine = pr(1, "task/sales-xray/46-a", "docs/shared.md", "db/migrations/versions/x.py")
    repo.prs = [mine, other]
    problems = gate(repo).pr_check(1)
    assert problems and expected in problems[0]


def test_pr_check_cli_exit_codes(capsys) -> None:
    repo = FakeRepo()
    repo.prs = [pr(1, "task/admin/29-a", "apps/admin-web/a.tsx")]
    assert MODULE.main(["pr-check", "1"], gate(repo)) == 0
    repo.prs.append(pr(2, "task/admin/30-b", "apps/admin-web/b.tsx"))
    assert MODULE.main(["pr-check", "1"], gate(repo)) == 1
    assert "::error::" in capsys.readouterr().out


def test_the_ui_lane_runs_beside_the_sales_xray_lane() -> None:
    repo = FakeRepo()
    repo.branches.append("task/sales-xray/59-overview-tolerance")
    assert gate(repo).start("101-report-overview-look", "ui") == "task/ui/101-report-overview-look"
