#!/usr/bin/env python3
"""Reclaim only proved superseded advisory/web artifacts for pool admission."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime
from typing import Any

SHA = r"[0-9a-f]{40}"
RECLAIMABLE = re.compile(rf"^(sales-xray-visual-({SHA})-[1-9][0-9]*|ac-sales-xray-web-({SHA}))$")
REPLACEMENTS = ("ac-application", "ac-sales-xray-web")


class GitHub:
    def __init__(self, repository: str) -> None:
        if re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository) is None:
            raise ValueError("Repository identity is malformed")
        self.root = f"/repos/{repository}"
        executable = shutil.which("gh")
        if executable is None:
            raise ValueError("GitHub CLI is unavailable")
        self.executable = executable

    def api(self, path: str, *, paginate: bool = False, delete: bool = False) -> Any:
        arguments = [
            self.executable,
            "api",
            "--header",
            "Accept: application/vnd.github+json",
            "--header",
            "X-GitHub-Api-Version: 2026-03-10",
        ]
        if paginate:
            arguments.extend(["--paginate", "--slurp"])
        if delete:
            arguments.extend(["--method", "DELETE"])
        arguments.append(self.root + path)
        result = subprocess.run(  # noqa: S603 - fixed gh executable, no shell
            arguments, capture_output=True, text=True, check=False, timeout=120
        )
        if result.returncode != 0:
            raise ValueError(f"GitHub metadata request failed: {path}")
        return None if delete else json.loads(result.stdout)

    def artifacts(self) -> list[dict[str, Any]]:
        pages = self.api("/actions/artifacts?per_page=100", paginate=True)
        if (
            not isinstance(pages, list)
            or not pages
            or any(
                not isinstance(page, dict) or not isinstance(page.get("artifacts"), list)
                for page in pages
            )
        ):
            raise ValueError("Repository artifact inventory could not be proven")
        artifacts = [artifact for page in pages for artifact in page["artifacts"]]
        ids = set()
        for artifact in artifacts:
            if (
                not isinstance(artifact, dict)
                or type(artifact.get("id")) is not int
                or artifact["id"] <= 0
                or artifact["id"] in ids
                or type(artifact.get("size_in_bytes")) is not int
                or artifact["size_in_bytes"] < 0
                or not isinstance(artifact.get("name"), str)
            ):
                raise ValueError("Repository artifact usage could not be proven")
            ids.add(artifact["id"])
        return artifacts

    def pulls(self, state: str) -> list[dict[str, Any]]:
        pages = self.api(f"/pulls?state={state}&per_page=100", paginate=True)
        if (
            not isinstance(pages, list)
            or not pages
            or any(not isinstance(page, list) for page in pages)
        ):
            raise ValueError("Pull request protection could not be proven")
        pulls = [pull for page in pages for pull in page]
        for pull in pulls:
            if (
                not isinstance(pull, dict)
                or pull.get("state") not in ("open", "closed")
                or not isinstance(pull.get("head"), dict)
                or re.fullmatch(SHA, pull["head"].get("sha", "")) is None
                or not isinstance(pull["head"].get("ref"), str)
            ):
                raise ValueError("Pull request protection could not be proven")
        return pulls


def source(artifact: dict[str, Any]) -> str | None:
    match = RECLAIMABLE.fullmatch(artifact["name"])
    return (match[2] or match[3]) if match else None


def branch_matches(artifact: dict[str, Any], pull: dict[str, Any]) -> bool:
    run = artifact.get("workflow_run") or {}
    head = pull["head"]
    repository_id = (head.get("repo") or {}).get("id")
    return (
        repository_id is not None
        and repository_id == run.get("head_repository_id")
        and head.get("ref") is not None
        and head["ref"] == run.get("head_branch")
    )


def protected(artifact: dict[str, Any], pulls: list[dict[str, Any]], shas: set[str]) -> bool:
    artifact_sha = source(artifact)
    run_sha = (artifact.get("workflow_run") or {}).get("head_sha")
    return (
        artifact_sha in shas
        or run_sha in shas
        or any(
            pull["state"] == "open"
            and (
                branch_matches(artifact, pull) or pull["head"].get("sha") in (artifact_sha, run_sha)
            )
            for pull in pulls
        )
    )


def created_at(artifact: dict[str, Any]) -> datetime:
    return datetime.fromisoformat(artifact["created_at"].replace("Z", "+00:00"))


def superseded(artifact: dict[str, Any], pulls: list[dict[str, Any]]) -> bool:
    artifact_sha = source(artifact)
    for pull in pulls:
        if pull["state"] != "closed" or not pull.get("closed_at"):
            continue
        if artifact_sha == pull["head"].get("sha") or (
            pull.get("merged_at") and artifact_sha == pull.get("merge_commit_sha")
        ):
            return True
        if branch_matches(artifact, pull) and created_at(artifact) <= datetime.fromisoformat(
            pull["closed_at"].replace("Z", "+00:00")
        ):
            return True
    return False


def projection(artifacts: list[dict[str, Any]], candidate: int, replacement: str | None) -> int:
    # Keep the existing credit for exact bundles reclaimed only after verified
    # replacement upload. This helper never deletes an application bundle.
    pattern = re.compile(rf"^{replacement}-{SHA}$") if replacement else None
    return candidate + sum(
        int(artifact["size_in_bytes"])
        for artifact in artifacts
        if pattern is None or not pattern.fullmatch(artifact["name"])
    )


def reclaim(github: GitHub, candidate: int, ceiling: int, replacement: str | None) -> int:
    artifacts = github.artifacts()
    projected = projection(artifacts, candidate, replacement)
    if projected <= ceiling:
        return projected
    pulls = github.pulls("all")
    shas = {
        os.environ.get(variable, "") for variable in ("GITHUB_SHA", "FROZEN_SHA", "RELEASE_SHA")
    }
    # Keep the newest main evidence/bundle in each reclaimable family, even
    # when admission runs against an older manually frozen source.
    main_artifacts = [
        artifact
        for artifact in artifacts
        if source(artifact) and (artifact.get("workflow_run") or {}).get("head_branch") == "main"
    ]
    for prefix in ("sales-xray-visual-", "ac-sales-xray-web-"):
        family = [artifact for artifact in main_artifacts if artifact["name"].startswith(prefix)]
        if family:
            shas.add(source(max(family, key=lambda item: (created_at(item), item["id"]))) or "")
    eligible = sorted(
        (
            artifact
            for artifact in artifacts
            if source(artifact)
            and not (replacement and artifact["name"].startswith(replacement + "-"))
            and not protected(artifact, pulls, shas)
            and superseded(artifact, pulls)
        ),
        key=lambda artifact: (created_at(artifact), artifact["id"]),
    )
    for artifact in eligible:
        # Recheck protection immediately before deletion: a closed branch may
        # have been reopened, or a new PR may now use that branch/source.
        if protected(artifact, github.pulls("open"), shas):
            continue
        github.api(f"/actions/artifacts/{artifact['id']}", delete=True)
        artifacts = github.artifacts()
        if any(item["id"] == artifact["id"] for item in artifacts):
            raise ValueError("Artifact reclamation could not be verified")
        projected = projection(artifacts, candidate, replacement)
        print(
            f"Reclaimed superseded artifact {artifact['id']} ({artifact['name']}); "
            f"projected repository pool is {projected} bytes.",
            file=sys.stderr,
        )
        if projected <= ceiling:
            break
    return projected


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate-bytes", type=int, required=True)
    parser.add_argument("--pool-bytes", type=int, required=True)
    parser.add_argument("--replacement-prefix", choices=REPLACEMENTS)
    arguments = parser.parse_args()
    try:
        if arguments.candidate_bytes < 0 or arguments.pool_bytes <= 0:
            raise ValueError("Artifact admission sizes are malformed")
        print(
            reclaim(
                GitHub(os.environ["GITHUB_REPOSITORY"]),
                arguments.candidate_bytes,
                arguments.pool_bytes,
                arguments.replacement_prefix,
            )
        )
    except (ValueError, KeyError, TypeError, subprocess.TimeoutExpired) as error:
        print(f"Safe artifact reclamation refused: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
