#!/usr/bin/env python3
"""Prepare the restore drill's one private host staging directory safely."""

from __future__ import annotations

import contextlib
import os
import stat
import sys
from pathlib import Path

TARGET_PARTS = ("var", "lib", "authority-closers")
TARGET_LEAF = "restore-drill-inputs"


class PreparationError(RuntimeError):
    """The exact root-owned directory contract could not be established."""


def _directory_flags() -> int:
    return (
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )


def _require_safe_directory(fd: int, *, expected_uid: int, expected_gid: int) -> None:
    metadata = os.fstat(fd)
    mode = stat.S_IMODE(metadata.st_mode)
    if (
        not stat.S_ISDIR(metadata.st_mode)
        or metadata.st_uid != expected_uid
        or metadata.st_gid != expected_gid
        or mode & 0o022
    ):
        raise PreparationError("a restore drill input root ancestor is unsafe")


def prepare_under(
    root: Path,
    *,
    expected_uid: int = 0,
    expected_gid: int = 0,
) -> Path:
    """Create the exact leaf through no-follow directory descriptors."""

    if not root.is_absolute():
        raise PreparationError("the preparation root must be absolute")
    flags = _directory_flags()
    descriptors: list[int] = []
    try:
        current = os.open(root, flags)
        descriptors.append(current)
        _require_safe_directory(current, expected_uid=expected_uid, expected_gid=expected_gid)
        for component in TARGET_PARTS:
            current = os.open(component, flags, dir_fd=current)
            descriptors.append(current)
            _require_safe_directory(current, expected_uid=expected_uid, expected_gid=expected_gid)

        with contextlib.suppress(FileExistsError):
            os.mkdir(TARGET_LEAF, mode=0o700, dir_fd=current)
        leaf = os.open(TARGET_LEAF, flags, dir_fd=current)
        descriptors.append(leaf)
        metadata = os.fstat(leaf)
        if (
            not stat.S_ISDIR(metadata.st_mode)
            or metadata.st_uid != expected_uid
            or metadata.st_gid != expected_gid
            or stat.S_IMODE(metadata.st_mode) != 0o700
        ):
            raise PreparationError("the restore drill input root is unsafe")
        return root.joinpath(*TARGET_PARTS, TARGET_LEAF)
    except PreparationError:
        raise
    except OSError as error:
        raise PreparationError("the restore drill input root could not be prepared") from error
    finally:
        for descriptor in reversed(descriptors):
            os.close(descriptor)


def main() -> int:
    if os.name != "posix" or os.geteuid() != 0:
        print("restore drill input root preparation requires root on POSIX", file=sys.stderr)
        return 1
    try:
        prepare_under(Path("/"))
    except PreparationError as error:
        print(f"restore drill input root preparation failed closed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
