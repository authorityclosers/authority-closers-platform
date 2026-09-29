#!/usr/bin/env python3
"""Print merged pull-request subjects between two revisions."""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

PULL_REQUEST_SUBJECT_RE = re.compile(r"\(#[0-9]+\)$")


def release_notes(git_dir: str | Path, from_ref: str, to_sha: str) -> list[str]:
    """Return first-parent subjects ending in a pull-request number, in git order."""

    if not from_ref or not to_sha or from_ref.startswith("-") or to_sha.startswith("-"):
        raise ValueError("from and to revisions are required")
    git_executable = shutil.which("git")
    if git_executable is None:
        raise FileNotFoundError("git executable is not available")
    result = subprocess.run(  # noqa: S603 - fixed executable and argv list; no shell is used.
        [
            git_executable,
            f"--git-dir={git_dir}",
            "log",
            "--first-parent",
            "--format=%s",
            f"{from_ref}..{to_sha}",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return [
        subject for subject in result.stdout.splitlines() if PULL_REQUEST_SUBJECT_RE.search(subject)
    ]


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--git-dir", required=True, type=Path)
    parser.add_argument("--from", dest="from_ref", required=True)
    parser.add_argument("--to", dest="to_sha", required=True)
    args = parser.parse_args(argv)
    try:
        subjects = release_notes(args.git_dir, args.from_ref, args.to_sha)
    except (OSError, subprocess.CalledProcessError, ValueError) as error:
        print(f"release notes failed: {error}", file=sys.stderr)
        return 1
    for subject in subjects:
        print(subject)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
