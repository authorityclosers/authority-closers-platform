#!/usr/bin/env python3
"""Work gate: one task at a time per lane, up to five lanes in parallel.

GitHub is the shared lock. A task is active while its branch exists on GitHub;
merging its pull request deletes the branch and frees the lock.

- A lane task lives on `task/<lane>/<issue>-<name>`. Each lane (sales-xray,
  platform, admin, ui, devenv) holds one task at a time; different lanes run in parallel.
- A plain `task/<issue>-<name>` branch is exclusive: it runs alone, as before.
- A red or unknown `main` blocks new work; the task that fixes a red `main` may
  start with `--fixes-red-main`. A running `main` build does not block a start;
  merges still wait for a green `main`.
- Pull requests may not change the same file, and only one open pull request at
  a time may touch shared files (migrations, lockfiles, workflows, AGENTS.md).

    python scripts/ac_task.py status [--json]          what is open, which lanes are free
    python scripts/ac_task.py start sales-xray 81-fix  claim a lane and branch from main
    python scripts/ac_task.py start 76-my-fix          claim everything (exclusive task)
    python scripts/ac_task.py check                    may this branch be worked on?
    python scripts/ac_task.py done                     after the merge: back to main
    python scripts/ac_task.py pr-check 90              CI: may this pull request stay open?

Needs `git` and an authenticated `gh` (GitHub CLI).
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

REPOSITORY = "authorityclosers/authority-closers-platform"
VALIDATION_WORKFLOW = "application.yml"
TASK_NAME_RE = re.compile(r"[0-9]+-[a-z0-9]+(?:-[a-z0-9]+)*")
LANES = ("sales-xray", "platform", "admin", "ui", "devenv")
EXCLUSIVE = "exclusive"
SHARED_PREFIXES = ("db/migrations/", ".github/")
SHARED_FILES = frozenset(
    {
        "AGENTS.md",
        "CLAUDE.md",
        "package.json",
        "pnpm-lock.yaml",
        "pnpm-workspace.yaml",
        "pyproject.toml",
        "uv.lock",
        "packages/python/ac_platform/db/models.py",
        "tests/database/test_model_registry.py",
        "scripts/ac_task.py",
    }
)
EXIT_BUSY = 3

Runner = Callable[[Sequence[str]], str]


class TaskError(RuntimeError):
    """A command failed or the repository is not in a state to continue."""


def run(argv: Sequence[str]) -> str:
    completed = subprocess.run(  # noqa: S603 - fixed git/gh argument lists
        list(argv), capture_output=True, text=True, check=False
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout).strip().splitlines()
        raise TaskError(
            f"{' '.join(argv[:3])} failed: {detail[-1] if detail else completed.returncode}"
        )
    return completed.stdout


def lane_of(branch: str) -> str:
    """The lane a branch holds; plain task branches and anything else are exclusive."""

    parts = branch.split("/")
    if len(parts) == 3 and parts[0] == "task" and parts[1] in LANES:
        return parts[1]
    return EXCLUSIVE


def is_shared(path: str) -> bool:
    return path in SHARED_FILES or path.startswith(SHARED_PREFIXES)


@dataclass
class Verdict:
    """Whether new work may start, and why not."""

    reasons: list[str] = field(default_factory=list)
    active_branches: list[str] = field(default_factory=list)
    open_prs: list[str] = field(default_factory=list)
    main_state: str = "unknown"
    lanes: dict[str, str | None] = field(default_factory=dict)

    @property
    def free(self) -> bool:
        return not self.reasons


@dataclass
class Gate:
    runner: Runner = run

    def git(self, *args: str) -> str:
        return self.runner(["git", *args])

    def gh(self, *args: str) -> str:
        return self.runner(["gh", *args])

    # -- facts -----------------------------------------------------------------

    def remote_branches(self) -> list[str]:
        names = []
        for line in self.git("ls-remote", "--heads", "origin").splitlines():
            _sha, _, ref = line.partition("\t")
            if ref.startswith("refs/heads/"):
                names.append(ref.removeprefix("refs/heads/"))
        return sorted(names)

    def open_pull_requests(self, fields: str = "number,headRefName,title") -> list[dict]:
        data = self.gh(
            "pr", "list", "-R", REPOSITORY, "--state", "open", "--json", fields, "--limit", "100"
        )
        return list(json.loads(data or "[]"))

    def main_state(self) -> str:
        """Only push and workflow_dispatch runs count for the latest main validation."""

        head = self.git("ls-remote", "origin", "refs/heads/main").split("\t", 1)[0].strip()
        if not re.fullmatch(r"[0-9a-f]{40}", head):
            return "unknown"
        data = json.loads(
            self.gh(
                "api",
                f"repos/{REPOSITORY}/actions/workflows/{VALIDATION_WORKFLOW}/runs"
                f"?branch=main&head_sha={head}&per_page=100",
            )
            or "{}"
        )
        runs = [
            item
            for item in data.get("workflow_runs", [])
            if item.get("event") in ("push", "workflow_dispatch")
        ]
        if not runs:
            return "running"
        latest = max(runs, key=lambda item: (item.get("run_number", 0), item.get("run_attempt", 0)))
        if latest.get("status") != "completed":
            return "running"
        return "green" if latest.get("conclusion") == "success" else "red"

    def current_branch(self) -> str:
        return self.git("rev-parse", "--abbrev-ref", "HEAD").strip()

    def is_clean(self) -> bool:
        return not self.git("status", "--porcelain", "--untracked-files=no").strip()

    def gate_matches_main(self) -> bool:
        """Whether this copy of the work gate matches the fetched main branch."""

        current = Path(__file__).read_text(encoding="utf-8")
        main = self.git("show", "origin/main:scripts/ac_task.py")
        return current == main

    # -- decisions ---------------------------------------------------------------

    def assess(self, own_branch: str | None = None, lane: str = EXCLUSIVE) -> Verdict:
        """May work in `lane` go ahead? An exclusive task needs everything else closed."""

        verdict = Verdict()
        branches = [name for name in self.remote_branches() if name not in ("main", own_branch)]
        verdict.active_branches = branches
        verdict.lanes = {name: None for name in LANES}
        for name in branches:
            if lane_of(name) in verdict.lanes:
                verdict.lanes[lane_of(name)] = name
        blocking = [
            name for name in branches if lane == EXCLUSIVE or lane_of(name) in (EXCLUSIVE, lane)
        ]
        prs = [pr for pr in self.open_pull_requests() if pr.get("headRefName") != own_branch]
        verdict.open_prs = [f"#{pr.get('number')} {pr.get('title')}" for pr in prs]
        blocking_prs = [
            f"#{pr.get('number')} {pr.get('title')}"
            for pr in prs
            if lane == EXCLUSIVE or lane_of(str(pr.get("headRefName"))) in (EXCLUSIVE, lane)
        ]
        verdict.main_state = self.main_state()
        if blocking:
            where = "" if lane == EXCLUSIVE else f" in the {lane} lane"
            verdict.reasons.append(f"another task is in progress{where}: " + ", ".join(blocking))
        if blocking_prs:
            verdict.reasons.append("open pull request(s): " + "; ".join(blocking_prs))
        if verdict.main_state == "red":
            verdict.reasons.append(
                "main is red: only the task that fixes it may start (start ... --fixes-red-main)"
            )
        elif verdict.main_state == "unknown":
            verdict.reasons.append("main is not green yet (unknown)")
        return verdict

    def start(self, name: str, lane: str = EXCLUSIVE, fixes_red_main: bool = False) -> str:
        if lane != EXCLUSIVE and lane not in LANES:
            raise TaskError(f"unknown lane {lane!r}; lanes are {', '.join(LANES)}")
        if not TASK_NAME_RE.fullmatch(name):
            raise TaskError(
                "task name must look like <issue>-<short-name>, e.g. 76-single-track-gate"
            )
        branch = f"task/{name}" if lane == EXCLUSIVE else f"task/{lane}/{name}"
        if not self.is_clean():
            raise TaskError("this folder has uncommitted changes; finish or stash them first")
        self.git("fetch", "--quiet", "--prune", "origin")
        current = self.current_branch()
        if current.startswith("task/") and current not in self.remote_branches():
            raise TaskError(
                f"current task branch {current} is missing from GitHub; "
                "run `python3 scripts/ac_task.py done` first"
            )
        if not self.gate_matches_main():
            remedy = (
                "run `python3 scripts/ac_task.py done` first"
                if current.startswith("task/")
                else "run `git switch main && git merge --ff-only origin/main` first"
            )
            raise TaskError(
                "running scripts/ac_task.py differs from origin/main:scripts/ac_task.py; " + remedy
            )
        verdict = self.assess(lane=lane)
        if fixes_red_main and verdict.main_state == "red":
            verdict.reasons = [
                reason for reason in verdict.reasons if not reason.startswith("main is red:")
            ]
        if not verdict.free:
            raise BusyError(verdict)
        self.git("switch", "--quiet", "--create", branch, "origin/main")
        # Pushing the branch claims the lock for every agent and device.
        self.git("push", "--quiet", "--set-upstream", "origin", branch)
        return branch

    def check(self) -> Verdict:
        branch = self.current_branch()
        if branch == "main":
            return self.assess()
        if not branch.startswith("task/"):
            verdict = Verdict(reasons=[f"work happens on task/* branches, not {branch}"])
            return verdict
        if branch not in self.remote_branches():
            return Verdict(reasons=[f"{branch} is not claimed on GitHub; run start first"])
        verdict = self.assess(own_branch=branch, lane=lane_of(branch))
        # main moving on is fine while you work; only other tasks block you.
        verdict.reasons = [reason for reason in verdict.reasons if not reason.startswith("main is")]
        return verdict

    def done(self) -> str:
        branch = self.current_branch()
        if not branch.startswith("task/"):
            raise TaskError("not on a task branch")
        self.git("fetch", "--quiet", "--prune", "origin")
        if branch in self.remote_branches():
            raise TaskError(
                f"{branch} still exists on GitHub; merge or close its pull request first"
            )
        if not self.is_clean():
            raise TaskError("uncommitted changes on the task branch; keep or discard them first")
        self.git("switch", "--quiet", "main")
        self.git("merge", "--quiet", "--ff-only", "origin/main")
        self.git("branch", "--quiet", "-D", branch)
        return branch

    def pr_check(self, number: int) -> list[str]:
        """Problems that forbid pull request `number` from being open right now."""

        prs = self.open_pull_requests("number,headRefName,title,files")
        mine = next((pr for pr in prs if pr.get("number") == number), None)
        if mine is None:
            return [f"#{number} is not an open pull request"]
        lane = lane_of(str(mine.get("headRefName")))
        files = {str(item.get("path")) for item in mine.get("files") or []}
        problems = []
        for other in prs:
            if other is mine:
                continue
            label = f"#{other.get('number')} {other.get('title')}"
            other_lane = lane_of(str(other.get("headRefName")))
            other_files = {str(item.get("path")) for item in other.get("files") or []}
            if EXCLUSIVE in (lane, other_lane):
                problems.append(f"{label} is open and one of the two is an exclusive task")
                continue
            if other_lane == lane:
                problems.append(f"{label} already holds the {lane} lane")
            overlap = sorted(files & other_files)
            if overlap:
                problems.append(f"{label} changes the same files: {', '.join(overlap[:5])}")
            shared = sorted(path for path in files if is_shared(path))
            if shared and any(is_shared(path) for path in other_files):
                problems.append(
                    f"{label} also changes shared files; one at a time ({', '.join(shared[:3])})"
                )
        return problems


class BusyError(TaskError):
    def __init__(self, verdict: Verdict) -> None:
        super().__init__("; ".join(verdict.reasons))
        self.verdict = verdict


def _describe(verdict: Verdict) -> str:
    lines = [f"main: {verdict.main_state}"]
    lines.append("active task branches: " + (", ".join(verdict.active_branches) or "none"))
    lines.append("open pull requests: " + ("; ".join(verdict.open_prs) or "none"))
    if verdict.lanes:
        lines.append(
            "lanes: "
            + ", ".join(f"{name}={holder or 'free'}" for name, holder in verdict.lanes.items())
        )
    if verdict.free:
        lines.append("FREE: new work may start")
    else:
        lines.extend(f"BUSY: {reason}" for reason in verdict.reasons)
    return "\n".join(lines)


def _status_verdict_line(label: str, verdict: Verdict) -> str:
    if verdict.free:
        return f"{label}: FREE"
    return f"{label}: BUSY: {'; '.join(verdict.reasons)}"


def _describe_status(gate: Gate, verdict: Verdict) -> str:
    """Describe start verdicts and, on task branches, the current task verdict."""

    lines = [_main_status_line(verdict.main_state)]
    lines.append("active task branches: " + (", ".join(verdict.active_branches) or "none"))
    lines.append("open pull requests: " + ("; ".join(verdict.open_prs) or "none"))
    if verdict.lanes:
        lines.append(
            "lanes: "
            + ", ".join(f"{name}={holder or 'free'}" for name, holder in verdict.lanes.items())
        )

    branch = gate.current_branch()
    if branch.startswith("task/"):
        task_verdict = gate.check()
        if task_verdict.free:
            task_state = "free to continue"
        else:
            blockers = "; ".join(task_verdict.reasons)
            task_state = f"blocked: {blockers}"
        lines.append(f"your task {branch}: {task_state}")

    lines.append("Start verdicts (BUSY applies to starting new work):")
    for lane in LANES:
        lines.append(_status_verdict_line(lane, gate.assess(lane=lane)))
    lines.append(_status_verdict_line("exclusive", verdict))
    return "\n".join(lines)


def _status_json(gate: Gate) -> dict[str, object]:
    """Per-lane view for automation: which lanes may start a task right now."""

    overall = gate.assess()
    free = {}
    for lane in LANES:
        verdict = gate.assess(lane=lane)
        free[lane] = verdict.free
    return {
        "main": overall.main_state,
        "active_branches": overall.active_branches,
        "open_prs": overall.open_prs,
        "lanes": {lane: {"holder": overall.lanes.get(lane), "free": free[lane]} for lane in LANES},
        "exclusive_free": overall.free,
    }


def _main_status_line(state: str) -> str:
    if state == "running":
        return "main: running (new tasks may start; merges wait for a green main)"
    if state == "red":
        return "main: red (only the task that fixes it may start, with --fixes-red-main)"
    return f"main: {state}"


def main(argv: Sequence[str] | None = None, gate: Gate | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="ac_task", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = parser.add_subparsers(dest="command", required=True)
    status = sub.add_parser("status")
    status.add_argument("--json", action="store_true", help="per-lane status for automation")
    start = sub.add_parser("start")
    start.add_argument(
        "names",
        nargs="+",
        metavar="[LANE] NAME",
        help=f"optional lane ({', '.join(LANES)}) then <issue>-<short-name>",
    )
    start.add_argument(
        "--fixes-red-main",
        action="store_true",
        help="allow this task to start while it fixes a red main build",
    )
    sub.add_parser("check")
    sub.add_parser("done")
    pr_check = sub.add_parser("pr-check")
    pr_check.add_argument("number", type=int)
    args = parser.parse_args(argv)
    gate = gate or Gate()
    try:
        if args.command == "status":
            gate.git("fetch", "--quiet", "--prune", "origin")
            if args.json:
                print(json.dumps(_status_json(gate)))
                return 0
            verdict = gate.assess()
            print(_describe_status(gate, verdict))
            return 0 if verdict.free else EXIT_BUSY
        if args.command == "start":
            if len(args.names) > 2:
                raise TaskError("start takes [LANE] NAME")
            lane, name = (EXCLUSIVE, args.names[0]) if len(args.names) == 1 else args.names
            print(
                f"started {gate.start(name, lane, args.fixes_red_main)} "
                "from the latest main; the lock is claimed"
            )
            return 0
        if args.command == "check":
            verdict = gate.check()
            if verdict.free:
                print(f"ok: {gate.current_branch()} may be worked on")
                return 0
            print(_describe(verdict), file=sys.stderr)
            return EXIT_BUSY
        if args.command == "pr-check":
            problems = gate.pr_check(args.number)
            for problem in problems:
                print(f"::error::{problem}. One task per lane, no shared files (AGENTS.md).")
            if not problems:
                print("This pull request may stay open: its lane is its own and no files overlap.")
            return 1 if problems else 0
        print(f"finished {gate.done()}; back on the latest main")
        return 0
    except BusyError as error:
        print(_describe(error.verdict), file=sys.stderr)
        if any(reason.startswith("main is red:") for reason in error.verdict.reasons):
            print(
                "Stop: main is red; only the task that fixes it may start, with --fixes-red-main.",
                file=sys.stderr,
            )
        else:
            print(
                "Stop: finish the open task first (one task per lane, AGENTS.md).", file=sys.stderr
            )
        return EXIT_BUSY
    except TaskError as error:
        print(f"ac_task: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
