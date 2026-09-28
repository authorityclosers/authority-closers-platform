#!/usr/bin/env python3
"""Single-track work gate: one task at a time across every agent and device.

GitHub is the shared lock. A task is active while its `task/<issue>-<name>`
branch exists on GitHub; merging its pull request deletes the branch and frees
the lock. Nobody starts new work while another branch or pull request is open,
or while the latest `main` build is not green.

    python scripts/ac_task.py status            show what is open and whether work may start
    python scripts/ac_task.py start 76-my-fix   claim the lock and branch from the latest main
    python scripts/ac_task.py check             exit 0 only if the current branch may be worked on
    python scripts/ac_task.py done              after the merge: back to main, delete the branch

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

REPOSITORY = "authorityclosers/authority-closers-platform"
VALIDATION_WORKFLOW = "application.yml"
TASK_NAME_RE = re.compile(r"[0-9]+-[a-z0-9]+(?:-[a-z0-9]+)*")
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


@dataclass
class Verdict:
    """Whether new work may start, and why not."""

    reasons: list[str] = field(default_factory=list)
    active_branches: list[str] = field(default_factory=list)
    open_prs: list[str] = field(default_factory=list)
    main_state: str = "unknown"

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

    def open_pull_requests(self) -> list[dict[str, object]]:
        data = self.gh(
            "pr",
            "list",
            "-R",
            REPOSITORY,
            "--state",
            "open",
            "--json",
            "number,headRefName,title",
            "--limit",
            "100",
        )
        return list(json.loads(data or "[]"))

    def main_state(self) -> str:
        """green | running | red | unknown for the latest main commit's validation."""

        head = self.git("ls-remote", "origin", "refs/heads/main").split("\t", 1)[0].strip()
        if not re.fullmatch(r"[0-9a-f]{40}", head):
            return "unknown"
        data = json.loads(
            self.gh(
                "api",
                f"repos/{REPOSITORY}/actions/workflows/{VALIDATION_WORKFLOW}/runs"
                f"?branch=main&event=push&head_sha={head}&per_page=5",
            )
            or "{}"
        )
        runs = data.get("workflow_runs", [])
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

    # -- decisions ---------------------------------------------------------------

    def assess(self, own_branch: str | None = None) -> Verdict:
        verdict = Verdict()
        verdict.active_branches = [
            name for name in self.remote_branches() if name != "main" and name != own_branch
        ]
        for pr in self.open_pull_requests():
            if pr.get("headRefName") != own_branch:
                verdict.open_prs.append(f"#{pr.get('number')} {pr.get('title')}")
        verdict.main_state = self.main_state()
        if verdict.active_branches:
            verdict.reasons.append(
                "another task is in progress: " + ", ".join(verdict.active_branches)
            )
        if verdict.open_prs:
            verdict.reasons.append("open pull request(s): " + "; ".join(verdict.open_prs))
        if verdict.main_state != "green":
            verdict.reasons.append(f"main is not green yet ({verdict.main_state})")
        return verdict

    def start(self, name: str) -> str:
        if not TASK_NAME_RE.fullmatch(name):
            raise TaskError(
                "task name must look like <issue>-<short-name>, e.g. 76-single-track-gate"
            )
        branch = f"task/{name}"
        if not self.is_clean():
            raise TaskError("this folder has uncommitted changes; finish or stash them first")
        self.git("fetch", "--quiet", "--prune", "origin")
        verdict = self.assess()
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
        verdict = self.assess(own_branch=branch)
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


class BusyError(TaskError):
    def __init__(self, verdict: Verdict) -> None:
        super().__init__("; ".join(verdict.reasons))
        self.verdict = verdict


def _describe(verdict: Verdict) -> str:
    lines = [f"main: {verdict.main_state}"]
    lines.append("active task branches: " + (", ".join(verdict.active_branches) or "none"))
    lines.append("open pull requests: " + ("; ".join(verdict.open_prs) or "none"))
    if verdict.free:
        lines.append("FREE: new work may start")
    else:
        lines.extend(f"BUSY: {reason}" for reason in verdict.reasons)
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None, gate: Gate | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="ac_task", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("status")
    start = sub.add_parser("start")
    start.add_argument("name", help="<issue>-<short-name>, e.g. 76-single-track-gate")
    sub.add_parser("check")
    sub.add_parser("done")
    args = parser.parse_args(argv)
    gate = gate or Gate()
    try:
        if args.command == "status":
            gate.git("fetch", "--quiet", "--prune", "origin")
            verdict = gate.assess()
            print(_describe(verdict))
            return 0 if verdict.free else EXIT_BUSY
        if args.command == "start":
            print(f"started {gate.start(args.name)} from the latest main; the lock is claimed")
            return 0
        if args.command == "check":
            verdict = gate.check()
            if verdict.free:
                print(f"ok: {gate.current_branch()} may be worked on")
                return 0
            print(_describe(verdict), file=sys.stderr)
            return EXIT_BUSY
        print(f"finished {gate.done()}; back on the latest main")
        return 0
    except BusyError as error:
        print(_describe(error.verdict), file=sys.stderr)
        print("Stop: finish the open task first (one task at a time, AGENTS.md).", file=sys.stderr)
        return EXIT_BUSY
    except TaskError as error:
        print(f"ac_task: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
