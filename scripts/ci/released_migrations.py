#!/usr/bin/env python3
"""Released migrations are history: fail when a migration that is already on main changed.

Root cause 3 of the v0.86 migration failures (owner, 24 Oct 2026: fix the root cause so it does
not happen again). A wording sweep (d85f7fe1) edited released migration 0096's docstring; the
release's migration-safety gate refuses any rewrite of history, but it runs only on the release
PR, hours after the edit. This fast check runs in wb-ci whenever db/migrations changes.

    released_migrations.py [--base origin/main] [--path db/migrations/versions]

A migration file present on <base> must be byte-identical (same content and mode) in HEAD.
Added files are new revisions and pass. A file on <base> that HEAD's history never had is a
release not merged back yet: a note, not a failure. Exit 0 when no released migration changed,
1 with the list when one did, 2 when git cannot compare (fetch <base> first).
"""

from __future__ import annotations

import argparse
import subprocess
import sys

MESSAGE = "released migrations are history; add a new revision"


def git(*arguments: str) -> str:
    return subprocess.run(  # noqa: S603 - fixed git argv, no shell
        ["git", *arguments],  # noqa: S607
        check=True,
        capture_output=True,
        text=True,
    ).stdout


def compare(base: str, path: str) -> tuple[int, list[str], list[str]]:
    """(released count, rewritten "<status> <file>" entries, files not merged back yet)."""
    released = [
        name
        for name in git("ls-tree", "-r", "--name-only", base, "--", path).splitlines()
        if name.endswith(".py")
    ]
    rewritten: list[str] = []
    lagging: list[str] = []
    changes = git("diff", "--name-status", "--no-renames", base, "HEAD", "--", path)
    for line in changes.splitlines():
        status, _, name = line.partition("\t")
        if status == "A" or not name.endswith(".py"):
            continue
        if status == "D" and not git("log", "-1", "--format=%H", "HEAD", "--", name).strip():
            lagging.append(name)
        else:
            rewritten.append(f"{status} {name}")
    return len(released), rewritten, lagging


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    parser.add_argument("--base", default="origin/main")
    parser.add_argument("--path", default="db/migrations/versions")
    args = parser.parse_args(argv)
    try:
        git("rev-parse", "--verify", "--end-of-options", f"{args.base}^{{commit}}")
        released, rewritten, lagging = compare(args.base, args.path)
    except (OSError, subprocess.CalledProcessError):
        print(f"released-migrations: FAIL (cannot compare with {args.base}; fetch it first)")
        return 2
    for name in lagging:
        print(f"released-migrations: note: {name} is on {args.base} but not merged here yet")
    if rewritten:
        print(f"::error title=released migration changed::{MESSAGE}: {', '.join(rewritten)}")
        print(f"released-migrations: FAIL ({MESSAGE}): {', '.join(rewritten)}")
        return 1
    print(f"released-migrations: PASS ({released} released migrations unchanged on {args.base})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
