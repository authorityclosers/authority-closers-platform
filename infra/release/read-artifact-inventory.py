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
from collections.abc import Callable
from datetime import UTC, datetime
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


class SnapshotChanged(ValueError):
    """An artifact in the fixed snapshot changed identity or size."""


class InventorySnapshot:
    """Keep the original boundary and observed identities across retries."""

    def __init__(self, started_at: datetime | None = None) -> None:
        self.started_at = started_at or datetime.now(UTC)
        self.expected_count: int | None = None
        self.known: dict[int, dict[str, Any]] = {}


def artifact_created_at(artifact: dict[str, Any]) -> datetime:
    try:
        created = datetime.fromisoformat(artifact["created_at"].replace("Z", "+00:00"))
        if created.tzinfo is None:
            raise ValueError
        return created
    except (KeyError, AttributeError, TypeError, ValueError):
        raise ValueError("invalid artifact schema: created_at") from None


def validate_inventory(
    raw: str, *, snapshot: InventorySnapshot | None = None
) -> tuple[list[dict[str, Any]], int]:
    snapshot = snapshot or InventorySnapshot()
    try:
        pages = json.loads(raw, object_pairs_hook=unique_object)
    except ValueError:
        raise ValueError("invalid JSON") from None
    if not isinstance(pages, list) or not pages:
        raise ValueError("missing inventory pages")
    artifacts: dict[int, dict[str, Any]] = {}
    older: dict[int, dict[str, Any]] = {}
    for index, page in enumerate(pages):
        if (
            not isinstance(page, dict)
            or type(page.get("total_count")) is not int
            or page["total_count"] < 0
            or not isinstance(page.get("artifacts"), list)
        ):
            raise ValueError("invalid page schema")
        expected_size = min(PAGE_SIZE, max(0, page["total_count"] - index * PAGE_SIZE))
        if len(page["artifacts"]) != expected_size:
            raise ValueError("incomplete inventory page")
        if not expected_size and (index or len(pages) != 1):
            raise ValueError("unexpected empty inventory page")
        recent: set[int] = set()
        for artifact in page["artifacts"]:
            if (
                not isinstance(artifact, dict)
                or type(artifact.get("id")) is not int
                or artifact["id"] <= 0
                or type(artifact.get("size_in_bytes")) is not int
                or artifact["size_in_bytes"] < 0
                or not isinstance(artifact.get("name"), str)
                or not artifact["name"]
                or type(artifact.get("expired")) is not bool
            ):
                raise ValueError("invalid artifact schema")
            identity = artifact["id"]
            in_snapshot = artifact_created_at(artifact) <= snapshot.started_at
            previous = snapshot.known.get(identity) or artifacts.get(identity)
            if previous and (in_snapshot or identity in snapshot.known) and any(
                previous[key] != artifact[key] for key in ("size_in_bytes", "name", "created_at")
            ):
                raise SnapshotChanged("artifact identity or size changed during inventory")
            artifacts[identity] = (
                previous
                if previous and previous["size_in_bytes"] > artifact["size_in_bytes"]
                else artifact
            )
            if in_snapshot:
                older[identity] = artifact
                snapshot.known[identity] = artifact
            else:
                recent.add(identity)
        if index == 0:
            # GitHub lists newest artifacts first. If the boundary is hidden
            # behind a whole page of concurrent uploads, do not guess its count.
            if len(recent) == PAGE_SIZE and page["total_count"] > PAGE_SIZE:
                raise ValueError("inventory snapshot boundary is not visible")
            expected = page["total_count"] - len(recent)
            if snapshot.expected_count is None:
                snapshot.expected_count = expected
            elif expected != snapshot.expected_count:
                raise ValueError("older artifact count changed during inventory")
    if len(older) != snapshot.expected_count or not snapshot.known.keys() <= older.keys():
        raise ValueError("incomplete inventory")
    # New uploads are outside the completeness proof, but count any observed
    # bytes conservatively for the ceiling. Repeated IDs are charged only once.
    return list(artifacts.values()), len(pages)


def read_inventory(
    executable: str,
    repository: str,
    operation: str,
    *,
    fetch: Callable[[], str] | None = None,
) -> list[dict[str, Any]]:
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
    snapshot = InventorySnapshot()
    for attempt in range(1, ATTEMPTS + 1):
        prefix = f"Artifact inventory operation={operation} attempt={attempt}/{ATTEMPTS}"
        try:
            # Each invocation starts at page one. Capture/suppress CLI diagnostics
            # and publish no bytes until both transport and completeness pass.
            if fetch is not None:
                raw = fetch()
            else:
                result = subprocess.run(  # noqa: S603 - resolved gh executable, no shell
                    command, capture_output=True, text=True, check=False, timeout=TIMEOUT_SECONDS
                )
                if result.returncode != 0:
                    raise ValueError(f"gh exit={result.returncode}")
                raw = result.stdout
            artifacts, pages = validate_inventory(raw, snapshot=snapshot)
            print(
                f"{prefix} complete pages={pages} artifacts={len(artifacts)} "
                f"bytes={sum(a['size_in_bytes'] for a in artifacts)}",
                file=sys.stderr,
            )
            return artifacts
        except SnapshotChanged:
            raise
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
