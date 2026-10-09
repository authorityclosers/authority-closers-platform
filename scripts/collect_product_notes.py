#!/usr/bin/env python3
"""Bake the newest 200 first-parent PR notes into a release, without blocking it."""

from __future__ import annotations

import argparse
import http.client
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.request
from collections.abc import Sequence
from dataclasses import asdict
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "packages/python"))
from ac_platform.product_updates.pr_note import UserNote, parse_user_note  # noqa: E402

PR_SUBJECT = re.compile(r"\(#([0-9]+)\)$")


def collect(release_sha: str, repository: str, token: str) -> dict[str, Any]:
    result: dict[str, Any] = {
        "version": 1,
        "release_sha": release_sha,
        "complete": False,
        "notes": [],
    }
    try:
        deadline = time.monotonic() + 120
        if not re.fullmatch(r"[0-9a-f]{40}", release_sha):
            raise ValueError("invalid release SHA")
        if not token or not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
            raise ValueError("GitHub context unavailable")
        git = shutil.which("git")
        if git is None:
            raise OSError("git unavailable")
        subjects = subprocess.run(  # noqa: S603 - fixed executable and argv, without a shell
            [git, "log", "--first-parent", "--format=%s", release_sha, "--"],
            capture_output=True,
            text=True,
            check=True,
            timeout=30,
        ).stdout.splitlines()
        prs = list(dict.fromkeys(int(m[1]) for s in subjects if (m := PR_SUBJECT.search(s))))[:200]
        notes = []
        for pr in prs:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("collection budget exhausted")
            request = urllib.request.Request(
                f"https://api.github.com/repos/{repository}/pulls/{pr}",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/vnd.github+json",
                    "X-GitHub-Api-Version": "2022-11-28",
                },
            )
            with urllib.request.urlopen(request, timeout=min(15, remaining)) as response:  # noqa: S310 - fixed HTTPS host
                payload = json.load(response)
            note = parse_user_note(payload.get("body") or "")
            if not isinstance(note, UserNote) or not payload["merged_at"]:
                continue
            notes.append(
                {
                    "key": f"pr-{pr}",
                    "pr": pr,
                    "merged_at": payload["merged_at"],
                    **asdict(note),
                    "approved": any(
                        label["name"] == "note-approved" for label in payload["labels"]
                    ),
                }
            )
        result.update(complete=True, notes=notes)
    except (
        OSError,
        ValueError,
        KeyError,
        TypeError,
        AttributeError,
        http.client.HTTPException,
        subprocess.SubprocessError,
    ):
        # Do not print provider payloads, exception messages, or authentication data.
        print(
            "::warning::Product note collection failed; this release carries no new notes.",
            file=sys.stderr,
        )
    return result


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--release-sha", default=os.getenv("GITHUB_SHA", ""))
    parser.add_argument("--repository", default=os.getenv("GITHUB_REPOSITORY", ""))
    args = parser.parse_args(argv)
    result = collect(args.release_sha, args.repository, os.getenv("GH_TOKEN", ""))
    args.output.write_text(json.dumps(result, ensure_ascii=False) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
