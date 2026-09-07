"""Read-only, checksum-pinned files behind the private object-storage port.

This adapter is never selected by default. A reviewed deployment supplies an
immutable inventory and mounts its root read-only; this is not an upload API or
a general filesystem server. Authorization remains the delivery layer's job.
"""

from __future__ import annotations

import hashlib
import os
import re
import stat
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, NoReturn

from ac_platform.media.errors import MediaStorageUnavailable
from ac_platform.media.storage import StoredObjectMetadata, UnconfiguredPrivateObjectStorage

_MAX_INVENTORY = 8192
_MAX_OBJECT_BYTES = 8 * 1024**3
_MAX_TOTAL_BYTES = 32 * 1024**3
_BUFFER_BYTES = 1024**2
_MAX_PREFIX_BYTES = _BUFFER_BYTES + 1  # HLS readers need one oversize-detection byte.
_MAX_CHUNK_BYTES = 16 * _BUFFER_BYTES
_SAFE_PATH = re.compile(r"[A-Za-z0-9_-][A-Za-z0-9_./-]{0,511}\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_CONTENT_TYPE = re.compile(r"[a-z0-9.+-]+/[a-z0-9.+-]+\Z")
_VERSION = re.compile(r"[A-Za-z0-9_.-]{1,128}\Z")


@dataclass(frozen=True, slots=True)
class FileMediaObject:
    """An explicitly authorized inventory entry, never discovered by globbing."""

    object_key: str
    relative_path: str
    content_type: str
    content_length: int
    checksum_sha256: str
    storage_version_id: str


@dataclass(frozen=True, slots=True)
class _VerifiedFile:
    path: Path
    metadata: StoredObjectMetadata
    identity: tuple[int, int, int, int, int]


def _identity(info: os.stat_result) -> tuple[int, int, int, int, int]:
    # Python 3.12 Windows lstat/fstat expose different legacy ctime semantics.
    # The explicit birth time is stable across both; POSIX ctime remains the
    # stronger metadata-change signal. Neither replaces an immutable mount.
    metadata_time = (
        getattr(info, "st_birthtime_ns", info.st_ctime_ns) if os.name == "nt" else info.st_ctime_ns
    )
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, metadata_time)


def _safe_path(value: str) -> bool:
    return bool(
        _SAFE_PATH.fullmatch(value)
        and all(part not in {"", ".", ".."} for part in value.split("/"))
        and all(not part.endswith(".") for part in value.split("/"))
    )


def _check_path(path: Path) -> None:
    """Reject symlinks and Windows reparse points, including every ancestor."""

    for component in (*reversed(path.parents), path):
        info = component.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & getattr(
            stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400
        ):
            raise MediaStorageUnavailable("Private media paths must not contain links.")
        if component != path and not stat.S_ISDIR(info.st_mode):
            raise MediaStorageUnavailable("The private media root is unavailable.")


class ReadOnlyFileMediaStorage(UnconfiguredPrivateObjectStorage):
    """Bounded file streaming with pinned bytes and no mutating operations.

    Hashes are checked at registration, then open file identities are checked
    before and after each bounded read. This detects accidental replacement or
    mutation; it does not replace a read-only mount or defend against an OS
    administrator who can alter both files and trusted deployment metadata.
    """

    def __init__(self, *, root: Path, inventory: Sequence[FileMediaObject]) -> None:
        self._files: dict[str, _VerifiedFile] = {}
        if (
            not root.is_absolute()
            or ".." in root.parts
            or not 1 <= len(inventory) <= _MAX_INVENTORY
        ):
            raise MediaStorageUnavailable("The private media inventory is invalid.")
        try:
            _check_path(root)
            if not stat.S_ISDIR(root.lstat().st_mode):
                raise MediaStorageUnavailable("The private media root is unavailable.")
            total = 0
            for entry in inventory:
                if (
                    not _safe_path(entry.object_key)
                    or not _safe_path(entry.relative_path)
                    or not _CONTENT_TYPE.fullmatch(entry.content_type)
                    or len(entry.content_type) > 128
                    or not _SHA256.fullmatch(entry.checksum_sha256)
                    or not _VERSION.fullmatch(entry.storage_version_id)
                    or type(entry.content_length) is not int
                    or not 1 <= entry.content_length <= _MAX_OBJECT_BYTES
                    or entry.object_key in self._files
                ):
                    raise MediaStorageUnavailable("The private media inventory is invalid.")
                total += entry.content_length
                if total > _MAX_TOTAL_BYTES:
                    raise MediaStorageUnavailable("The private media inventory exceeds its limit.")
                path = root.joinpath(*entry.relative_path.split("/"))
                _check_path(path)
                info = path.lstat()
                if not stat.S_ISREG(info.st_mode) or info.st_size != entry.content_length:
                    raise MediaStorageUnavailable("The private media inventory does not match.")
                item = _VerifiedFile(
                    path,
                    StoredObjectMetadata(
                        entry.object_key,
                        entry.content_type,
                        entry.content_length,
                        entry.checksum_sha256,
                        entry.storage_version_id,
                    ),
                    _identity(info),
                )
                digest = hashlib.sha256()
                with self._open(item) as source:
                    while chunk := self._read_chunk(source, item, _BUFFER_BYTES):
                        digest.update(chunk)
                if digest.hexdigest() != entry.checksum_sha256:
                    raise MediaStorageUnavailable("The private media inventory does not match.")
                self._files[entry.object_key] = item
        except OSError:
            raise MediaStorageUnavailable("The private media inventory is unavailable.") from None

    def _unavailable(self) -> NoReturn:
        raise MediaStorageUnavailable("This private media adapter is read-only.")

    @contextmanager
    def _open(self, item: _VerifiedFile) -> Iterator[BinaryIO]:
        try:
            _check_path(item.path)
            flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
            descriptor = os.open(item.path, flags)
            try:
                source = os.fdopen(descriptor, "rb", buffering=0)
            except BaseException:
                os.close(descriptor)
                raise
            with source:
                self._check_identity(source, item)
                yield source
        except OSError:
            raise MediaStorageUnavailable("The private media object is unavailable.") from None

    @staticmethod
    def _check_identity(source: BinaryIO, item: _VerifiedFile) -> None:
        info = os.fstat(source.fileno())
        if not stat.S_ISREG(info.st_mode) or _identity(info) != item.identity:
            raise MediaStorageUnavailable("The private media object changed after verification.")

    @classmethod
    def _read_chunk(cls, source: BinaryIO, item: _VerifiedFile, size: int) -> bytes:
        cls._check_identity(source, item)
        chunk = source.read(size)
        cls._check_identity(source, item)
        return chunk

    def _item(self, object_key: str) -> _VerifiedFile:
        item = self._files.get(object_key)
        if item is None:
            raise MediaStorageUnavailable("The private media object is unavailable.")
        return item

    def head(self, object_key: str) -> StoredObjectMetadata | None:
        item = self._files.get(object_key)
        if item is None:
            return None
        with self._open(item):
            return item.metadata

    def read_prefix(self, object_key: str, *, max_bytes: int = 512) -> bytes:
        if type(max_bytes) is not int or not 1 <= max_bytes <= _MAX_PREFIX_BYTES:
            raise MediaStorageUnavailable("The private media read exceeds its limit.")
        item = self._item(object_key)
        with self._open(item) as source:
            return self._read_chunk(source, item, max_bytes)

    def read(self, object_key: str) -> bytes:
        item = self._item(object_key)
        if item.metadata.content_length > _BUFFER_BYTES:
            raise MediaStorageUnavailable("Use bounded streaming for this private media object.")
        return self.read_prefix(object_key, max_bytes=item.metadata.content_length)

    def iter_range(
        self,
        object_key: str,
        *,
        start: int = 0,
        end: int | None = None,
        chunk_size: int = _BUFFER_BYTES,
    ) -> Iterator[bytes]:
        item = self._item(object_key)
        final = item.metadata.content_length - 1 if end is None else end
        if (
            type(start) is not int
            or type(final) is not int
            or not 0 <= start <= final < item.metadata.content_length
            or type(chunk_size) is not int
            or not 1 <= chunk_size <= _MAX_CHUNK_BYTES
        ):
            raise MediaStorageUnavailable("The private media range is invalid.")
        with self._open(item) as source:
            source.seek(start)
            remaining = final - start + 1
            while remaining:
                chunk = self._read_chunk(source, item, min(chunk_size, remaining))
                if not chunk:
                    raise MediaStorageUnavailable("The private media object is truncated.")
                remaining -= len(chunk)
                yield chunk

    def list_prefix(self, prefix: str) -> tuple[str, ...]:
        normalized = prefix.rstrip("/")
        if not normalized or not _safe_path(normalized):
            return ()
        return tuple(
            sorted(
                key for key in self._files if key == normalized or key.startswith(f"{normalized}/")
            )
        )
