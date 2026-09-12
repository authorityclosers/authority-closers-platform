"""Private local object transport for an explicitly configured internal worker.

This adapter does not activate public uploads or satisfy the existing R2/storage gate.
Tenant authorization and retention/deletion orchestration remain domain responsibilities.
"""

from __future__ import annotations

import ctypes
import hashlib
import hmac
import os
import re
import stat
from collections.abc import Iterable, Iterator
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any, Protocol
from uuid import UUID, uuid4

MAX_OBJECT_BYTES = 128 * 1024 * 1024
CHUNK_BYTES = 1024 * 1024
_MARKER = b"ac.private-local-recording-storage/1\n"
_MARKER_NAME = ".ac-recording-storage"
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_REPARSE_POINT = 0x400
_O_NOFOLLOW = int(getattr(os, "O_NOFOLLOW", 0))
_O_DIRECTORY = int(getattr(os, "O_DIRECTORY", 0))
_O_BINARY = int(getattr(os, "O_BINARY", 0))


class StorageError(ValueError):
    """Stable sanitized failure; never includes object bytes or filesystem paths."""


class ObjectKind(StrEnum):
    SOURCE_AUDIO = "source-audio"
    SIGNAL_FEATURES = "signal-features"
    SIGNAL_CHECKPOINT = "signal-checkpoint"
    TRANSCRIPT = "transcript"
    REPORT = "report"


@dataclass(frozen=True, slots=True)
class ObjectKey:
    tenant_id: UUID
    recording_id: UUID
    blob_id: UUID
    kind: ObjectKind

    def __post_init__(self) -> None:
        if any(
            type(value) is not UUID
            for value in (
                self.tenant_id,
                self.recording_id,
                self.blob_id,
            )
        ) or not isinstance(self.kind, ObjectKind):
            raise StorageError("storage_server_key_required")

    @property
    def directories(self) -> tuple[str, str, str]:
        return self.tenant_id.hex, self.recording_id.hex, self.kind.value

    @property
    def filename(self) -> str:
        return self.blob_id.hex + ".blob"


@dataclass(frozen=True, slots=True)
class StoredObject:
    key: ObjectKey
    sha256: str
    size_bytes: int
    transport: str = "private-local/1"


@dataclass(frozen=True, slots=True)
class RecordingDeletionReceipt:
    tenant_id: UUID
    recording_id: UUID
    deleted_count: int
    already_absent_count: int
    local_inventory_empty: bool
    domain_generation_fence_verified: bool = False


class RecordingObjectStorage(Protocol):
    def put(
        self,
        key: ObjectKey,
        chunks: Iterable[bytes],
        *,
        expected_sha256: str,
        expected_bytes: int | None = None,
    ) -> StoredObject: ...

    def iter_bytes(self, key: ObjectKey, *, expected_sha256: str) -> Iterator[bytes]: ...

    def delete(self, key: ObjectKey) -> bool: ...

    def list_recording(self, tenant_id: UUID, recording_id: UUID) -> tuple[ObjectKey, ...]: ...

    def delete_recording(
        self,
        tenant_id: UUID,
        recording_id: UUID,
        *,
        expected_keys: tuple[ObjectKey, ...],
    ) -> RecordingDeletionReceipt: ...


def _validate_digest(value: str) -> None:
    if not isinstance(value, str) or not _SHA256.fullmatch(value):
        raise StorageError("storage_sha256_required")


def _validate_entry(info: os.stat_result, *, directory: bool = False) -> None:
    check = stat.S_ISDIR if directory else stat.S_ISREG
    if (
        not check(info.st_mode)
        or getattr(info, "st_file_attributes", 0) & _REPARSE_POINT
        or (not directory and info.st_nlink != 1)
    ):
        raise StorageError("storage_unsafe_filesystem_entry")


def _windows_apis() -> tuple[Any, Any]:
    # Loaded only on Windows; no shell, environment dump, key store or credentials lookup.
    from ctypes import wintypes

    loader = getattr(ctypes, "WinDLL", None)
    if loader is None:
        raise StorageError("storage_windows_api_unavailable")
    kernel = loader("kernel32", use_last_error=True)
    security = loader("advapi32", use_last_error=True)
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.LocalFree.argtypes = [wintypes.HLOCAL]
    kernel.LocalFree.restype = wintypes.HLOCAL
    kernel.CreateFileW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.c_void_p,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.GetFileInformationByHandleEx.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        ctypes.c_void_p,
        wintypes.DWORD,
    ]
    security.OpenProcessToken.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.HANDLE),
    ]
    security.GetTokenInformation.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
    ]
    security.ConvertSidToStringSidW.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.LPWSTR)]
    security.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(wintypes.DWORD),
    ]
    security.SetFileSecurityW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, ctypes.c_void_p]
    return kernel, security


def _restrict_directory(path: Path) -> None:
    if os.name != "nt":
        os.chmod(path, 0o700, follow_symlinks=False)
        return
    from ctypes import wintypes

    kernel, security = _windows_apis()
    token = wintypes.HANDLE()
    sid_text = wintypes.LPWSTR()
    descriptor = ctypes.c_void_p()
    try:
        if not security.OpenProcessToken(kernel.GetCurrentProcess(), 0x0008, ctypes.byref(token)):
            raise StorageError("storage_private_acl_unavailable")
        required = wintypes.DWORD()
        security.GetTokenInformation(token, 1, None, 0, ctypes.byref(required))
        if not 0 < required.value <= 65536:
            raise StorageError("storage_private_acl_unavailable")
        buffer = ctypes.create_string_buffer(required.value)
        if not security.GetTokenInformation(token, 1, buffer, required, ctypes.byref(required)):
            raise StorageError("storage_private_acl_unavailable")
        sid_pointer = ctypes.cast(buffer, ctypes.POINTER(ctypes.c_void_p))[0]
        if not security.ConvertSidToStringSidW(sid_pointer, ctypes.byref(sid_text)):
            raise StorageError("storage_private_acl_unavailable")
        # Protected inheritable DACL: this Windows user, SYSTEM, and local administrators.
        sddl = f"D:P(A;OICI;FA;;;{sid_text.value})(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)"
        if not security.ConvertStringSecurityDescriptorToSecurityDescriptorW(
            sddl,
            1,
            ctypes.byref(descriptor),
            None,
        ) or not security.SetFileSecurityW(str(path), 0x80000004, descriptor):
            raise StorageError("storage_private_acl_unavailable")
    finally:
        if descriptor:
            kernel.LocalFree(descriptor)
        if sid_text:
            kernel.LocalFree(ctypes.cast(sid_text, ctypes.c_void_p))
        if token:
            kernel.CloseHandle(token)


def _windows_open(path: Path, *, directory: bool) -> int:
    from ctypes import wintypes

    kernel, _ = _windows_apis()
    access = 0x80 if directory else 0x80000000  # FILE_READ_ATTRIBUTES / GENERIC_READ
    # Directory handles pin ancestors against rename/delete. File readers deny write/delete.
    share = 0x3 if directory else 0x1
    flags = 0x00200000 | (0x02000000 if directory else 0)  # OPEN_REPARSE_POINT, BACKUP_SEMANTICS
    handle = kernel.CreateFileW(str(path), access, share, None, 3, flags, None)
    if handle == ctypes.c_void_p(-1).value:
        read_error = getattr(ctypes, "get_last_error", None)
        if read_error is None:
            raise StorageError("storage_windows_api_unavailable")
        error = int(read_error())
        if error in (2, 3):
            raise FileNotFoundError
        raise StorageError("storage_entry_unavailable")
    attributes = (wintypes.DWORD * 2)()
    if (
        not kernel.GetFileInformationByHandleEx(handle, 9, attributes, ctypes.sizeof(attributes))
        or attributes[0] & _REPARSE_POINT
        or bool(attributes[0] & 0x10) != directory
    ):
        kernel.CloseHandle(handle)
        raise StorageError("storage_unsafe_filesystem_entry")
    return int(handle)


@dataclass
class _Directory:
    path: Path
    descriptor: int | None

    def names(self) -> list[str]:
        return sorted(os.listdir(self.descriptor if self.descriptor is not None else self.path))

    def mkdir(self, name: str) -> None:
        if self.descriptor is not None:
            os.mkdir(name, 0o700, dir_fd=self.descriptor)
        else:
            (self.path / name).mkdir(mode=0o700)

    def rmdir(self, name: str) -> None:
        if self.descriptor is not None:
            os.rmdir(name, dir_fd=self.descriptor)
        else:
            (self.path / name).rmdir()

    def open(self, name: str, flags: int, mode: int = 0o600) -> int:
        if self.descriptor is not None:
            return os.open(name, flags | _O_NOFOLLOW, mode, dir_fd=self.descriptor)
        if flags == os.O_RDONLY:
            import msvcrt

            handle = _windows_open(self.path / name, directory=False)
            try:
                opener = getattr(msvcrt, "open_osfhandle", None)
                if opener is None:
                    raise StorageError("storage_windows_api_unavailable")
                return int(opener(handle, os.O_RDONLY | _O_BINARY))
            except BaseException:
                kernel, _ = _windows_apis()
                kernel.CloseHandle(handle)
                raise
        return os.open(self.path / name, flags | _O_BINARY, mode)

    def unlink(self, name: str) -> None:
        if self.descriptor is not None:
            os.unlink(name, dir_fd=self.descriptor)
        else:
            (self.path / name).unlink()

    def stat(self, name: str) -> os.stat_result:
        if self.descriptor is not None:
            return os.stat(name, dir_fd=self.descriptor, follow_symlinks=False)
        return (self.path / name).lstat()

    def publish(self, temporary: str, name: str) -> None:
        # Hard-link creation is atomic and fails if the destination already exists.
        # Filesystems without local hard-link support fail closed; no unsafe rename fallback.
        if self.descriptor is not None:
            os.link(
                temporary,
                name,
                src_dir_fd=self.descriptor,
                dst_dir_fd=self.descriptor,
                follow_symlinks=False,
            )
        else:
            os.link(self.path / temporary, self.path / name, follow_symlinks=False)


@contextmanager
def _directory(path: Path, *, create_under: Path | None = None) -> Iterator[_Directory]:
    """Walk with pinned handles/openat; no ancestor symlink or reparse traversal."""
    descriptor: int | None = None
    handles: list[int] = []
    current = Path(path.anchor)
    try:
        if os.name == "nt":
            handles.append(_windows_open(current, directory=True))
        else:
            if not _O_DIRECTORY or not _O_NOFOLLOW:
                raise StorageError("storage_required_nofollow_unavailable")
            descriptor = os.open(current, os.O_RDONLY | _O_DIRECTORY | _O_NOFOLLOW)
        for name in path.parts[1:]:
            current = current / name
            create = (
                create_under is not None
                and current != create_under
                and current.is_relative_to(create_under)
            )
            if descriptor is not None:
                if create:
                    with suppress(FileExistsError):
                        os.mkdir(name, 0o700, dir_fd=descriptor)
                next_descriptor = os.open(
                    name, os.O_RDONLY | _O_DIRECTORY | _O_NOFOLLOW, dir_fd=descriptor
                )
                os.close(descriptor)
                descriptor = next_descriptor
            else:
                if create:
                    with suppress(FileExistsError):
                        current.mkdir(mode=0o700)
                handles.append(_windows_open(current, directory=True))
        yield _Directory(path, descriptor)
    except OSError as error:
        if isinstance(error, FileNotFoundError):
            raise
        raise StorageError("storage_filesystem_operation_failed") from None
    finally:
        if descriptor is not None:
            os.close(descriptor)
        if handles:
            kernel, _ = _windows_apis()
            for handle in reversed(handles):
                kernel.CloseHandle(handle)


class PrivateLocalRecordingStorage:
    """Object transport for server-created keys, with an explicit private local root.

    Constructor accepts a new root or a previously initialized marked root. Existing
    unrelated directories are rejected. Never select root or ObjectKey from a URL/path.
    """

    def __init__(self, root: Path, *, max_bytes: int = MAX_OBJECT_BYTES) -> None:
        if (
            not root.is_absolute()
            or ".." in root.parts
            or len(root.parts) < 3
            or type(max_bytes) is not int
            or not 0 < max_bytes <= MAX_OBJECT_BYTES
        ):
            raise StorageError("storage_invalid_configuration")
        repository = Path(__file__).resolve().parents[4]
        if root.is_relative_to(repository) or any(
            (parent / ".git").exists() for parent in (root, *root.parents)
        ):
            raise StorageError("storage_root_must_be_outside_repository")
        self.root = root
        self.max_bytes = max_bytes
        created = False
        # Parent must already exist. Only this explicitly configured root is created.
        with _directory(root.parent) as parent:
            try:
                parent.mkdir(root.name)
                created = True
            except FileExistsError:
                pass
            try:
                with _directory(root) as directory:
                    if not created:
                        try:
                            descriptor = directory.open(_MARKER_NAME, os.O_RDONLY)
                        except FileNotFoundError:
                            raise StorageError("storage_root_not_owned") from None
                        with os.fdopen(descriptor, "rb") as marker:
                            _validate_entry(os.fstat(marker.fileno()))
                            if marker.read(len(_MARKER) + 1) != _MARKER:
                                raise StorageError("storage_root_not_owned")
                    if directory.descriptor is not None:
                        os.chmod(directory.descriptor, 0o700)
                    else:
                        _restrict_directory(root)
                    if created:
                        descriptor = directory.open(
                            _MARKER_NAME,
                            os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                        )
                        with os.fdopen(descriptor, "wb") as marker:
                            marker.write(_MARKER)
                            marker.flush()
                            os.fsync(marker.fileno())
            except BaseException:
                if created:
                    with _directory(root) as cleanup, suppress(FileNotFoundError):
                        cleanup.unlink(_MARKER_NAME)
                    parent.rmdir(root.name)
                raise

    def _path(self, key: ObjectKey) -> Path:
        if not isinstance(key, ObjectKey):
            raise StorageError("storage_server_key_required")
        return self.root.joinpath(*key.directories)

    def put(
        self,
        key: ObjectKey,
        chunks: Iterable[bytes],
        *,
        expected_sha256: str,
        expected_bytes: int | None = None,
    ) -> StoredObject:
        _validate_digest(expected_sha256)
        if expected_bytes is not None and (
            type(expected_bytes) is not int or not 0 < expected_bytes <= self.max_bytes
        ):
            raise StorageError("storage_invalid_expected_size")
        path = self._path(key)
        temporary = ".upload-" + uuid4().hex + ".tmp"
        with _directory(path, create_under=self.root) as directory:
            descriptor = directory.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            size = 0
            digest = hashlib.sha256()
            try:
                with os.fdopen(descriptor, "wb") as output:
                    for chunk in chunks:
                        if not isinstance(chunk, bytes) or len(chunk) > CHUNK_BYTES:
                            raise StorageError("storage_invalid_chunk")
                        size += len(chunk)
                        if size > self.max_bytes:
                            raise StorageError("storage_object_limit")
                        output.write(chunk)
                        digest.update(chunk)
                    if size == 0 or (expected_bytes is not None and size != expected_bytes):
                        raise StorageError("storage_size_mismatch")
                    if not hmac.compare_digest(digest.hexdigest(), expected_sha256):
                        raise StorageError("storage_digest_mismatch")
                    output.flush()
                    os.fsync(output.fileno())
                try:
                    directory.publish(temporary, key.filename)
                except FileExistsError:
                    raise StorageError("storage_object_exists") from None
                return StoredObject(key, digest.hexdigest(), size)
            finally:
                directory.unlink(temporary)

    def iter_bytes(self, key: ObjectKey, *, expected_sha256: str) -> Iterator[bytes]:
        """Verify size/hash before first yield; consumers must close abandoned iterators."""
        _validate_digest(expected_sha256)
        try:
            with _directory(self._path(key)) as directory:
                descriptor = directory.open(key.filename, os.O_RDONLY)
                with os.fdopen(descriptor, "rb") as source:
                    info = os.fstat(source.fileno())
                    _validate_entry(info)
                    if not 0 < info.st_size <= self.max_bytes:
                        raise StorageError("storage_object_limit")
                    digest = hashlib.sha256()
                    size = 0
                    while block := source.read(min(CHUNK_BYTES, self.max_bytes + 1 - size)):
                        size += len(block)
                        if size > self.max_bytes:
                            raise StorageError("storage_object_limit")
                        digest.update(block)
                    if not hmac.compare_digest(digest.hexdigest(), expected_sha256):
                        raise StorageError("storage_digest_mismatch")
                    if (
                        size != info.st_size
                        or os.fstat(source.fileno()).st_mtime_ns != info.st_mtime_ns
                    ):
                        raise StorageError("storage_object_changed")
                    source.seek(0)
                    remaining = size
                    while remaining:
                        block = source.read(min(CHUNK_BYTES, remaining))
                        if not block:
                            raise StorageError("storage_object_changed")
                        remaining -= len(block)
                        yield block
        except FileNotFoundError:
            raise StorageError("storage_object_missing") from None

    def delete(self, key: ObjectKey) -> bool:
        try:
            with _directory(self._path(key)) as directory:
                _validate_entry(directory.stat(key.filename))
                directory.unlink(key.filename)
            return True
        except FileNotFoundError:
            return False

    def list_recording(self, tenant_id: UUID, recording_id: UUID) -> tuple[ObjectKey, ...]:
        """Inventory one exact server scope; concurrent writers require a domain fence."""
        if type(tenant_id) is not UUID or type(recording_id) is not UUID:
            raise StorageError("storage_server_key_required")
        path = self.root / tenant_id.hex / recording_id.hex
        result = []
        opened = False
        try:
            with _directory(path) as directory:
                opened = True
                for name in directory.names():
                    if name not in {kind.value for kind in ObjectKind}:
                        raise StorageError("storage_recording_inventory_unexpected")
                    _validate_entry(directory.stat(name), directory=True)
                    with _directory(path / name) as objects:
                        for filename in objects.names():
                            if not re.fullmatch(r"[0-9a-f]{32}\.blob", filename):
                                raise StorageError("storage_recording_inventory_unexpected")
                            _validate_entry(objects.stat(filename))
                            result.append(
                                ObjectKey(
                                    tenant_id,
                                    recording_id,
                                    UUID(hex=filename[:-5]),
                                    ObjectKind(name),
                                )
                            )
        except FileNotFoundError:
            if opened:
                raise StorageError("storage_recording_inventory_changed") from None
            # A missing recording namespace is empty only when the managed root still exists.
            with _directory(self.root):
                pass
            return ()
        return tuple(result)

    def delete_recording(
        self,
        tenant_id: UUID,
        recording_id: UUID,
        *,
        expected_keys: tuple[ObjectKey, ...],
    ) -> RecordingDeletionReceipt:
        """Delete DB-owned inventory and recheck empty after caller fences/drains writes.

        Missing expected objects are allowed for idempotent retries. Unknown filesystem
        objects prevent success. This adapter cannot establish the domain generation fence.
        """
        if (
            not isinstance(expected_keys, tuple)
            or any(
                not isinstance(key, ObjectKey)
                or key.tenant_id != tenant_id
                or key.recording_id != recording_id
                for key in expected_keys
            )
            or len(set(expected_keys)) != len(expected_keys)
        ):
            raise StorageError("storage_recording_inventory_scope_mismatch")
        actual = set(self.list_recording(tenant_id, recording_id))
        if not actual.issubset(expected_keys):
            raise StorageError("storage_recording_inventory_mismatch")
        deleted = sum(self.delete(key) for key in expected_keys)
        if self.list_recording(tenant_id, recording_id):
            raise StorageError("storage_recording_deletion_incomplete")
        return RecordingDeletionReceipt(
            tenant_id, recording_id, deleted, len(expected_keys) - deleted, True
        )
