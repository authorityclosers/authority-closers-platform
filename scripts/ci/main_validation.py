#!/usr/bin/env python3
"""Let a push to main reuse the release PR's validation of the same tree.

Release pipeline (owner, 24 Oct 2026: "we need to improve the release pipeline to reduce the time
for release"). Every merge to main re-ran the whole Application validation, about 19 of its 30
minutes, on a tree that the release pull request had passed minutes earlier. Only then did
packaging start.

Prints `reuse=true|false` lines for $GITHUB_OUTPUT. It is true only when all of these hold:
- this push to main is the merge of exactly one pull request from this repository;
- that pull request's head has exactly this commit's tree and contains main's previous commit;
- a completed, successful Application validation `pull_request` run exists for that head;
- that run's `validate` job passed.
Any other answer, including any API or git error, prints `reuse=false`, and the full validation
runs as before. It never fails the job.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import urllib.request
from collections.abc import Callable
from typing import Any

SHA = re.compile(r"[0-9a-f]{40}")
WORKFLOW_PATH = ".github/workflows/application.yml"
Api = Callable[[str], Any]
Git = Callable[..., str]


class NoReuse(Exception):
    """This push must run the full validation; the message says why."""


def github_api(path: str) -> Any:
    base = os.environ.get("GITHUB_API_URL", "https://api.github.com")
    request = urllib.request.Request(  # noqa: S310 - fixed GitHub API base from the runner
        base + path,
        headers={
            "Authorization": f"Bearer {os.environ['GH_TOKEN']}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310
        return json.load(response)


def git(*arguments: str) -> str:
    return subprocess.run(  # noqa: S603 - fixed git argv
        ["git", *arguments],  # noqa: S607
        check=True,
        capture_output=True,
        text=True,
        timeout=120,
    ).stdout.strip()


def reusable_run(api: Api, run_git: Git, repository: str, sha: str) -> dict[str, str]:
    if not SHA.fullmatch(sha):
        raise NoReuse("the pushed commit is not a full SHA")
    pulls = api(f"/repos/{repository}/commits/{sha}/pulls")
    merged = [
        pull
        for pull in pulls
        if pull.get("merged_at")
        and pull.get("merge_commit_sha") == sha
        and (pull.get("base") or {}).get("ref") == "main"
        and ((pull.get("head") or {}).get("repo") or {}).get("full_name") == repository
    ]
    if len(merged) != 1:
        raise NoReuse("this push is not the merge of exactly one pull request from this repository")
    number, head = int(merged[0]["number"]), str(merged[0]["head"]["sha"])
    if not SHA.fullmatch(head):
        raise NoReuse("the pull request head is malformed")
    run_git("fetch", "--quiet", "--no-tags", "origin", f"+refs/pull/{number}/head:refs/ac/pr-head")
    if run_git("rev-parse", "refs/ac/pr-head") != head:
        raise NoReuse("the pull request head moved after its merge")
    if run_git("rev-parse", f"{sha}^{{tree}}") != run_git("rev-parse", f"{head}^{{tree}}"):
        raise NoReuse("the merged tree differs from the tested pull request head")
    # Pull request checks test the head merged into the base of that moment. When the head
    # contains main's previous commit, every such base is in the head already, so the tested
    # merge is the head's own tree, which is this commit's tree.
    try:
        run_git("merge-base", "--is-ancestor", f"{sha}^", head)
    except subprocess.CalledProcessError:
        raise NoReuse("the pull request head does not contain main's previous commit") from None
    runs = api(
        f"/repos/{repository}/actions/workflows/application.yml/runs"
        f"?event=pull_request&head_sha={head}&per_page=20"
    ).get("workflow_runs", [])
    passed = [
        run
        for run in runs
        if run.get("head_sha") == head
        and run.get("event") == "pull_request"
        and run.get("path") == WORKFLOW_PATH
        and run.get("status") == "completed"
        and run.get("conclusion") == "success"
        and (run.get("repository") or {}).get("full_name") == repository
    ]
    if not passed:
        raise NoReuse("no successful Application validation run for the pull request head")
    run = max(passed, key=lambda item: (item.get("run_number", 0), item.get("run_attempt", 0)))
    jobs = api(f"/repos/{repository}/actions/runs/{int(run['id'])}/jobs?filter=latest&per_page=100")
    validate = [job for job in jobs.get("jobs", []) if job.get("name") == "validate"]
    if [job.get("conclusion") for job in validate] != ["success"]:
        raise NoReuse("the pull request run's validate job did not pass")
    return {"reuse": "true", "run": str(int(run["id"])), "pull": str(number), "head": head}


def decide(
    api: Api, run_git: Git, event: str, ref: str, repository: str, sha: str
) -> dict[str, str]:
    if event != "push" or ref != "refs/heads/main":
        return {"reuse": "false", "reason": "only pushes to main reuse a pull request's validation"}
    try:
        return reusable_run(api, run_git, repository, sha)
    except NoReuse as reason:
        return {"reuse": "false", "reason": str(reason)}
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError):
        return {"reuse": "false", "reason": "the pull request evidence could not be read"}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--event", required=True)
    parser.add_argument("--ref", required=True)
    parser.add_argument("--sha", required=True)
    args = parser.parse_args(argv)
    repository = os.environ.get("GITHUB_REPOSITORY", "")
    result = decide(github_api, git, args.event, args.ref, repository, args.sha)
    for key in ("reuse", "run", "pull", "head"):
        if key in result:
            print(f"{key}={result[key]}")
    line = (
        f"Reusing Application validation run {result['run']} of pull request #{result['pull']} "
        f"(head {result['head']}, same tree as {args.sha})."
        if result["reuse"] == "true"
        else f"Full validation: {result['reason']}."
    )
    print(line, file=sys.stderr)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as stream:
            stream.write(line + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
