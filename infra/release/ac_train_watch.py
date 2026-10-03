#!/usr/bin/env python3
"""Read release state and spool alerts when staging falls behind green main."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

import ac_release
from ac_train_notify import DEFAULT_SPOOL, emit

LAG_SECONDS = 30 * 60
NO_RUN_SECONDS = 20 * 60
STATUS_COMMAND = ("ac-release", "status", "--json")


class WatchError(RuntimeError):
    """The read-only release status or GitHub response is unusable."""


def _parse_time(value: Any) -> dt.datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.UTC)
    return parsed.astimezone(dt.UTC)


def _run_completion(run: Mapping[str, Any]) -> dt.datetime | None:
    return _parse_time(run.get("completed_at") or run.get("updated_at"))


def _main_commit(github: Any) -> tuple[str, dt.datetime] | None:
    data = github.get_json(f"/repos/{ac_release.REPOSITORY}/commits/main")
    sha = data.get("sha")
    commit = data.get("commit") or {}
    committer = commit.get("committer") or {}
    timestamp = _parse_time(committer.get("date"))
    if not isinstance(sha, str) or not ac_release.SHA_RE.fullmatch(sha) or timestamp is None:
        return None
    return sha, timestamp


def _newest_core_success(github: Any) -> tuple[str, dt.datetime] | None:
    data = github.get_json(
        f"/repos/{ac_release.REPOSITORY}/actions/workflows/{ac_release.CORE_WORKFLOW}/runs",
        {"branch": "main", "event": "push", "per_page": "100"},
    )
    runs = data.get("workflow_runs", [])
    candidates: dict[str, tuple[int, int]] = {}
    for run in runs:
        sha = str(run.get("head_sha", ""))
        if not ac_release.SHA_RE.fullmatch(sha):
            continue
        order = (int(run.get("run_number") or 0), int(run.get("run_attempt") or 0))
        candidates[sha] = max(candidates.get(sha, (-1, -1)), order)
    ordered_shas = sorted(candidates, key=lambda sha: candidates[sha], reverse=True)
    for sha in ordered_shas:
        run = ac_release.find_push_run(github, ac_release.CORE_WORKFLOW, sha)
        if not run or not ac_release.validated(github, sha):
            continue
        completed = _run_completion(run)
        if completed is not None:
            return sha, completed
    return None


def _newest_validated_web(github: Any) -> tuple[str, dt.datetime, frozenset[str]] | None:
    """The newest validated web build, its clock, and the newer web builds above it.

    A newer build can already run on staging, for example when a later push
    cancelled its validation run; staging is then ahead of the target, not behind.
    """

    newer: list[str] = []
    for sha in ac_release.recent_web_shas(github):
        newer.append(sha)
        if not ac_release.validated(github, sha):
            continue
        build = ac_release.web_build_for(github, sha)
        if build is None:
            continue
        run = ac_release.find_push_run(github, ac_release.WEB_WORKFLOW, sha)
        if run is None:
            continue
        web_completed = _run_completion(run)
        application_run = ac_release.find_push_run(github, ac_release.CORE_WORKFLOW, sha)
        application_completed = _run_completion(application_run or {})
        if web_completed is not None and application_completed is not None:
            return sha, max(web_completed, application_completed), frozenset(newer[:-1])
    return None


def read_status(
    command: Sequence[str] = STATUS_COMMAND,
    *,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> dict[str, Any]:
    try:
        result = runner(
            list(command),
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
        status = json.loads(result.stdout)
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError, TypeError) as error:
        raise WatchError("could not read ac-release status JSON") from error
    if not isinstance(status, dict) or not isinstance(status.get("environments"), dict):
        raise WatchError("ac-release status has no environments object")
    if not isinstance(status["environments"].get("staging"), dict):
        raise WatchError("ac-release status has no staging environment")
    # T4 may add train metadata. It is optional and does not affect watch decisions.
    status.get("train")
    return status


def evaluate(
    status: Mapping[str, Any],
    github: Any,
    *,
    now: dt.datetime | None = None,
    notify: Callable[..., Path | None] = emit,
    spool: Path | str = DEFAULT_SPOOL,
) -> list[dict[str, Any]]:
    """Write every currently true staging or main-workflow alert."""

    current = now or dt.datetime.now(dt.UTC)
    if current.tzinfo is None:
        current = current.replace(tzinfo=dt.UTC)
    current = current.astimezone(dt.UTC)
    staging = status["environments"]["staging"]
    emitted: list[dict[str, Any]] = []

    def alert(key: str, text: str, **fields: Any) -> None:
        notify("alert", key, text, spool=spool, **fields)
        emitted.append({"key": key, "text": text, **fields})

    if staging.get("paused") is True:
        alert(
            "state:staging:paused",
            "staging release is paused",
            environment="staging",
            flag="paused",
        )
    failed = staging.get("failed")
    if isinstance(failed, Mapping):
        for component in ac_release.COMPONENTS:
            failed_sha = failed.get(component)
            if failed_sha:
                alert(
                    f"state:staging:{component}-failed",
                    f"staging {component} deploy has a failed flag",
                    environment="staging",
                    component=component,
                    sha=str(failed_sha),
                    flag=f"{component}-failed",
                )

    web = _newest_validated_web(github)
    for component, current_key, latest, ahead in (
        ("core", "core", _newest_core_success(github), frozenset[str]()),
        ("web", "web", web[:2] if web else None, web[2] if web else frozenset[str]()),
    ):
        if latest is None:
            continue
        target_sha, completed = latest
        staging_sha = staging.get(current_key)
        lag = (current - completed).total_seconds()
        if staging_sha != target_sha and staging_sha not in ahead and lag > LAG_SECONDS:
            alert(
                f"lag:staging:{component}:{target_sha}",
                f"staging {component} is behind green main {target_sha[:7]}",
                environment="staging",
                component=component,
                sha=target_sha,
                staging_sha=staging_sha,
                lag_seconds=int(lag),
            )

    head = _main_commit(github)
    if head is not None:
        head_sha, committed = head
        age = (current - committed).total_seconds()
        if (
            age > NO_RUN_SECONDS
            and ac_release.find_push_run(github, ac_release.CORE_WORKFLOW, head_sha) is None
        ):
            alert(
                f"norun:{head_sha}",
                f"main HEAD {head_sha[:7]} has no application workflow run after 20 minutes",
                sha=head_sha,
                age_seconds=int(age),
            )
    return emitted


def check(
    *,
    command: Sequence[str] = STATUS_COMMAND,
    token_file: Path | None = None,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    notify: Callable[..., Path | None] = emit,
    spool: Path | str = DEFAULT_SPOOL,
    now: dt.datetime | None = None,
) -> list[dict[str, Any]]:
    status = read_status(command, runner=runner)
    paths = ac_release.Paths()
    token_path = token_file or paths.token
    try:
        token = token_path.read_text(encoding="utf-8").strip()
    except OSError as error:
        raise WatchError("GitHub token file is unavailable") from error
    github = ac_release.GitHub(token)
    return evaluate(status, github, now=now, notify=notify, spool=spool)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ac-train-watch")
    parser.add_argument("--spool", type=Path, default=DEFAULT_SPOOL)
    args = parser.parse_args(argv)
    try:
        events = check(spool=args.spool)
    except (WatchError, ac_release.ReleaseError, OSError) as error:
        print(f"ac-train-watch: {error}", file=sys.stderr)
        return 1
    print(json.dumps({"alerts": events}, sort_keys=True))
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised through the CLI tests
    raise SystemExit(main())
