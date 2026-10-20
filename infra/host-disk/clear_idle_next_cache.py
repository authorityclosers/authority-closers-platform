#!/usr/bin/env python3
"""Dry-run by default: clear only .next/cache in idle, retired lane checkouts."""

from __future__ import annotations

import argparse
import json
import os
import shutil
from contextlib import suppress
from pathlib import Path

LANES = Path("/home/acdev/src/lanes")


def process_references() -> set[Path]:
    references = set()
    for process in Path("/proc").glob("[0-9]*"):
        try:
            references.add((process / "cwd").resolve(strict=True))
            for fd in (process / "fd").iterdir():
                with suppress(FileNotFoundError):
                    references.add(fd.resolve(strict=True))
        except (FileNotFoundError, ProcessLookupError):
            continue
    return references


def clear(cache: Path, references: set[Path], *, apply: bool) -> dict:
    if not cache.exists():
        return {"path": str(cache), "status": "absent"}
    # No symlink at any ancestor may redirect a retired lane into live dev.
    if cache.resolve() != cache or cache.name != "cache" or cache.parent.name != ".next":
        raise ValueError("cache path is not a direct .next/cache directory")
    app = cache.parent.parent
    if any(reference == app or app in reference.parents for reference in references):
        return {"path": str(cache), "status": "in_use"}
    entries = list(cache.rglob("*"))
    if any(entry.is_symlink() for entry in entries):
        raise ValueError("cache contains a symlink; refused")
    allocated = sum(entry.stat().st_blocks * 512 for entry in entries if entry.is_file())
    result = {"path": str(cache), "status": "cleared" if apply else "eligible", "bytes": allocated}
    if apply:
        # rmtree refuses a top-level symlink and does not follow child symlinks.
        shutil.rmtree(cache)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if os.geteuid() != 0:
        parser.error("root is required to inspect all process references")
    references = process_references()
    results = [
        clear(cache, references, apply=args.apply)
        for cache in sorted(LANES.glob("*/authority-closers-platform/apps/*/.next/cache"))
    ]
    print(json.dumps({"apply": args.apply, "caches": results}, indent=2))


if __name__ == "__main__":
    main()
