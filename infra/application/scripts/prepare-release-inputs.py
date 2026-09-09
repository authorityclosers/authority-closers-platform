#!/usr/bin/env python3
"""Stage and validate immutable application release inputs without shell evaluation."""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import stat
import sys
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path

BUNDLE_FILES = frozenset(
    {
        "SHA256SUMS",
        "application-images.tar.gz",
        "release-images.env",
    }
)
CHECKSUM_FILES = frozenset({"application-images.tar.gz", "release-images.env"})
MANIFEST_KEYS = (
    "AC_ADMIN_IMAGE",
    "AC_ADMIN_REGISTRY_DIGEST",
    "AC_ADMIN_TRANSPORT_DIGEST",
    "AC_API_IMAGE",
    "AC_API_REGISTRY_DIGEST",
    "AC_API_TRANSPORT_DIGEST",
    "AC_COACH_IMAGE",
    "AC_COACH_REGISTRY_DIGEST",
    "AC_COACH_TRANSPORT_DIGEST",
    "AC_LEARNER_IMAGE",
    "AC_LEARNER_REGISTRY_DIGEST",
    "AC_LEARNER_TRANSPORT_DIGEST",
    "AC_MIGRATION_HEAD",
    "AC_RELEASE_ID",
)
_MANIFEST_PATTERNS = {
    "AC_ADMIN_IMAGE": re.compile(r"sha256:[0-9a-f]{64}"),
    "AC_ADMIN_REGISTRY_DIGEST": re.compile(
        r"ghcr\.io/authorityclosers/authority-closers-admin-web@sha256:[0-9a-f]{64}"
    ),
    "AC_ADMIN_TRANSPORT_DIGEST": re.compile(r"sha256:[0-9a-f]{64}"),
    "AC_API_IMAGE": re.compile(r"sha256:[0-9a-f]{64}"),
    "AC_API_REGISTRY_DIGEST": re.compile(
        r"ghcr\.io/authorityclosers/authority-closers-api@sha256:[0-9a-f]{64}"
    ),
    "AC_API_TRANSPORT_DIGEST": re.compile(r"sha256:[0-9a-f]{64}"),
    "AC_COACH_IMAGE": re.compile(r"sha256:[0-9a-f]{64}"),
    "AC_COACH_REGISTRY_DIGEST": re.compile(
        r"ghcr\.io/authorityclosers/authority-closers-coach-web@sha256:[0-9a-f]{64}"
    ),
    "AC_COACH_TRANSPORT_DIGEST": re.compile(r"sha256:[0-9a-f]{64}"),
    "AC_LEARNER_IMAGE": re.compile(r"sha256:[0-9a-f]{64}"),
    "AC_LEARNER_REGISTRY_DIGEST": re.compile(
        r"ghcr\.io/authorityclosers/authority-closers-learner-web@sha256:[0-9a-f]{64}"
    ),
    "AC_LEARNER_TRANSPORT_DIGEST": re.compile(r"sha256:[0-9a-f]{64}"),
    "AC_MIGRATION_HEAD": re.compile(r"[0-9]{8}_[0-9]{4}"),
    "AC_RELEASE_ID": re.compile(r"[0-9a-f]{40}"),
}


class ReleaseInputError(RuntimeError):
    """A release input violated the stable-copy or reviewed-manifest contract."""


@dataclass(frozen=True, slots=True)
class FileIdentity:
    device: int
    inode: int
    mode: int
    size: int
    modified_ns: int
    changed_ns: int

    @classmethod
    def from_stat(cls, value: os.stat_result) -> FileIdentity:
        return cls(
            device=value.st_dev,
            inode=value.st_ino,
            mode=value.st_mode,
            size=value.st_size,
            modified_ns=value.st_mtime_ns,
            # Windows exposes creation metadata as ctime and may update its
            # nanosecond representation when a file handle opens. POSIX ctime
            # is the mutation signal needed for the stable-copy check.
            changed_ns=value.st_ctime_ns if os.name == "posix" else 0,
        )


def _require_absolute(path: Path, label: str) -> None:
    if not path.is_absolute():
        raise ReleaseInputError(f"{label} must be absolute")


def _regular_identity(path: Path, label: str) -> FileIdentity:
    try:
        value = path.stat(follow_symlinks=False)
    except OSError as error:
        raise ReleaseInputError(f"{label} must be a readable regular non-symlink file") from error
    if not stat.S_ISREG(value.st_mode):
        raise ReleaseInputError(f"{label} must be a readable regular non-symlink file")
    return FileIdentity.from_stat(value)


def _directory_identity(path: Path, label: str) -> FileIdentity:
    try:
        value = path.stat(follow_symlinks=False)
    except OSError as error:
        raise ReleaseInputError(f"{label} must be a non-symlink directory") from error
    if not stat.S_ISDIR(value.st_mode):
        raise ReleaseInputError(f"{label} must be a non-symlink directory")
    return FileIdentity.from_stat(value)


def _open_readonly(path: Path, expected: FileIdentity, label: str) -> int:
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as error:
        raise ReleaseInputError(f"{label} could not be opened without following links") from error
    opened = os.fstat(descriptor)
    if not stat.S_ISREG(opened.st_mode) or FileIdentity.from_stat(opened) != expected:
        os.close(descriptor)
        raise ReleaseInputError(f"{label} changed before it could be opened")
    return descriptor


def _assert_stable(
    path: Path,
    descriptor: int,
    expected: FileIdentity,
    label: str,
) -> None:
    opened = FileIdentity.from_stat(os.fstat(descriptor))
    current = _regular_identity(path, label)
    if opened != expected or current != expected:
        raise ReleaseInputError(f"{label} changed while it was being consumed")


def _copy_regular_file(source: Path, destination: Path, label: str) -> FileIdentity:
    expected = _regular_identity(source, label)
    source_descriptor = _open_readonly(source, expected, label)
    destination_flags = (
        os.O_WRONLY
        | os.O_CREAT
        | os.O_EXCL
        | getattr(os, "O_BINARY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    try:
        destination_descriptor = os.open(destination, destination_flags, 0o600)
    except OSError as error:
        os.close(source_descriptor)
        raise ReleaseInputError("private input staging destination is not empty") from error
    try:
        with (
            os.fdopen(source_descriptor, "rb", closefd=False) as source_file,
            os.fdopen(destination_descriptor, "wb", closefd=False) as destination_file,
        ):
            shutil.copyfileobj(source_file, destination_file, length=1024 * 1024)
            destination_file.flush()
            os.fsync(destination_descriptor)
        _assert_stable(source, source_descriptor, expected, label)
        # The destination was created O_EXCL inside a private directory, so it
        # cannot become a symlink between creation and this mode change.
        os.chmod(destination, 0o600)
    except BaseException:
        with suppress(OSError):
            destination.unlink(missing_ok=True)
        raise
    finally:
        os.close(source_descriptor)
        os.close(destination_descriptor)
    return expected


def _read_regular_bytes(path: Path, label: str, *, max_bytes: int = 64 * 1024) -> bytes:
    expected = _regular_identity(path, label)
    if expected.size > max_bytes:
        raise ReleaseInputError(f"{label} exceeds the bounded text contract")
    descriptor = _open_readonly(path, expected, label)
    try:
        with os.fdopen(descriptor, "rb", closefd=False) as source_file:
            payload = source_file.read(max_bytes + 1)
        if len(payload) > max_bytes:
            raise ReleaseInputError(f"{label} exceeds the bounded text contract")
        _assert_stable(path, descriptor, expected, label)
        return payload
    finally:
        os.close(descriptor)


def _sha256_regular_file(path: Path, label: str) -> str:
    expected = _regular_identity(path, label)
    descriptor = _open_readonly(path, expected, label)
    digest = hashlib.sha256()
    try:
        with os.fdopen(descriptor, "rb", closefd=False) as source_file:
            for chunk in iter(lambda: source_file.read(1024 * 1024), b""):
                digest.update(chunk)
        _assert_stable(path, descriptor, expected, label)
        return digest.hexdigest()
    finally:
        os.close(descriptor)


def _directory_entries(path: Path, label: str) -> dict[str, FileIdentity]:
    entries: dict[str, FileIdentity] = {}
    try:
        with os.scandir(path) as candidates:
            for candidate in candidates:
                try:
                    entries[candidate.name] = _regular_identity(
                        path / candidate.name,
                        f"{label} entry",
                    )
                except ReleaseInputError as error:
                    raise ReleaseInputError(f"{label} contains a non-regular entry") from error
    except OSError as error:
        raise ReleaseInputError(f"{label} could not be inspected") from error
    return entries


def _fsync_directory(path: Path) -> None:
    if os.name != "posix":
        return
    descriptor = os.open(
        path,
        os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0),
    )
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def stage_release_inputs(archive: Path, bundle: Path, destination: Path) -> None:
    """Copy all caller inputs once into an empty private destination."""

    for path, label in (
        (archive, "release archive"),
        (bundle, "image bundle"),
        (destination, "private input staging directory"),
    ):
        _require_absolute(path, label)
    archive_identity = _regular_identity(archive, "release archive")
    bundle_identity = _directory_identity(bundle, "image bundle")
    destination_identity = _directory_identity(destination, "private input staging directory")
    if os.name == "posix":
        get_effective_user_id = getattr(os, "geteuid", None)
        if get_effective_user_id is None or destination.stat().st_uid != get_effective_user_id():
            raise ReleaseInputError("private input staging directory has the wrong owner")
        if stat.S_IMODE(destination_identity.mode) != 0o700:
            raise ReleaseInputError("private input staging directory must have mode 0700")
    if any(destination.iterdir()):
        raise ReleaseInputError("private input staging directory must be empty")

    bundle_entries = _directory_entries(bundle, "image bundle")
    if set(bundle_entries) != BUNDLE_FILES:
        raise ReleaseInputError("image bundle does not contain the exact reviewed file set")

    _copy_regular_file(archive, destination / "release-archive.tar", "release archive")
    staged_bundle = destination / "image-bundle"
    staged_bundle.mkdir(mode=0o700)
    for filename in sorted(BUNDLE_FILES):
        copied_identity = _copy_regular_file(
            bundle / filename,
            staged_bundle / filename,
            f"image bundle {filename}",
        )
        if copied_identity != bundle_entries[filename]:
            raise ReleaseInputError(f"image bundle {filename} changed before staging")

    if _regular_identity(archive, "release archive") != archive_identity:
        raise ReleaseInputError("release archive changed while inputs were being staged")
    if _directory_identity(bundle, "image bundle") != bundle_identity:
        raise ReleaseInputError("image bundle changed while inputs were being staged")
    if _directory_entries(bundle, "image bundle") != bundle_entries:
        raise ReleaseInputError("image bundle files changed while inputs were being staged")
    _fsync_directory(staged_bundle)
    _fsync_directory(destination)


def _parse_checksums(payload: bytes) -> dict[str, str]:
    try:
        text = payload.decode("ascii")
    except UnicodeDecodeError as error:
        raise ReleaseInputError("bundle checksum manifest must be ASCII") from error
    lines = text.splitlines()
    if text != "".join(f"{line}\n" for line in lines):
        raise ReleaseInputError("bundle checksum manifest must use canonical lines")
    checksums: dict[str, str] = {}
    pattern = re.compile(r"([0-9a-f]{64})  ([A-Za-z0-9._-]+)")
    for line in lines:
        match = pattern.fullmatch(line)
        if match is None:
            raise ReleaseInputError("bundle checksum manifest is malformed")
        digest, filename = match.groups()
        if filename not in CHECKSUM_FILES or filename in checksums:
            raise ReleaseInputError("bundle checksum manifest has an unexpected contract")
        checksums[filename] = digest
    if set(checksums) != CHECKSUM_FILES:
        raise ReleaseInputError("bundle checksum manifest is incomplete")
    return checksums


def _parse_manifest(payload: bytes, expected_release_id: str) -> dict[str, str]:
    try:
        text = payload.decode("ascii")
    except UnicodeDecodeError as error:
        raise ReleaseInputError("release image manifest must be ASCII") from error
    lines = text.splitlines()
    if text != "".join(f"{line}\n" for line in lines):
        raise ReleaseInputError("release image manifest must use canonical lines")
    values: dict[str, str] = {}
    for line in lines:
        key, separator, value = line.partition("=")
        if separator != "=" or key not in _MANIFEST_PATTERNS or key in values:
            raise ReleaseInputError("release image manifest has an unexpected key contract")
        if _MANIFEST_PATTERNS[key].fullmatch(value) is None:
            raise ReleaseInputError(f"release image manifest {key} is malformed")
        values[key] = value
    if set(values) != set(MANIFEST_KEYS):
        raise ReleaseInputError("release image manifest has an incomplete key contract")
    if values["AC_RELEASE_ID"] != expected_release_id:
        raise ReleaseInputError("release image manifest does not match the source release")
    for component in ("ADMIN", "API", "COACH", "LEARNER"):
        runtime_identity = values[f"AC_{component}_IMAGE"]
        transport_identity = values[f"AC_{component}_TRANSPORT_DIGEST"]
        if runtime_identity != transport_identity:
            raise ReleaseInputError(
                f"release image manifest AC_{component}_IMAGE must match its OCI transport digest"
            )
    return values


def verify_bundle(bundle: Path, expected_release_id: str) -> tuple[str, ...]:
    """Verify staged bundle hashes and return strict values in fixed key order."""

    _require_absolute(bundle, "staged image bundle")
    if _MANIFEST_PATTERNS["AC_RELEASE_ID"].fullmatch(expected_release_id) is None:
        raise ReleaseInputError("expected release ID is malformed")
    _directory_identity(bundle, "staged image bundle")
    entries = _directory_entries(bundle, "staged image bundle")
    if set(entries) != BUNDLE_FILES:
        raise ReleaseInputError("staged image bundle has an unexpected file contract")
    checksums = _parse_checksums(
        _read_regular_bytes(bundle / "SHA256SUMS", "bundle checksum manifest")
    )
    image_filename = "application-images.tar.gz"
    if (
        _sha256_regular_file(
            bundle / image_filename,
            f"staged image bundle {image_filename}",
        )
        != checksums[image_filename]
    ):
        raise ReleaseInputError(f"staged image bundle checksum mismatch: {image_filename}")
    manifest_filename = "release-images.env"
    manifest_payload = _read_regular_bytes(
        bundle / manifest_filename,
        f"staged image bundle {manifest_filename}",
    )
    if hashlib.sha256(manifest_payload).hexdigest() != checksums[manifest_filename]:
        raise ReleaseInputError(f"staged image bundle checksum mismatch: {manifest_filename}")
    values = _parse_manifest(manifest_payload, expected_release_id)
    return tuple(values[key] for key in MANIFEST_KEYS)


def main(arguments: list[str] | None = None) -> int:
    args = sys.argv[1:] if arguments is None else arguments
    try:
        if len(args) == 4 and args[0] == "stage":
            stage_release_inputs(Path(args[1]), Path(args[2]), Path(args[3]))
            return 0
        if len(args) == 3 and args[0] == "verify-bundle":
            values = verify_bundle(Path(args[1]), args[2])
            sys.stdout.write("".join(f"{value}\n" for value in values))
            return 0
        raise ReleaseInputError(
            "usage: prepare-release-inputs.py stage ARCHIVE BUNDLE DESTINATION; or "
            "verify-bundle BUNDLE EXPECTED_RELEASE_ID"
        )
    except ReleaseInputError as error:
        print(f"FAIL  {error}", file=sys.stderr)
        return 1
    except OSError:
        print("FAIL  release input filesystem operation failed", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
