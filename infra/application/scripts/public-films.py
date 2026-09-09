#!/usr/bin/env python3
"""Release-controlled installation of one immutable noninstructional public-film pack.

No environment flag, destination, manifest URL, provider, or metadata override
is accepted. The thin archive's manifest must match the canonical API manifest
byte-for-byte (CI assertion) and the compiled digest below. Business state is
changed only later through the separate audited application import command.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import stat
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

MANIFEST_SHA256 = "dc8f635df33432aee83c461535823881286ded1577a8f8a72dc5b10f0ad86b42"
REGISTRY_SHA256 = "fc61c87d5428d53d35b82061a53fbdbd9967b8bf658c6d0425a78a07bc106290"
MANIFEST_RELATIVE = "data/public_films_technical_demo_12s_v1.json"
POLICY_RELATIVE = "capabilities/public-films.json"
OVERRIDE_RELATIVE = "compose.public-films.yaml"
APPLICATION_ROOT = Path("/srv/authority-closers/application")
RELEASES_ROOT = APPLICATION_ROOT / "releases"
MEDIA_ROOT = APPLICATION_ROOT / "media-public-films"
ROOT_UID = 0
ROOT_GID = 0
FILE_COUNT = 30
PACK_BYTES = 54_274_209
BUFFER_BYTES = 1024**2
_SAFE_RELATIVE = re.compile(r"[A-Za-z0-9_-][A-Za-z0-9_./-]{0,159}\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_MIMES = {
    ".mp4": "video/mp4",
    ".m3u8": "application/vnd.apple.mpegurl",
    ".ts": "video/mp2t",
    ".vtt": "text/vtt",
    ".json": "application/json",
}


class PackError(RuntimeError):
    """A fixed artifact, path or release capability failed admission."""


@dataclass(frozen=True)
class PackFile:
    path: str
    length: int
    sha256: str


def _fail(message: str) -> PackError:
    return PackError(f"public-film demonstration pack refused: {message}")


def _no_duplicates(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise _fail("duplicate JSON key")
        result[key] = value
    return result


def _safe_relative(value: object) -> bool:
    return (
        isinstance(value, str)
        and bool(_SAFE_RELATIVE.fullmatch(value))
        and all(part not in {"", ".", ".."} and not part.endswith(".") for part in value.split("/"))
    )


def _trusted_metadata(info: os.stat_result, *, read_only: bool = False) -> None:
    if info.st_uid != ROOT_UID or info.st_mode & (0o222 if read_only else 0o022):
        raise _fail("installed paths must have the required root owner and immutable permissions")
    if read_only:
        expected = 0o555 if stat.S_ISDIR(info.st_mode) else 0o444
        if stat.S_IMODE(info.st_mode) != expected:
            raise _fail("installed files and directories must be exactly 0444 and 0555")


def _checked_path(path: Path, *, trusted: bool, read_only: bool = False) -> os.stat_result:
    if not path.is_absolute() or ".." in path.parts:
        raise _fail("an absolute traversal-free path is required")
    for ancestor in (*reversed(path.parents), path):
        info = ancestor.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & getattr(
            stat,
            "FILE_ATTRIBUTE_REPARSE_POINT",
            0x400,
        ):
            raise _fail("symbolic links and reparse points are forbidden")
        if ancestor != path and not stat.S_ISDIR(info.st_mode):
            raise _fail("path ancestor is not a directory")
        if trusted:
            _trusted_metadata(info, read_only=read_only and ancestor == path)
    return info


def _identity(info: os.stat_result) -> tuple[int, int, int, int, int]:
    # Python 3.12 Windows lstat/fstat differ in legacy ctime semantics. POSIX
    # keeps ctime; Windows uses the stable explicit birthtime, as the file port.
    metadata_time = (
        getattr(info, "st_birthtime_ns", info.st_ctime_ns) if os.name == "nt" else info.st_ctime_ns
    )
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, metadata_time


def _read_regular(path: Path, *, limit: int, trusted: bool) -> bytes:
    info = _checked_path(path, trusted=trusted)
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or not 0 < info.st_size <= limit:
        raise _fail("a bounded singly-linked regular file is required")
    descriptor = os.open(
        path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
    )
    with os.fdopen(descriptor, "rb") as source:
        if _identity(os.fstat(source.fileno())) != _identity(info):
            raise _fail("file identity changed before reading")
        result = source.read(limit + 1)
        if len(result) != info.st_size or _identity(os.fstat(source.fileno())) != _identity(info):
            raise _fail("file changed while reading")
    return result


def _release_root(release: Path) -> None:
    if release.parent != RELEASES_ROOT or re.fullmatch(r"[0-9a-f]{40}", release.name) is None:
        raise _fail("an exact immutable release directory is required")
    if not stat.S_ISDIR(_checked_path(release, trusted=True).st_mode):
        raise _fail("release root is unavailable")
    marker = _read_regular(release / "RELEASE-COMMIT", limit=41, trusted=True)
    if marker != (release.name + "\n").encode("ascii"):
        raise _fail("release identity marker differs from its directory")


LEARNER_ORIGINS = {
    "staging": "https://learner-staging.authorityclosers.com",
    "production": "https://learner.authorityclosers.com",
}


def load_policy(release: Path, environment: str) -> bool:
    if environment not in LEARNER_ORIGINS:
        raise _fail("only a named deployment environment is accepted")
    _release_root(release)
    policy = release / POLICY_RELATIVE
    try:
        policy.lstat()
    except FileNotFoundError:
        return False  # Older immutable releases remain off, including rollback.
    raw = _read_regular(policy, limit=4096, trusted=True)
    value = json.loads(raw, object_pairs_hook=_no_duplicates)
    if (
        not isinstance(value, dict)
        or set(value) != {"schema_version", "enabled", "manifest_sha256", "learner_origins"}
        or value["schema_version"] != "ac-public-film-demonstration-deployment.v1"
        or value["manifest_sha256"] != MANIFEST_SHA256
        or value["learner_origins"] != LEARNER_ORIGINS
        or not isinstance(value["enabled"], dict)
        or set(value["enabled"]) != set(LEARNER_ORIGINS)
        or any(type(enabled) is not bool for enabled in value["enabled"].values())
    ):
        raise _fail("the release capability policy differs from its fixed contract")
    enabled = value["enabled"][environment]
    if enabled:
        raw_environment = _read_regular(
            release / "environments" / f"{environment}.env", limit=32768, trusted=True
        ).decode("utf-8")
        for key, expected in (
            ("AC_ENVIRONMENT", environment),
            ("AC_PUBLIC_APP_URL", LEARNER_ORIGINS[environment]),
        ):
            entries = [
                line.split("=", 1)[1]
                for line in raw_environment.splitlines()
                if line.startswith(key + "=")
            ]
            if entries != [expected]:
                raise _fail("enabled deployment must use its exact learner origin and environment")
    return enabled


def load_manifest(release: Path) -> tuple[PackFile, ...]:
    _release_root(release)
    raw = _read_regular(release / MANIFEST_RELATIVE, limit=2 * BUFFER_BYTES, trusted=True)
    if hashlib.sha256(raw).hexdigest() != MANIFEST_SHA256:
        raise _fail("the thin-archive manifest differs from the canonical API manifest")
    value = json.loads(raw, object_pairs_hook=_no_duplicates)
    if (
        value.get("schema_version") != "ac-public-film-demonstration-pack.v1"
        or value.get("manifest_id") != "public-films-technical-demo-12s-v1"
        or value.get("fixture_registry_sha256") != REGISTRY_SHA256
        or value.get("purpose") != "technical-playback-demonstration"
        or value.get("allowed_deployment_environments") != ["staging", "production"]
        or value.get("instructional_content") is not False
        or value.get("full_films") is not False
        or value.get("provider_activation") is not False
        or value.get("source_inventory_manifest_sha256")
        != "d693acc73dc3f66c1b13ad6e68d5e41cba8478dc719f4b68211ce829442b0222"
        or [clip.get("fixture_id") for clip in value.get("clips", [])]
        != ["bbb-4k-30-normal", "caminandes-gran-dillama-1080p"]
    ):
        raise _fail("only the reviewed two-film manifest is accepted")
    result = []
    seen = set()
    for clip, directory in zip(value["clips"], ("bbb-12s", "caminandes-12s"), strict=True):
        for entry in clip["objects"]:
            if set(entry) != {"path", "content_type", "content_length", "sha256"}:
                raise _fail("unexpected object metadata")
            path = entry["path"]
            if (
                not _safe_relative(path)
                or not path.startswith(directory + "/")
                or path in seen
                or _MIMES.get(Path(path).suffix) != entry["content_type"]
                or type(entry["content_length"]) is not int
                or not 0 < entry["content_length"] <= 128 * BUFFER_BYTES
                or not isinstance(entry["sha256"], str)
                or not _SHA256.fullmatch(entry["sha256"])
            ):
                raise _fail("unsafe or unbounded object inventory")
            seen.add(path)
            result.append(PackFile(path, entry["content_length"], entry["sha256"]))
    if len(result) != FILE_COUNT or sum(item.length for item in result) != PACK_BYTES:
        raise _fail("the fixed object count or total bytes changed")
    return tuple(result)


def _inventory(root: Path, files: tuple[PackFile, ...], *, installed: bool) -> None:
    root_info = _checked_path(root, trusted=installed, read_only=installed)
    if not stat.S_ISDIR(root_info.st_mode):
        raise _fail("pack root is not a directory")
    expected_files = {item.path for item in files}
    expected_dirs = {
        str(parent).replace("\\", "/")
        for item in files
        for parent in Path(item.path).parents
        if str(parent) != "."
    }
    observed = set()
    pending = [root]
    while pending:
        directory = pending.pop()
        with os.scandir(directory) as entries:
            for entry in entries:
                relative = Path(entry.path).relative_to(root).as_posix()
                info = entry.stat(follow_symlinks=False)
                if installed:
                    _trusted_metadata(info, read_only=True)
                if stat.S_ISDIR(info.st_mode) and relative in expected_dirs:
                    _checked_path(Path(entry.path), trusted=installed, read_only=installed)
                    pending.append(Path(entry.path))
                elif (
                    stat.S_ISREG(info.st_mode) and relative in expected_files and info.st_nlink == 1
                ):
                    _checked_path(Path(entry.path), trusted=installed, read_only=installed)
                    observed.add(relative)
                else:
                    raise _fail("pack contains extra, linked or non-regular objects")
    if observed != expected_files:
        raise _fail("pack object inventory is incomplete")


def _stream_verified(path: Path, item: PackFile, output: BinaryIO | None = None) -> None:
    before = _checked_path(path, trusted=False)
    if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or before.st_size != item.length:
        raise _fail("object length or file kind differs from the reviewed manifest")
    descriptor = os.open(
        path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
    )
    digest = hashlib.sha256()
    with os.fdopen(descriptor, "rb") as source:
        if _identity(os.fstat(source.fileno())) != _identity(before):
            raise _fail("source identity changed before copying")
        remaining = item.length
        while remaining:
            chunk = source.read(min(remaining, BUFFER_BYTES))
            if not chunk:
                raise _fail("source ended before its reviewed length")
            remaining -= len(chunk)
            digest.update(chunk)
            if output is not None:
                output.write(chunk)
        if source.read(1) or _identity(os.fstat(source.fileno())) != _identity(before):
            raise _fail("source changed while copying")
    if _identity(path.lstat()) != _identity(before) or digest.hexdigest() != item.sha256:
        raise _fail("object checksum or identity differs from the reviewed manifest")


def verify_pack(root: Path, files: tuple[PackFile, ...], *, installed: bool) -> None:
    _inventory(root, files, installed=installed)
    for item in files:
        _stream_verified(root / item.path, item)
    _inventory(root, files, installed=installed)


def compose_file(release: Path, environment: str) -> str:
    if not load_policy(release, environment):
        return ""
    # Exact-commit RELEASE-FILES validation is the installer's source authority.
    override = release / OVERRIDE_RELATIVE
    _read_regular(override, limit=8192, trusted=True)
    load_manifest(release)
    return str(override)


def preflight(release: Path, environment: str) -> None:
    if load_policy(release, environment):
        compose_file(release, environment)
        verify_pack(MEDIA_ROOT / MANIFEST_SHA256, load_manifest(release), installed=True)


def _sync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def install_pack(release: Path, environment: str, source: Path) -> str:
    if environment not in {"staging", "production"}:
        raise _fail("installation requires a named deployment environment")
    if os.name != "posix" or os.geteuid() != ROOT_UID:
        raise _fail("installation requires the root operator on the POSIX deployment host")
    # Installing inert bytes is permitted while policy remains disabled; only
    # a separately reviewed release policy can mount them into the API.
    load_policy(release, environment)
    files = load_manifest(release)
    verify_pack(source, files, installed=False)
    _checked_path(APPLICATION_ROOT, trusted=True)
    if not MEDIA_ROOT.exists() and not MEDIA_ROOT.is_symlink():
        MEDIA_ROOT.mkdir(mode=0o755)
        os.chown(MEDIA_ROOT, ROOT_UID, ROOT_GID)
    _checked_path(MEDIA_ROOT, trusted=True)
    import fcntl

    lock_fd = os.open(MEDIA_ROOT / ".install.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    stage = None
    try:
        lock_info = os.fstat(lock_fd)
        _trusted_metadata(lock_info)
        if not stat.S_ISREG(lock_info.st_mode) or lock_info.st_nlink != 1:
            raise _fail("pack installation lock is invalid")
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        destination = MEDIA_ROOT / MANIFEST_SHA256
        if destination.exists() or destination.is_symlink():
            verify_pack(destination, files, installed=True)
            return "already_installed"
        stage = Path(tempfile.mkdtemp(prefix=f".install-{MANIFEST_SHA256}-", dir=MEDIA_ROOT))
        os.chown(stage, ROOT_UID, ROOT_GID)
        for item in files:
            target = stage / item.path
            target.parent.mkdir(parents=True, exist_ok=True, mode=0o755)
            with target.open("xb") as output:
                _stream_verified(source / item.path, item, output)
                output.flush()
                os.fsync(output.fileno())
            os.chown(target, ROOT_UID, ROOT_GID)
            target.chmod(0o444)
        directories = sorted(
            (path for path in stage.rglob("*") if path.is_dir()),
            key=lambda path: len(path.parts),
            reverse=True,
        )
        for directory in (*directories, stage):
            os.chown(directory, ROOT_UID, ROOT_GID)
            directory.chmod(0o555)
            _sync_directory(directory)
        verify_pack(stage, files, installed=True)
        if destination.exists() or destination.is_symlink():
            raise _fail("immutable destination appeared during installation")
        stage.rename(destination)
        stage = None
        _sync_directory(MEDIA_ROOT)
        return "installed"
    finally:
        try:
            if stage is not None:
                # Only the freshly created, validated sibling stage is removable.
                if stage.parent != MEDIA_ROOT or not stage.name.startswith(
                    f".install-{MANIFEST_SHA256}-"
                ):
                    raise _fail("unexpected staging cleanup path")
                if stage.exists():
                    for directory in (stage, *(path for path in stage.rglob("*") if path.is_dir())):
                        directory.chmod(0o700)
                    shutil.rmtree(stage)
        finally:
            os.close(lock_fd)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("compose-file", "preflight", "install"))
    parser.add_argument("release", type=Path)
    parser.add_argument("environment", choices=("staging", "production"))
    parser.add_argument("source", type=Path, nargs="?")
    args = parser.parse_args(argv)
    try:
        if args.command == "install":
            if args.source is None:
                raise _fail("installation requires an explicit source pack directory")
            print(install_pack(args.release, args.environment, args.source))
        elif args.source is not None:
            raise _fail("source input is accepted only by the pack installation command")
        elif args.command == "compose-file":
            print(compose_file(args.release, args.environment))
        else:
            preflight(args.release, args.environment)
    except (PackError, OSError, ValueError, KeyError, TypeError):
        print(
            "FAIL  Public-film release policy or immutable package validation failed.",
            file=sys.stderr,
        )
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
