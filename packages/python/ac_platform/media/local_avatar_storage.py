"""Private, bounded localhost avatar objects. Never a production/provider adapter."""

from __future__ import annotations

import hashlib
import json
import re
import stat
import threading
from collections.abc import Iterator
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import quote

from ac_platform.media.errors import MediaConflict, MediaStorageUnavailable
from ac_platform.media.signing import MediaSigner
from ac_platform.media.storage import (
    _LOCAL_AVATAR_UPLOAD_CONTRACT,
    PrivateObjectStorage,
    StorageUploadIntent,
    StoredObjectMetadata,
)

MAX_AVATAR_BYTES = 5 * 1024 * 1024
MAX_LOCAL_STORE_BYTES = 100 * 1024 * 1024
LOCAL_AVATAR_ORIGIN = "http://learner.localhost:3100"
UPLOAD_PREFIX = "/v1/media/local-avatar-upload/"
_UUID = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
_KEY = re.compile(
    rf"tenants/{_UUID}/media/avatar/{_UUID}/{_UUID}/original(?:/avatar/(?:128|256|512))?"
)
_LOCK = threading.RLock()
_MARKER = b"AC disposable localhost avatar objects v1\n"


def require_plain_path(path: Path) -> None:
    for part in (path, *path.parents):
        if part.exists() or part.is_symlink():
            info = part.lstat()
            if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
                raise MediaStorageUnavailable("Local avatar storage cannot follow links.")


class LocalAvatarStorage:
    """Immutable checksum-verified envelopes; keys never become filesystem paths.

    A marked, private directory persists across API restarts. Non-avatar reads
    delegate to the independently verified read-only public-film inventory.
    Writes/deletes can affect only exact avatar keys. This is a single-process
    local development store, not a general object provider or malware scanner.
    """

    def __init__(self, *, root: Path, signer: MediaSigner, fallback: PrivateObjectStorage) -> None:
        if not root.is_absolute() or root.name != "avatar-objects":
            raise MediaStorageUnavailable("Local avatar storage requires its named isolated root.")
        require_plain_path(root)
        root.mkdir(parents=True, exist_ok=True)
        marker = root / ".local-avatar-store"
        require_plain_path(marker)
        if not marker.exists():
            if tuple(root.iterdir()):
                raise MediaStorageUnavailable("Local avatar storage refuses an unmarked directory.")
            with marker.open("xb") as stream:
                stream.write(_MARKER)
        if marker.read_bytes() != _MARKER:
            raise MediaStorageUnavailable("Local avatar storage marker is invalid.")
        self.root, self.signer, self.fallback = root, signer, fallback

    @staticmethod
    def owns(key: str) -> bool:
        return bool(_KEY.fullmatch(key))

    def _path(self, key: str) -> Path:
        if not self.owns(key):
            raise MediaStorageUnavailable("The local avatar object namespace is invalid.")
        path = self.root / (hashlib.sha256(key.encode()).hexdigest() + ".blob")
        require_plain_path(path)
        return path

    def _load(self, key: str) -> tuple[StoredObjectMetadata, bytes] | None:
        path = self._path(key)
        with _LOCK:
            if not path.exists():
                return None
            if not path.is_file() or not 0 < path.stat().st_size <= MAX_AVATAR_BYTES + 4096:
                raise MediaStorageUnavailable("The local avatar envelope is invalid.")
            try:
                with path.open("rb") as stream:
                    header = stream.readline(4097)
                    if len(header) > 4096 or not header.endswith(b"\n"):
                        raise ValueError
                    metadata = StoredObjectMetadata(**json.loads(header))
                    body = stream.read(MAX_AVATAR_BYTES + 1)
                if (
                    metadata.object_key != key
                    or metadata.content_type not in {"image/jpeg", "image/png", "image/webp"}
                    or not 0 < len(body) <= MAX_AVATAR_BYTES
                    or metadata.content_length != len(body)
                    or metadata.checksum_sha256 != hashlib.sha256(body).hexdigest()
                    or metadata.storage_version_id != metadata.checksum_sha256
                ):
                    raise ValueError
                return metadata, body
            except (OSError, TypeError, ValueError) as error:
                raise MediaStorageUnavailable(
                    "The local avatar object failed integrity checks."
                ) from error

    def create_upload_intent(
        self,
        *,
        object_key: str,
        content_type: str,
        content_length: int,
        checksum_sha256: str | None,
        expires_at: datetime,
    ) -> StorageUploadIntent:
        self._path(object_key)
        if (
            not object_key.endswith("/original")
            or content_type not in {"image/jpeg", "image/png", "image/webp"}
            or not 0 < content_length <= MAX_AVATAR_BYTES
            or not checksum_sha256
            or not re.fullmatch(r"[0-9a-f]{64}", checksum_sha256)
        ):
            raise MediaStorageUnavailable("The local avatar upload contract is invalid.")
        expiry = expires_at.replace(tzinfo=UTC) if expires_at.tzinfo is None else expires_at
        now = datetime.now(UTC)
        token = self.signer.sign(
            {
                "key": object_key,
                "bytes": content_length,
                "mime": content_type,
                "checksum": checksum_sha256,
            },
            now=now,
            lifetime=expiry - now,
            token_type="local-avatar-upload",  # noqa: S106 - token kind
        )
        return StorageUploadIntent(
            f"{LOCAL_AVATAR_ORIGIN}{UPLOAD_PREFIX}{quote(object_key, safe='')}?token={token}",
            object_key,
            expiry,
            {
                "Content-Type": content_type,
                "Content-Length": str(content_length),
                "x-content-sha256": checksum_sha256,
            },
            _contract=_LOCAL_AVATAR_UPLOAD_CONTRACT,
        )

    def head(self, object_key: str) -> StoredObjectMetadata | None:
        if not self.owns(object_key):
            return self.fallback.head(object_key)
        result = self._load(object_key)
        return result[0] if result else None

    def read(self, object_key: str) -> bytes:
        if not self.owns(object_key):
            return self.fallback.read(object_key)
        result = self._load(object_key)
        if result is None:
            raise MediaStorageUnavailable("The local avatar object is unavailable.")
        return result[1]

    def read_prefix(self, object_key: str, *, max_bytes: int = 512) -> bytes:
        return (
            self.read(object_key)[:max_bytes]
            if self.owns(object_key)
            else self.fallback.read_prefix(object_key, max_bytes=max_bytes)
        )

    def iter_range(
        self,
        object_key: str,
        *,
        start: int = 0,
        end: int | None = None,
        chunk_size: int = 1024 * 1024,
    ) -> Iterator[bytes]:
        if not self.owns(object_key):
            yield from self.fallback.iter_range(
                object_key, start=start, end=end, chunk_size=chunk_size
            )
            return
        if start < 0 or (end is not None and end < start) or not 0 < chunk_size <= MAX_AVATAR_BYTES:
            raise MediaStorageUnavailable("The local avatar range is invalid.")
        body = self.read(object_key)
        stop = len(body) if end is None else min(end + 1, len(body))
        for offset in range(start, stop, chunk_size):
            yield body[offset : min(offset + chunk_size, stop)]

    def put(
        self,
        *,
        object_key: str,
        body: bytes,
        content_type: str,
        storage_version_id: str | None = None,
    ) -> StoredObjectMetadata:
        del storage_version_id
        path = self._path(object_key)
        if not 0 < len(body) <= MAX_AVATAR_BYTES or content_type not in {
            "image/jpeg",
            "image/png",
            "image/webp",
        }:
            raise MediaStorageUnavailable("The local avatar bytes exceed the storage contract.")
        checksum = hashlib.sha256(body).hexdigest()
        metadata = StoredObjectMetadata(object_key, content_type, len(body), checksum, checksum)
        with _LOCK:
            existing = self._load(object_key)
            if existing is not None:
                if existing[0] != metadata:
                    raise MediaConflict(
                        "Local avatar bytes are immutable; create a replacement version."
                    )
                return existing[0]
            encoded = json.dumps(asdict(metadata), separators=(",", ":")).encode() + b"\n" + body
            total = 0
            for entry in self.root.iterdir():
                require_plain_path(entry)
                if not entry.is_file():
                    raise MediaStorageUnavailable("Unexpected local avatar storage entry.")
                total += entry.stat().st_size
            if total + len(encoded) > MAX_LOCAL_STORE_BYTES:
                raise MediaStorageUnavailable(
                    "Local avatar storage is full; existing photos are preserved."
                )
            with path.open("xb") as stream:
                stream.write(encoded)
            return metadata

    def copy(
        self,
        *,
        source_key: str,
        destination_key: str,
        content_type: str,
        create_only: bool = False,
    ) -> StoredObjectMetadata:
        if type(create_only) is not bool:
            raise MediaStorageUnavailable("The local avatar copy contract is invalid.")
        if not self.owns(destination_key):
            return self.fallback.copy(
                source_key=source_key,
                destination_key=destination_key,
                content_type=content_type,
                create_only=create_only,
            )
        with _LOCK:
            if create_only and self._load(destination_key) is not None:
                raise MediaConflict("The local avatar destination already exists.")
            return self.put(
                object_key=destination_key, body=self.read(source_key), content_type=content_type
            )

    def delete(self, object_key: str) -> None:
        with _LOCK:
            path = self._path(object_key)
            if self._load(object_key) is not None:
                path.unlink()

    def list_prefix(self, prefix: str) -> tuple[str, ...]:
        # No prefix scans are needed by the narrowly scoped avatar processor.
        del prefix
        return ()
