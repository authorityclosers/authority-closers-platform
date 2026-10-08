#!/usr/bin/env python3
"""Read a complete repository artifact inventory, retrying without partial output."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from typing import Any

ATTEMPTS = 3
TIMEOUT_SECONDS = 120
PAGE_SIZE = 100


def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def validate_inventory(raw: str) -> tuple[list[dict[str, Any]], int]:
    try:
        pages = json.loads(raw, object_pairs_hook=unique_object)
    except ValueError:
        raise ValueError("invalid JSON") from None
    if not isinstance(pages, list) or not pages:
        raise ValueError("missing inventory pages")
    artifacts: list[dict[str, Any]] = []
    total = None
    ids: set[int] = set()
    for page in pages:
        if (
            not isinstance(page, dict)
            or type(page.get("total_count")) is not int
            or page["total_count"] < 0
            or not isinstance(page.get("artifacts"), list)
        ):
            raise ValueError("invalid page schema")
        if total is None:
            total = page["total_count"]
        if page["total_count"] != total:
            raise ValueError("inventory count changed between pages")
        expected_size = min(PAGE_SIZE, max(0, total - len(artifacts)))
        if len(page["artifacts"]) != expected_size:
            raise ValueError("incomplete inventory page")
        for artifact in page["artifacts"]:
            if (
                not isinstance(artifact, dict)
                or type(artifact.get("id")) is not int
                or artifact["id"] <= 0
                or artifact["id"] in ids
                or type(artifact.get("size_in_bytes")) is not int
                or artifact["size_in_bytes"] < 0
                or not isinstance(artifact.get("name"), str)
                or not artifact["name"]
                or type(artifact.get("expired")) is not bool
            ):
                raise ValueError("invalid artifact schema or duplicate identity")
            ids.add(artifact["id"])
            artifacts.append(artifact)
    if len(artifacts) != total or len(pages) != max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE):
        raise ValueError("incomplete inventory")
    return artifacts, len(pages)


def read_inventory(executable: str, repository: str, operation: str) -> list[dict[str, Any]]:
    command = [
        executable,
        "api",
        "--paginate",
        "--slurp",
        "--header",
        "Accept: application/vnd.github+json",
        "--header",
        "X-GitHub-Api-Version: 2026-03-10",
        f"/repos/{repository}/actions/artifacts?per_page={PAGE_SIZE}",
    ]
    for attempt in range(1, ATTEMPTS + 1):
        prefix = f"Artifact inventory operation={operation} attempt={attempt}/{ATTEMPTS}"
        try:
            # Each invocation starts at page one. Capture/suppress CLI diagnostics
            # and publish no bytes until both transport and completeness pass.
            result = subprocess.run(  # noqa: S603 - resolved gh executable, no shell
                command, capture_output=True, text=True, check=False, timeout=TIMEOUT_SECONDS
            )
            if result.returncode != 0:
                reason = f"gh exit={result.returncode}"
            else:
                artifacts, pages = validate_inventory(result.stdout)
                print(
                    f"{prefix} complete pages={pages} artifacts={len(artifacts)} "
                    f"bytes={sum(a['size_in_bytes'] for a in artifacts)}",
                    file=sys.stderr,
                )
                return artifacts
        except subprocess.TimeoutExpired:
            reason = f"timeout={TIMEOUT_SECONDS}s"
        except UnicodeError:
            reason = "invalid response encoding"
        except ValueError as error:
            reason = str(error)
        print(f"{prefix} rejected: {reason}; discarded attempt", file=sys.stderr)
        if attempt < ATTEMPTS:
            time.sleep(2 * attempt)
    raise ValueError(f"Artifact inventory operation={operation} exhausted {ATTEMPTS} attempts")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--operation", choices=("admission", "after-upload", "final"), required=True
    )
    args = parser.parse_args()
    repository = os.environ.get("GITHUB_REPOSITORY", "")
    executable = shutil.which("gh")
    if re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository) is None or not executable:
        print("Artifact inventory requires a repository identity and GitHub CLI", file=sys.stderr)
        return 1
    try:
        artifacts = read_inventory(executable, repository, args.operation)
    except (ValueError, OSError):
        print(f"Artifact inventory operation={args.operation} could not be proven", file=sys.stderr)
        return 1
    print(json.dumps(artifacts))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
