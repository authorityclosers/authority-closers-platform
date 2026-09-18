"""Explicit private video storage with bounded, atomic streaming writes.

Storage metadata describes bytes, never authorization, scanning or publication.
Generic browser grants remain disabled. After canonical Studio admission, this
adapter can issue only its exact same-host, cookie-authenticated byte-route path.
Use a dedicated service-owned local filesystem, not NFS or an untrusted directory.
All cooperating writers share OS locks and a logical-envelope-byte budget.
Reservations use file lengths; sparse files do not guarantee allocated disk space.
File and process-restart integrity is tested. Host/power-loss durability is not:
directory synchronization and target-filesystem recovery proof precede activation.
"""

from __future__ import annotations

import errno
import hashlib
import json
import os
import re
import stat
import sys
import time
from collections.abc import Callable, Iterable, Iterator
from contextlib import AbstractContextManager, contextmanager
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import BinaryIO
from uuid import UUID, uuid4

from ac_platform.media.errors import MediaConflict, MediaStorageUnavailable
from ac_platform.media.file_storage import _check_path, _identity
from ac_platform.media.storage import (
    _STUDIO_VIDEO_UPLOAD_CONTRACT,
    StorageUploadIntent,
    StoredObjectMetadata,
    StudioVideoStorageUploadIntent,
)

CHUNK_BYTES = 1024 * 1024
# Browser requests stay well below the smallest supported edge request limit.
# The receiver still consumes each request in CHUNK_BYTES frames.
RESUMABLE_CHUNK_BYTES = 16 * 1024 * 1024
_HEADER_BYTES = 4096
_GUARD_WAIT_SECONDS = 2.0
_GUARD_RETRY_SECONDS = 0.01
_UUID = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
_KEY = re.compile(rf"tenants/{_UUID}/media/video/{_UUID}/{_UUID}/original(?:/[a-zA-Z0-9_./-]+)?\Z")
_HASH = re.compile(r"[0-9a-f]{64}\Z")
_ENTRY = re.compile(r"(?:[0-9a-f]{64}\.object|[0-9a-f]{2}\.lock|[0-9a-f]{32}\.part)\Z")
_MARKER = b"AC private immutable video objects v1\n"
_VERIFICATION_SEAL = object()
_TYPES = frozenset(
    {
        "video/mp4",
        "video/webm",
        "video/mp2t",
        "application/vnd.apple.mpegurl",
        "application/x-mpegurl",
        "application/octet-stream",
        "text/vtt",
        "image/jpeg",
        "image/webp",
    }
)


@dataclass(frozen=True)
class _Object:
    metadata: StoredObjectMetadata
    identity: tuple[int, int, int, int, int]


@dataclass(frozen=True)
class ResumableUploadResult:
    uploaded_bytes: int
    metadata: StoredObjectMetadata | None = None


@dataclass
class ActiveVideoObjectVerification:
    """Short-lived guard held continuously from full hash through DB commit."""

    metadata: StoredObjectMetadata
    _storage: VideoFileStorage = field(repr=False)
    _identity: tuple[int, int, int, int, int] = field(repr=False)
    _seal: object = field(repr=False)
    active: bool = field(default=True, repr=False)


class VideoFileStorage:
    """Filesystem implementation of the byte port; disabled until composed.

    Writes reserve their complete envelope size before consuming input. Interrupted
    writes are removed when bounded cleanup succeeds; otherwise leftovers remain
    charged and never readable, just like process-crash leftovers.
    Operators must reconcile leftovers through a future explicit maintenance
    command, not silently erase them on startup. Published keys are immutable.

    Every metadata inspection rehashes the complete bounded object. File identity
    and timestamps cannot prove byte integrity, especially on Windows. This is
    intentionally O(object size) I/O per inspection, including range admission;
    caching needs a stronger immutable-storage guarantee before it can be safe.

    Object-key locks use 256 fixed stripes. Different keys can contend and
    require a retry, but failed/deleted objects cannot grow lockfiles forever.
    Lockfiles are never unlinked or silently migrated from older layouts.
    """

    def __init__(
        self, *, root: Path, max_object_bytes: int, max_store_bytes: int, max_objects: int = 16384
    ) -> None:
        if (
            not root.is_absolute()
            or ".." in root.parts
            or root.name != "video-objects"
            or type(max_object_bytes) is not int
            or not 1 <= max_object_bytes <= 8 * 1024**3
            or type(max_store_bytes) is not int
            or not max_object_bytes + _HEADER_BYTES <= max_store_bytes <= 1024**4
            or type(max_objects) is not int
            or not 1 <= max_objects <= 65536
        ):
            raise MediaStorageUnavailable("The private video storage configuration is invalid.")
        self.root, self.max_object_bytes, self.max_store_bytes = (
            root,
            max_object_bytes,
            max_store_bytes,
        )
        self.max_objects = max_objects
        try:
            _check_path(root.parent)
            root.mkdir(mode=0o700, exist_ok=True)
            _check_path(root)
            if not root.is_dir():
                raise MediaStorageUnavailable("The private video root is unavailable.")
            marker = root / ".video-store-v1"
            if not marker.exists():
                if tuple(root.iterdir()):
                    raise MediaStorageUnavailable(
                        "Private video storage refuses an unmarked directory."
                    )
                with marker.open("xb") as stream:
                    self._write_all(stream, _MARKER)
                    stream.flush()
                    os.fsync(stream.fileno())
            _check_path(marker)
            if marker.stat().st_size != len(_MARKER) or marker.read_bytes() != _MARKER:
                raise MediaStorageUnavailable("The private video store marker is invalid.")
        except OSError:
            raise MediaStorageUnavailable("The private video root is unavailable.") from None

    def create_upload_intent(
        self,
        *,
        object_key: str,
        content_type: str,
        content_length: int,
        checksum_sha256: str | None,
        expires_at: datetime,
    ) -> StorageUploadIntent:
        del object_key, content_type, content_length, checksum_sha256, expires_at
        raise MediaStorageUnavailable("This private video adapter issues no upload grants.")

    def create_studio_video_upload_intent(
        self,
        *,
        object_key: str,
        tenant_id: UUID,
        owner_person_id: UUID,
        program_id: UUID,
        upload_id: UUID,
        content_type: str,
        content_length: int,
        checksum_sha256: str,
        expires_at: datetime,
    ) -> StudioVideoStorageUploadIntent:
        """Issue only the authenticated same-host route for an admitted upload."""

        self._path(object_key)
        if (
            not isinstance(tenant_id, UUID)
            or not isinstance(owner_person_id, UUID)
            or not isinstance(program_id, UUID)
            or not isinstance(upload_id, UUID)
            or not object_key.startswith(f"tenants/{tenant_id}/media/video/")
            or content_type not in {"video/mp4", "video/webm"}
            or type(content_length) is not int
            or not 0 < content_length <= self.max_object_bytes
            or not isinstance(checksum_sha256, str)
            or _HASH.fullmatch(checksum_sha256) is None
        ):
            raise MediaStorageUnavailable("The Studio video upload contract is invalid.")
        expiry = expires_at.replace(tzinfo=UTC) if expires_at.tzinfo is None else expires_at
        return StudioVideoStorageUploadIntent(
            upload_url=(f"/v1/admin/studio/programs/{program_id}/video-uploads/{upload_id}/bytes"),
            object_key=object_key,
            tenant_id=tenant_id,
            owner_person_id=owner_person_id,
            program_id=program_id,
            upload_id=upload_id,
            expires_at=expiry,
            headers={
                "content-type": content_type,
                "content-length": str(content_length),
                "x-content-sha256": checksum_sha256,
            },
            _contract=_STUDIO_VIDEO_UPLOAD_CONTRACT,
        )

    @staticmethod
    def _write_all(stream: BinaryIO, data: bytes) -> None:
        remaining = memoryview(data)
        while remaining:
            written = stream.write(remaining)
            if type(written) is not int or not 0 < written <= len(remaining):
                raise MediaStorageUnavailable("The private video write did not make progress.")
            remaining = remaining[written:]

    @staticmethod
    def owns(key: str) -> bool:
        return (
            isinstance(key, str)
            and len(key) <= 512
            and bool(_KEY.fullmatch(key))
            and all(
                part not in {"", ".", ".."} and not part.endswith(".") for part in key.split("/")
            )
        )

    def _path(self, key: str) -> Path:
        if not self.owns(key):
            raise MediaStorageUnavailable("The private video object namespace is invalid.")
        return self.root / (hashlib.sha256(key.encode()).hexdigest() + ".object")

    def _resumable_path(self, key: str) -> Path:
        if not self.owns(key):
            raise MediaStorageUnavailable("The private video object namespace is invalid.")
        # A stable name makes a process restart resumable without trusting a
        # client-provided temporary path.  The suffix remains covered by the
        # private-store inventory allowlist.
        return self.root / (
            hashlib.sha256(f"ac-resumable:{key}".encode()).hexdigest()[:32] + ".part"
        )

    @staticmethod
    def _resumable_header(
        *,
        object_key: str,
        content_type: str,
        content_length: int,
        checksum_sha256: str,
        storage_version_id: str,
        uploaded_bytes: int,
    ) -> bytes:
        value = json.dumps(
            {
                "schema": 1,
                "object_key": object_key,
                "content_type": content_type,
                "content_length": content_length,
                "checksum_sha256": checksum_sha256,
                "storage_version_id": storage_version_id,
                "uploaded_bytes": uploaded_bytes,
            },
            separators=(",", ":"),
        ).encode()
        if len(value) >= _HEADER_BYTES:
            raise MediaStorageUnavailable("The resumable video header exceeds its limit.")
        return value.ljust(_HEADER_BYTES - 1, b" ") + b"\n"

    def _read_resumable_header(self, stream: BinaryIO) -> dict[str, object]:
        header = stream.read(_HEADER_BYTES)
        if len(header) != _HEADER_BYTES or not header.endswith(b"\n"):
            raise MediaStorageUnavailable("The resumable video envelope is invalid.")
        try:
            value = json.loads(header)
        except (TypeError, ValueError, UnicodeError):
            raise MediaStorageUnavailable("The resumable video envelope is invalid.") from None
        if not isinstance(value, dict) or value.get("schema") != 1:
            raise MediaStorageUnavailable("The resumable video envelope is invalid.")
        return value

    def _verify_resumable_payload(
        self, stream: BinaryIO, *, content_length: int, checksum_sha256: str
    ) -> None:
        digest = hashlib.sha256()
        remaining = content_length
        stream.seek(_HEADER_BYTES)
        while remaining:
            chunk = stream.read(min(CHUNK_BYTES, remaining))
            if not chunk:
                raise MediaStorageUnavailable("The resumable video payload is truncated.")
            digest.update(chunk)
            remaining -= len(chunk)
        if stream.read(1) != b"" or digest.hexdigest() != checksum_sha256:
            raise MediaStorageUnavailable("The uploaded video checksum does not match.")

    def _check_resumable_inventory(self, size: int) -> None:
        total, count = 0, 0
        for entry in self.root.iterdir():
            _check_path(entry)
            info = entry.lstat()
            if not stat.S_ISREG(info.st_mode):
                raise MediaStorageUnavailable("An unexpected private video entry exists.")
            if entry.name not in {".guard", ".video-store-v1"} and not _ENTRY.fullmatch(entry.name):
                raise MediaStorageUnavailable("An unexpected private video entry exists.")
            if entry.suffix in {".part", ".object"}:
                total += info.st_size
                count += 1
        if count >= self.max_objects or total + size > self.max_store_bytes:
            raise MediaStorageUnavailable(
                "Private video storage is full. Existing videos are preserved."
            )

    def _ensure_resumable_partial(
        self,
        path: Path,
        *,
        object_key: str,
        content_type: str,
        content_length: int,
        checksum_sha256: str,
        storage_version_id: str,
    ) -> None:
        expected = {
            "object_key": object_key,
            "content_type": content_type,
            "content_length": content_length,
            "checksum_sha256": checksum_sha256,
            "storage_version_id": storage_version_id,
        }
        with self._lock(".guard"):
            if path.exists() or path.is_symlink():
                with self._open(path) as stream:
                    header = self._read_resumable_header(stream)
                    if any(header.get(key) != value for key, value in expected.items()):
                        raise MediaConflict("The resumable video identity changed.")
                    if os.fstat(stream.fileno()).st_size != content_length + _HEADER_BYTES:
                        raise MediaStorageUnavailable("The resumable video reservation is invalid.")
                return
            # Counting and creating are one guarded operation. A separate key
            # stripe may not reserve another full envelope between these steps.
            self._check_resumable_inventory(content_length + _HEADER_BYTES)
            created = False
            try:
                with path.open("xb") as stream:
                    created = True
                    stream.truncate(content_length + _HEADER_BYTES)
                    stream.seek(0)
                    self._write_all(
                        stream,
                        self._resumable_header(
                            object_key=object_key,
                            content_type=content_type,
                            content_length=content_length,
                            checksum_sha256=checksum_sha256,
                            storage_version_id=storage_version_id,
                            uploaded_bytes=0,
                        ),
                    )
                    stream.flush()
                    os.fsync(stream.fileno())
            except BaseException as error:
                if created:
                    try:
                        _check_path(path)
                        path.unlink(missing_ok=True)
                    except Exception:
                        error.add_note("An incomplete private video reservation remains charged.")
                raise

    @contextmanager
    def _lock(self, name: str) -> Iterator[None]:
        path = self.root / name
        handle = None
        locked = False
        try:
            _check_path(self.root)
            if path.exists() or path.is_symlink():
                _check_path(path)
            fd = os.open(
                path,
                os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0),
                0o600,
            )
            try:
                handle = os.fdopen(fd, "r+b", buffering=0)
            except BaseException:
                os.close(fd)
                raise
            if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
                raise MediaStorageUnavailable("The private video lock is invalid.")
            deadline = time.monotonic() + (_GUARD_WAIT_SECONDS if name == ".guard" else 0)
            while True:
                try:
                    if sys.platform == "win32":
                        import msvcrt

                        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                    else:
                        import fcntl

                        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except OSError as error:
                    if error.errno not in {errno.EACCES, errno.EAGAIN, errno.EDEADLK}:
                        raise
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise MediaConflict(
                            "This private video operation is busy. Retry shortly."
                        ) from None
                    time.sleep(min(_GUARD_RETRY_SECONDS, remaining))
            locked = True
            yield
        except BlockingIOError:
            raise MediaConflict("This private video operation is busy. Retry shortly.") from None
        except OSError:
            raise MediaStorageUnavailable(
                "Private video storage is temporarily unavailable."
            ) from None
        finally:
            if handle is not None:
                try:
                    if locked:
                        if sys.platform == "win32":
                            import msvcrt

                            handle.seek(0)
                            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                        else:
                            import fcntl

                            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
                finally:
                    handle.close()

    def _reserve(self, size: int) -> Path:
        with self._lock(".guard"):
            total, count = 0, 0
            for entry in self.root.iterdir():
                _check_path(entry)
                info = entry.lstat()
                if not stat.S_ISREG(info.st_mode):
                    raise MediaStorageUnavailable("An unexpected private video entry exists.")
                if entry.name not in {".guard", ".video-store-v1"} and not _ENTRY.fullmatch(
                    entry.name
                ):
                    raise MediaStorageUnavailable("An unexpected private video entry exists.")
                if entry.suffix in {".part", ".object"}:
                    total += info.st_size
                    count += 1
            if count >= self.max_objects or total + size > self.max_store_bytes:
                raise MediaStorageUnavailable(
                    "Private video storage is full. Existing videos are preserved."
                )
            partial = self.root / f"{uuid4().hex}.part"
            created = False
            try:
                with partial.open("xb") as stream:
                    created = True
                    stream.truncate(size)
            except BaseException as error:
                # _reserve has not returned this path to put_stream yet, so
                # it owns cleanup even when truncate/close fails. Never remove
                # a pre-existing path if exclusive creation itself failed.
                if created:
                    try:
                        _check_path(partial)
                        partial.unlink(missing_ok=True)
                    except Exception:
                        error.add_note("An incomplete private video reservation remains charged.")
                raise
            return partial

    @staticmethod
    def _check_stream(stream: BinaryIO, identity: tuple[int, int, int, int, int]) -> None:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or _identity(info) != identity:
            raise MediaStorageUnavailable("The private video object changed during reading.")

    @contextmanager
    def _open(self, path: Path) -> Iterator[BinaryIO]:
        try:
            _check_path(path)
            before = path.lstat()
            fd = os.open(
                path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
            )
            try:
                stream = os.fdopen(fd, "rb", buffering=0)
            except BaseException:
                os.close(fd)
                raise
            with stream:
                self._check_stream(stream, _identity(before))
                yield stream
        except OSError:
            raise MediaStorageUnavailable("The private video object is unavailable.") from None

    @contextmanager
    def _open_writable(self, path: Path) -> Iterator[BinaryIO]:
        """Open a trusted regular file without following a replacement link."""
        try:
            _check_path(path)
            before = path.lstat()
            fd = os.open(
                path,
                os.O_RDWR | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0),
            )
            try:
                stream = os.fdopen(fd, "r+b", buffering=0)
            except BaseException:
                os.close(fd)
                raise
            with stream:
                self._check_stream(stream, _identity(before))
                yield stream
        except OSError:
            raise MediaStorageUnavailable("The private video object is unavailable.") from None

    def _inspect(self, key: str) -> _Object | None:
        path = self._path(key)
        if not path.exists() and not path.is_symlink():
            return None
        with self._open(path) as stream:
            identity = _identity(os.fstat(stream.fileno()))
            try:
                header = stream.read(_HEADER_BYTES)
                if len(header) != _HEADER_BYTES or not header.endswith(b"\n"):
                    raise ValueError
                metadata = StoredObjectMetadata(**json.loads(header))
                if (
                    metadata.object_key != key
                    or not isinstance(metadata.content_type, str)
                    or metadata.content_type not in _TYPES
                    or type(metadata.content_length) is not int
                    or not 1 <= metadata.content_length <= self.max_object_bytes
                    or not isinstance(metadata.checksum_sha256, str)
                    or not _HASH.fullmatch(metadata.checksum_sha256)
                    or not isinstance(metadata.storage_version_id, str)
                    or not _HASH.fullmatch(metadata.storage_version_id)
                    or identity[2] != metadata.content_length + _HEADER_BYTES
                ):
                    raise ValueError
            except (ValueError, TypeError, UnicodeError):
                raise MediaStorageUnavailable("The private video envelope is invalid.") from None
            digest = hashlib.sha256()
            while chunk := stream.read(CHUNK_BYTES):
                self._check_stream(stream, identity)
                digest.update(chunk)
            self._check_stream(stream, identity)
            if digest.hexdigest() != metadata.checksum_sha256:
                raise MediaStorageUnavailable("The private video checksum does not match.")
            return _Object(metadata, identity)

    def head(self, object_key: str) -> StoredObjectMetadata | None:
        item = self._inspect(object_key)
        return item.metadata if item else None

    def _validate_verification(self, lease: ActiveVideoObjectVerification) -> None:
        if (
            type(lease) is not ActiveVideoObjectVerification
            or lease._seal is not _VERIFICATION_SEAL
            or lease._storage is not self
            or not lease.active
        ):
            raise MediaStorageUnavailable("The private video verification is invalid.")
        path = self._path(lease.metadata.object_key)
        with self._open(path) as stream:
            identity = _identity(os.fstat(stream.fileno()))
            try:
                header = stream.read(_HEADER_BYTES)
                metadata = StoredObjectMetadata(**json.loads(header))
            except (ValueError, TypeError, UnicodeError):
                raise MediaStorageUnavailable("The private video envelope is invalid.") from None
            if identity != lease._identity or metadata != lease.metadata:
                raise MediaConflict("The verified private video object changed.")
            try:
                if _identity(path.lstat()) != lease._identity:
                    raise MediaConflict("The verified private video object changed.")
            except OSError:
                raise MediaStorageUnavailable("The private video object is unavailable.") from None

    @contextmanager
    def hold_verification(self, object_key: str) -> Iterator[ActiveVideoObjectVerification]:
        """Hash once under the writer stripe and retain it through a short commit.

        This does not trust stat identity as byte integrity. The complete hash is
        computed only after the adapter's write/delete lock is acquired, and that
        same lock remains held until the caller's commit has finished. The final
        bounded identity/envelope check detects non-cooperating replacement; the
        store's documented trusted-directory requirement remains unchanged.
        """

        path = self._path(object_key)
        with self._lock(path.stem[:2] + ".lock"):
            item = self._inspect(object_key)
            if item is None:
                raise MediaStorageUnavailable("The private video object is unavailable.")
            lease = ActiveVideoObjectVerification(
                item.metadata,
                self,
                item.identity,
                _VERIFICATION_SEAL,
            )
            try:
                yield lease
                self._validate_verification(lease)
            finally:
                lease.active = False

    @contextmanager
    def hold_verifications(
        self, object_keys: tuple[str, ...]
    ) -> Iterator[tuple[ActiveVideoObjectVerification, ...]]:
        """Hold writer stripes while verifying a bounded set of immutable objects.

        Every stripe is acquired before any object is inspected or hashed. The
        context is synchronous by design: callers that bridge an async worker
        must enter and exit it on the same worker thread because OS file-lock
        handles are not portable across threads.
        """

        if type(object_keys) is not tuple or not 1 <= len(object_keys) <= 4096:
            raise MediaStorageUnavailable(
                "The private video verification batch must contain one to 4096 keys."
            )
        if any(type(object_key) is not str or not object_key for object_key in object_keys):
            raise MediaStorageUnavailable("The private video verification keys are invalid.")
        if len(set(object_keys)) != len(object_keys):
            raise MediaStorageUnavailable(
                "The private video verification batch cannot contain duplicate keys."
            )

        # Validate every key and derive its stripe before taking any lock. This
        # makes malformed input and partial acquisition failures side-effect free.
        paths = tuple(self._path(object_key) for object_key in object_keys)
        lock_names = tuple(sorted({f"{path.stem[:2]}.lock" for path in paths}))
        locks: list[AbstractContextManager[None]] = [self._lock(name) for name in lock_names]
        entered: list[AbstractContextManager[None]] = []
        leases: list[ActiveVideoObjectVerification] = []
        body_error: BaseException | None = None
        validation_error: BaseException | None = None
        release_error: BaseException | None = None
        try:
            for lock in locks:
                lock.__enter__()
                entered.append(lock)

            # All writer stripes are held before the first full envelope/hash
            # inspection. Preserve the caller's key order in the lease tuple.
            objects: list[_Object] = []
            for object_key in object_keys:
                item = self._inspect(object_key)
                if item is None:
                    raise MediaStorageUnavailable("The private video object is unavailable.")
                objects.append(item)
            leases = [
                ActiveVideoObjectVerification(
                    item.metadata,
                    self,
                    item.identity,
                    _VERIFICATION_SEAL,
                )
                for item in objects
            ]
            try:
                yield tuple(leases)
            except BaseException as error:
                body_error = error
                raise
            finally:
                # Validate every lease even when an earlier validation fails;
                # invalidation below must cover the complete batch.
                for lease in leases:
                    try:
                        self._validate_verification(lease)
                    except BaseException as error:
                        if validation_error is None:
                            validation_error = error
                for lease in leases:
                    lease.active = False
                if body_error is None and validation_error is not None:
                    raise validation_error
        finally:
            # Release all acquired locks even if one close path fails. The
            # context manager itself does not suppress body exceptions.
            for lock in reversed(entered):
                try:
                    lock.__exit__(None, None, None)
                except BaseException as error:
                    if release_error is None:
                        release_error = error
            if body_error is None and validation_error is None and release_error is not None:
                raise release_error

    def require_verification(
        self,
        lease: ActiveVideoObjectVerification,
        *,
        object_key: str,
    ) -> StoredObjectMetadata:
        """Resolve metadata only from an exact currently held storage guard."""

        if (
            type(lease) is not ActiveVideoObjectVerification
            or lease._seal is not _VERIFICATION_SEAL
            or lease._storage is not self
            or not lease.active
            or lease.metadata.object_key != object_key
        ):
            raise MediaStorageUnavailable("The private video verification is not active.")
        return lease.metadata

    def put_stream(
        self,
        *,
        object_key: str,
        chunks: Iterable[bytes],
        content_type: str,
        content_length: int,
        checksum_sha256: str,
        storage_version_id: str | None = None,
        before_publish: Callable[[], None] | None = None,
        create_only: bool = False,
    ) -> StoredObjectMetadata:
        path = self._path(object_key)
        if (
            not isinstance(content_type, str)
            or content_type not in _TYPES
            or type(content_length) is not int
            or not 1 <= content_length <= self.max_object_bytes
            or not isinstance(checksum_sha256, str)
            or not _HASH.fullmatch(checksum_sha256)
            or storage_version_id is not None
            and (not isinstance(storage_version_id, str) or not _HASH.fullmatch(storage_version_id))
            or type(create_only) is not bool
        ):
            raise MediaStorageUnavailable("The private video write contract is invalid.")
        version = (
            storage_version_id
            or hashlib.sha256(f"{object_key}:{content_type}:{checksum_sha256}".encode()).hexdigest()
        )
        expected = StoredObjectMetadata(
            object_key, content_type, content_length, checksum_sha256, version
        )
        partial = None
        with self._lock(path.stem[:2] + ".lock"):
            existing = self.head(object_key)
            if existing:
                if create_only:
                    raise MediaConflict("The private video destination already exists.")
                if existing != expected:
                    raise MediaConflict("Video bytes are immutable. Create a new version.")
                if before_publish is not None:
                    before_publish()
                return existing
            try:
                partial = self._reserve(content_length + _HEADER_BYTES)
                digest, written = hashlib.sha256(), 0
                with partial.open("r+b", buffering=0) as stream:
                    stream.seek(_HEADER_BYTES)
                    for chunk in chunks:
                        if not isinstance(chunk, bytes) or not 0 < len(chunk) <= CHUNK_BYTES:
                            raise MediaStorageUnavailable("Supply bounded nonempty video chunks.")
                        written += len(chunk)
                        if written > content_length:
                            raise MediaStorageUnavailable(
                                "The private video exceeds its declared length."
                            )
                        digest.update(chunk)
                        self._write_all(stream, chunk)
                    if written != content_length or digest.hexdigest() != checksum_sha256:
                        raise MediaStorageUnavailable(
                            "The uploaded video length or checksum does not match."
                        )
                    header = json.dumps(asdict(expected), separators=(",", ":")).encode()
                    if len(header) >= _HEADER_BYTES:
                        raise MediaStorageUnavailable("The private video header exceeds its limit.")
                    stream.seek(0)
                    self._write_all(stream, header.ljust(_HEADER_BYTES - 1, b" ") + b"\n")
                    stream.flush()
                    os.fsync(stream.fileno())
                # Recheck caller authority after the network transfer, without
                # holding a database transaction while waiting for file bytes.
                # This publishes private bytes only, never a playable lesson.
                if before_publish is not None:
                    before_publish()
                # Hold the same inventory guard used by quota scans. They must
                # see neither the temporary hard-link overlap nor a disappearing
                # reservation. A crash overlap stays charged for explicit repair.
                with self._lock(".guard"):
                    os.link(partial, path)
                    partial.unlink()
                    partial = None
                return expected
            except FileExistsError:
                raise MediaConflict("The private video destination already exists.") from None
            except OSError:
                raise MediaStorageUnavailable("The private video could not be stored.") from None
            finally:
                if partial is not None:
                    original_error = sys.exception()
                    try:
                        with self._lock(".guard"):
                            _check_path(partial)
                            partial.unlink(missing_ok=True)
                    except Exception:
                        # Keep the known .part charged if cleanup cannot run;
                        # never mask a failed upload with a cleanup-lock error.
                        if original_error is None:
                            raise MediaStorageUnavailable(
                                "An incomplete private video reservation remains charged."
                            ) from None
                        original_error.add_note(
                            "An incomplete private video reservation remains charged."
                        )

    def put_resumable_chunk(
        self,
        *,
        object_key: str,
        body: bytes,
        content_type: str,
        content_length: int,
        checksum_sha256: str,
        offset: int,
        chunk_checksum_sha256: str,
        storage_version_id: str | None = None,
        before_publish: Callable[[], None] | None = None,
    ) -> ResumableUploadResult:
        """Append one bounded, replay-safe browser chunk.

        The partial file is reserved at its complete envelope size before the
        first byte is accepted.  Its fixed header records the admitted source
        identity and written offset, while the final immutable object is only
        made visible after the complete source hash and the caller's fresh
        authority callback both succeed.
        """
        path = self._path(object_key)
        if (
            not isinstance(content_type, str)
            or content_type not in _TYPES
            or type(content_length) is not int
            or not 1 <= content_length <= self.max_object_bytes
            or not isinstance(checksum_sha256, str)
            or not _HASH.fullmatch(checksum_sha256)
            or type(offset) is not int
            or not 0 <= offset <= content_length
            or not isinstance(body, bytes)
            or not 0 < len(body) <= RESUMABLE_CHUNK_BYTES
            or offset + len(body) > content_length
            or not isinstance(chunk_checksum_sha256, str)
            or not _HASH.fullmatch(chunk_checksum_sha256)
            or hashlib.sha256(body).hexdigest() != chunk_checksum_sha256
            or storage_version_id is not None
            and (not isinstance(storage_version_id, str) or not _HASH.fullmatch(storage_version_id))
        ):
            raise MediaStorageUnavailable("The resumable video chunk contract is invalid.")
        version = (
            storage_version_id
            or hashlib.sha256(f"{object_key}:{content_type}:{checksum_sha256}".encode()).hexdigest()
        )
        expected = StoredObjectMetadata(
            object_key, content_type, content_length, checksum_sha256, version
        )
        with self._lock(path.stem[:2] + ".lock"):
            existing = self.head(object_key)
            if existing is not None:
                if existing != expected:
                    raise MediaConflict("Video bytes are immutable. Create a new version.")
                if offset + len(body) > content_length:
                    raise MediaConflict("The resumable video retry exceeds its source.")
                with self._open(path) as stream:
                    stream.seek(_HEADER_BYTES + offset)
                    if stream.read(len(body)) != body:
                        raise MediaConflict("The resumable video retry does not match its bytes.")
                if before_publish is not None:
                    before_publish()
                return ResumableUploadResult(content_length, existing)
            partial = self._resumable_path(object_key)
            self._ensure_resumable_partial(
                partial,
                object_key=object_key,
                content_type=content_type,
                content_length=content_length,
                checksum_sha256=checksum_sha256,
                storage_version_id=version,
            )
            with self._open_writable(partial) as stream:
                header = self._read_resumable_header(stream)
                written = header.get("uploaded_bytes")
                if type(written) is not int or not 0 <= written <= content_length:
                    raise MediaStorageUnavailable("The resumable video offset is invalid.")
                if offset > written:
                    raise MediaConflict("The resumable video has a gap before this chunk.")
                if offset < written:
                    if offset + len(body) > written:
                        raise MediaConflict(
                            "The resumable video chunk overlaps its current offset."
                        )
                    stream.seek(_HEADER_BYTES + offset)
                    already = stream.read(len(body))
                    if already != body:
                        raise MediaConflict("The resumable video retry does not match its bytes.")
                    if written == content_length:
                        self._verify_resumable_payload(
                            stream,
                            content_length=content_length,
                            checksum_sha256=checksum_sha256,
                        )
                        if before_publish is not None:
                            before_publish()
                        with self._lock(".guard"):
                            stream.seek(0)
                            self._write_all(
                                stream,
                                json.dumps(asdict(expected), separators=(",", ":"))
                                .encode()
                                .ljust(_HEADER_BYTES - 1, b" ")
                                + b"\n",
                            )
                            stream.flush()
                            os.fsync(stream.fileno())
                            stream.close()
                            os.link(partial, path)
                            partial.unlink()
                        return ResumableUploadResult(content_length, expected)
                    return ResumableUploadResult(written)
                stream.seek(_HEADER_BYTES + written)
                self._write_all(stream, body)
                written += len(body)
                stream.seek(0)
                self._write_all(
                    stream,
                    self._resumable_header(
                        object_key=object_key,
                        content_type=content_type,
                        content_length=content_length,
                        checksum_sha256=checksum_sha256,
                        storage_version_id=version,
                        uploaded_bytes=written,
                    ),
                )
                stream.flush()
                os.fsync(stream.fileno())
                if written != content_length:
                    return ResumableUploadResult(written)
                self._verify_resumable_payload(
                    stream,
                    content_length=content_length,
                    checksum_sha256=checksum_sha256,
                )
                if before_publish is not None:
                    before_publish()
                with self._lock(".guard"):
                    stream.seek(0)
                    self._write_all(
                        stream,
                        json.dumps(asdict(expected), separators=(",", ":"))
                        .encode()
                        .ljust(_HEADER_BYTES - 1, b" ")
                        + b"\n",
                    )
                    stream.flush()
                    os.fsync(stream.fileno())
                    stream.close()
                    os.link(partial, path)
                    partial.unlink()
                return ResumableUploadResult(content_length, expected)

    def put(
        self,
        *,
        object_key: str,
        body: bytes,
        content_type: str,
        storage_version_id: str | None = None,
        create_only: bool = False,
    ) -> StoredObjectMetadata:
        if type(create_only) is not bool:
            raise MediaStorageUnavailable("The private video write contract is invalid.")
        if not isinstance(body, bytes):
            raise MediaStorageUnavailable("The private video body must be bytes.")
        return self.put_stream(
            object_key=object_key,
            chunks=(body[i : i + CHUNK_BYTES] for i in range(0, len(body), CHUNK_BYTES)),
            content_type=content_type,
            content_length=len(body),
            checksum_sha256=hashlib.sha256(body).hexdigest(),
            storage_version_id=storage_version_id,
            create_only=create_only,
        )

    def iter_range(
        self,
        object_key: str,
        *,
        start: int = 0,
        end: int | None = None,
        chunk_size: int = CHUNK_BYTES,
    ) -> Iterator[bytes]:
        item = self._inspect(object_key)
        if item is None:
            raise MediaStorageUnavailable("The private video object is unavailable.")
        final = item.metadata.content_length - 1 if end is None else end
        if (
            type(start) is not int
            or type(final) is not int
            or not 0 <= start <= final < item.metadata.content_length
            or type(chunk_size) is not int
            or not 1 <= chunk_size <= CHUNK_BYTES
        ):
            raise MediaStorageUnavailable("The private video range is invalid.")
        with self._open(self._path(object_key)) as stream:
            self._check_stream(stream, item.identity)
            stream.seek(_HEADER_BYTES + start)
            remaining = final - start + 1
            while remaining:
                self._check_stream(stream, item.identity)
                chunk = stream.read(min(remaining, chunk_size))
                self._check_stream(stream, item.identity)
                if not chunk:
                    raise MediaStorageUnavailable("The private video object is truncated.")
                remaining -= len(chunk)
                yield chunk

    def read_prefix(self, object_key: str, *, max_bytes: int = 512) -> bytes:
        if type(max_bytes) is not int or not 1 <= max_bytes <= CHUNK_BYTES + 1:
            raise MediaStorageUnavailable("The private video read exceeds its limit.")
        item = self._inspect(object_key)
        if item is None:
            raise MediaStorageUnavailable("The private video object is unavailable.")
        return b"".join(
            self.iter_range(object_key, end=min(max_bytes, item.metadata.content_length) - 1)
        )

    def read(self, object_key: str) -> bytes:
        item = self._inspect(object_key)
        if item is None or item.metadata.content_length > CHUNK_BYTES:
            raise MediaStorageUnavailable("Use bounded streaming for this private video.")
        return self.read_prefix(object_key, max_bytes=item.metadata.content_length)

    def copy(
        self,
        *,
        source_key: str,
        destination_key: str,
        content_type: str,
        create_only: bool = False,
    ) -> StoredObjectMetadata:
        if type(create_only) is not bool:
            raise MediaStorageUnavailable("The private video copy contract is invalid.")
        source = self.head(source_key)
        if source is None:
            raise MediaStorageUnavailable("The private video source is unavailable.")
        return self.put_stream(
            object_key=destination_key,
            chunks=self.iter_range(source_key),
            content_type=content_type,
            content_length=source.content_length,
            checksum_sha256=source.checksum_sha256,
            create_only=create_only,
        )

    def delete(self, object_key: str) -> None:
        """Delete one immutable object and its exact resumable reservation.

        Partial reservations are deliberately absent from ``list_prefix`` and
        every read/head path.  Lifecycle deletion already has the admitted
        object key, so it can retire a crashed or expired reservation without
        exposing incomplete bytes as a media object.
        """
        path = self._path(object_key)
        partial = self._resumable_path(object_key)
        with self._lock(path.stem[:2] + ".lock"), self._lock(".guard"):
            if self._inspect(object_key) is not None:
                path.unlink()
            if partial.exists() or partial.is_symlink():
                with self._open(partial) as stream:
                    header = self._read_resumable_header(stream)
                    if header.get("object_key") != object_key:
                        raise MediaStorageUnavailable(
                            "The resumable video reservation is out of scope."
                        )
                _check_path(partial)
                partial.unlink()

    def list_prefix(self, prefix: str) -> tuple[str, ...]:
        if not isinstance(prefix, str) or not self.owns(prefix.rstrip("/")):
            return ()
        normalized, keys = prefix.rstrip("/"), []
        for path in self.root.glob("*.object"):
            with self._open(path) as stream:
                try:
                    key = json.loads(stream.read(_HEADER_BYTES))["object_key"]
                    if not self.owns(key) or self._path(key) != path:
                        raise ValueError
                except (ValueError, KeyError, TypeError, UnicodeError):
                    raise MediaStorageUnavailable(
                        "The private video inventory is invalid."
                    ) from None
            if key == normalized or key.startswith(normalized + "/"):
                self._inspect(key)
                keys.append(key)
        return tuple(sorted(keys))
