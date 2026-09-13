#!/usr/bin/env python3
"""Install the dedicated hosted Sales Xray database credential file.

The deployment wrapper supplies ``AC_DATABASE_URL`` to this process through
the existing Infisical child. This command never accepts a URL or destination
on argv, prints the URL, or emits a digest of its contents. The only managed
destinations are the fixed staging and production paths below.
"""

from __future__ import annotations

import argparse
import os
import stat
import sys
import tempfile
from contextlib import suppress
from pathlib import Path
from urllib.parse import parse_qsl, unquote_to_bytes, urlsplit

ENVIRONMENTS = frozenset(("staging", "production"))
SECRETS_ROOT = Path("/etc/authority-closers/secrets/sales-xray")
DATABASE_FILE_NAME = "database-url"
EXPECTED_DATABASE_HOST = "postgres"
EXPECTED_DATABASE_NAME = "ac_platform"
EXPECTED_DATABASE_USER = "ac_runtime"
ROOT_UID = 0
ROOT_GID = 0
WORKER_UID = 10001
DIRECTORY_MODE = 0o750
DATABASE_FILE_MODE = 0o400
MAX_DATABASE_URL_BYTES = 4096


class ProvisioningError(Exception):
    """A stable, content-free provisioning refusal."""


def _refuse() -> ProvisioningError:
    return ProvisioningError("database credential provisioning refused")


def _safe_absolute(path: Path) -> None:
    if not path.is_absolute() or ".." in path.parts:
        raise _refuse()


def _check_existing_ancestors(path: Path) -> None:
    """Reject links in an already-existing fixed path before any mkdir."""

    _safe_absolute(path)
    for ancestor in reversed(path.parents):
        try:
            info = ancestor.lstat()
        except FileNotFoundError:
            continue
        if (
            stat.S_ISLNK(info.st_mode)
            or not stat.S_ISDIR(info.st_mode)
            or info.st_uid != ROOT_UID
            or stat.S_IMODE(info.st_mode) & 0o022
        ):
            raise _refuse()


def _check_directory(path: Path) -> None:
    try:
        info = path.lstat()
    except OSError:
        raise _refuse() from None
    if (
        stat.S_ISLNK(info.st_mode)
        or not stat.S_ISDIR(info.st_mode)
        or info.st_uid != ROOT_UID
        or stat.S_IMODE(info.st_mode) & 0o022
    ):
        raise _refuse()


def _ensure_directory(path: Path) -> None:
    """Create one managed directory, then validate its trusted metadata."""

    _safe_absolute(path)
    missing: list[Path] = []
    cursor = path
    while True:
        try:
            info = cursor.lstat()
        except FileNotFoundError:
            missing.append(cursor)
            if cursor == cursor.parent:
                raise _refuse() from None
            cursor = cursor.parent
            continue
        except OSError:
            raise _refuse() from None
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
            raise _refuse()
        break
    _check_existing_ancestors(cursor)
    _check_directory(cursor)
    for candidate in reversed(missing):
        try:
            candidate.mkdir(mode=DIRECTORY_MODE)
        except FileExistsError:
            pass
        except OSError:
            raise _refuse() from None
        _check_directory(candidate)
    _check_directory(path)


def _validate_database_url(value: str) -> None:
    """Validate the exact private Compose database profile without logging it."""

    if not isinstance(value, str) or not value or value != value.strip():
        raise _refuse()
    try:
        if len(value.encode("utf-8", "strict")) > MAX_DATABASE_URL_BYTES:
            raise _refuse()
    except UnicodeError:
        raise _refuse() from None
    if any(ord(character) < 0x20 or ord(character) == 0x7F for character in value):
        raise _refuse()
    try:
        parsed = urlsplit(value)
        port = parsed.port
        username = parsed.username
        password = parsed.password
        hostname = parsed.hostname
        query = parse_qsl(parsed.query, keep_blank_values=True, strict_parsing=True)
    except (UnicodeError, ValueError):
        raise _refuse() from None

    if password is None:
        decoded_password = ""
    else:
        if any(
            character == "%"
            and (
                index + 2 >= len(password)
                or any(
                    digit not in "0123456789abcdefABCDEF"
                    for digit in password[index + 1 : index + 3]
                )
            )
            for index, character in enumerate(password)
        ):
            raise _refuse()
        try:
            decoded_password = unquote_to_bytes(password).decode("utf-8", "strict")
        except UnicodeError:
            raise _refuse() from None
    if (
        parsed.scheme != "postgresql+psycopg"
        or parsed.fragment
        or parsed.path != "/" + EXPECTED_DATABASE_NAME
        or parsed.username != EXPECTED_DATABASE_USER
        or username != EXPECTED_DATABASE_USER
        or password is None
        or len(decoded_password) < 16
        or decoded_password.startswith("local-")
        or any(ord(character) < 0x20 or ord(character) == 0x7F for character in decoded_password)
        or hostname != EXPECTED_DATABASE_HOST
        or port not in (None, 5432)
        or len(query) > 1
        or any(key != "sslmode" or not value for key, value in query)
    ):
        raise _refuse()


def _target_path(environment: str, root: Path) -> Path:
    if environment not in ENVIRONMENTS:
        raise _refuse()
    _safe_absolute(root)
    target = root / environment / DATABASE_FILE_NAME
    _safe_absolute(target)
    return target


def _read_existing(path: Path, expected: bytes) -> bool:
    """Return true only for an exact, trusted existing file."""

    try:
        # O_NONBLOCK prevents a hostile FIFO from blocking before fstat can
        # reject it. It is harmless for the regular file accepted below.
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
        descriptor = os.open(path, flags)
    except FileNotFoundError:
        return False
    except OSError:
        raise _refuse() from None
    try:
        with os.fdopen(descriptor, "rb") as stream:
            info = os.fstat(stream.fileno())
            if (
                not stat.S_ISREG(info.st_mode)
                or info.st_nlink != 1
                or info.st_uid != WORKER_UID
                or info.st_gid != ROOT_GID
                or stat.S_IMODE(info.st_mode) != DATABASE_FILE_MODE
                or info.st_size <= 0
                or info.st_size > MAX_DATABASE_URL_BYTES
            ):
                raise _refuse()
            actual = stream.read(MAX_DATABASE_URL_BYTES + 1)
    except ProvisioningError:
        raise
    except OSError:
        raise _refuse() from None
    if actual != expected:
        raise _refuse()
    return True


def _fsync_directory(path: Path) -> None:
    if os.name != "posix":
        return
    try:
        flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
        descriptor = os.open(path, flags)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    except OSError:
        raise _refuse() from None


def _create_file(path: Path, expected: bytes) -> None:
    """Create the final name without replacing a concurrently-created file."""

    temporary: Path | None = None
    descriptor: int | None = None
    try:
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=".database-url.", suffix=".tmp", dir=path.parent
        )
        temporary = Path(temporary_name)
        os.fchmod(descriptor, 0)
        offset = 0
        while offset < len(expected):
            offset += os.write(descriptor, expected[offset:])
        os.fsync(descriptor)
        os.fchown(descriptor, WORKER_UID, ROOT_GID)
        os.fchmod(descriptor, DATABASE_FILE_MODE)
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = None

        # link(2) is create-only: it cannot replace an existing destination.
        os.link(temporary, path, follow_symlinks=False)
        temporary.unlink()
        temporary = None
        _fsync_directory(path.parent)
    except FileExistsError:
        raise _refuse() from None
    except OSError:
        raise _refuse() from None
    finally:
        if descriptor is not None:
            with suppress(OSError):
                os.close(descriptor)
        if temporary is not None:
            with suppress(OSError):
                temporary.unlink()


def provision(
    environment: str,
    *,
    secrets_root: Path = SECRETS_ROOT,
    require_root: bool = True,
) -> str:
    """Provision the fixed environment file and return a safe status word.

    ``secrets_root`` and ``require_root`` exist only for isolated tests; the
    CLI always uses ``SECRETS_ROOT`` and requires UID 0.
    """

    if require_root and (os.name != "posix" or os.geteuid() != ROOT_UID):
        raise _refuse()
    try:
        raw_url = os.environ["AC_DATABASE_URL"]
    except KeyError:
        raise _refuse() from None
    _validate_database_url(raw_url)
    expected = raw_url.encode("utf-8")
    target = _target_path(environment, secrets_root)
    _ensure_directory(target.parent.parent)
    _ensure_directory(target.parent)
    if _read_existing(target, expected):
        return "already-present"
    _create_file(target, expected)
    if not _read_existing(target, expected):
        raise _refuse()
    return "installed"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("environment", choices=sorted(ENVIRONMENTS))
    args = parser.parse_args(argv)
    try:
        status = provision(args.environment)
    except (ProvisioningError, OSError, UnicodeError, ValueError):
        print("FAIL Sales Xray database credential provisioning refused.", file=sys.stderr)
        return 2
    print(f"PASS Sales Xray database credential {status}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
