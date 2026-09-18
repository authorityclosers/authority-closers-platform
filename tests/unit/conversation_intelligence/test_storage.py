from __future__ import annotations

import ctypes
import hashlib
import os
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest

from ac_platform.conversation_intelligence import storage


def _hash(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _key(
    *, tenant: UUID | None = None, kind: storage.ObjectKind | None = None
) -> storage.ObjectKey:
    return storage.ObjectKey(
        tenant or uuid4(),
        uuid4(),
        uuid4(),
        kind or storage.ObjectKind.SOURCE_AUDIO,
    )


def _objects(root: Path) -> list[Path]:
    return list(root.rglob("*.blob"))


def test_stream_put_verified_read_and_idempotent_delete(tmp_path: Path) -> None:
    adapter = storage.PrivateLocalRecordingStorage(tmp_path / "private")
    key = _key()
    content = b"local synthetic audio fixture"
    result = adapter.put(
        key,
        [content[:5], b"", content[5:]],
        expected_sha256=_hash(content),
        expected_bytes=len(content),
    )
    assert result.key == key
    assert result.sha256 == _hash(content)
    assert result.size_bytes == len(content)
    assert b"".join(adapter.iter_bytes(key, expected_sha256=_hash(content))) == content
    assert adapter.delete(key) is True
    assert adapter.delete(key) is False
    assert not list(adapter.root.rglob("*.tmp"))


def test_server_uuid_and_enum_keys_only() -> None:
    with pytest.raises(storage.StorageError, match="server_key_required"):
        storage.ObjectKey("../escape", uuid4(), uuid4(), storage.ObjectKind.SOURCE_AUDIO)  # type: ignore[arg-type]
    with pytest.raises(storage.StorageError, match="server_key_required"):
        storage.ObjectKey(uuid4(), uuid4(), uuid4(), "../source")  # type: ignore[arg-type]


def test_tenant_recording_and_kind_namespaces_do_not_alias(tmp_path: Path) -> None:
    adapter = storage.PrivateLocalRecordingStorage(tmp_path / "private")
    key = _key()
    other_tenant = storage.ObjectKey(uuid4(), key.recording_id, key.blob_id, key.kind)
    other_recording = storage.ObjectKey(key.tenant_id, uuid4(), key.blob_id, key.kind)
    other_kind = storage.ObjectKey(
        key.tenant_id, key.recording_id, key.blob_id, storage.ObjectKind.SIGNAL_FEATURES
    )
    for index, item in enumerate((key, other_tenant, other_recording, other_kind)):
        value = bytes([index])
        adapter.put(item, [value], expected_sha256=_hash(value))
    assert len(_objects(adapter.root)) == 4
    for index, item in enumerate((key, other_tenant, other_recording, other_kind)):
        value = bytes([index])
        assert b"".join(adapter.iter_bytes(item, expected_sha256=_hash(value))) == value


def test_existing_object_is_not_overwritten(tmp_path: Path) -> None:
    adapter = storage.PrivateLocalRecordingStorage(tmp_path / "private")
    key = _key()
    adapter.put(key, [b"first"], expected_sha256=_hash(b"first"))
    with pytest.raises(storage.StorageError, match="object_exists"):
        adapter.put(key, [b"second"], expected_sha256=_hash(b"second"))
    assert b"".join(adapter.iter_bytes(key, expected_sha256=_hash(b"first"))) == b"first"
    assert not list(adapter.root.rglob("*.tmp"))


@pytest.mark.parametrize("case", ["digest", "bytes", "limit", "empty", "chunk", "large-chunk"])
def test_invalid_stream_has_no_published_or_temporary_object(tmp_path: Path, case: str) -> None:
    adapter = storage.PrivateLocalRecordingStorage(tmp_path / "private", max_bytes=16)
    expected = _hash(b"fixture")
    chunks: Any = [b"fixture"]
    count = None
    if case == "digest":
        expected = "0" * 64
    elif case == "bytes":
        count = 4
    elif case == "limit":
        chunks = [b"a" * 10, b"b" * 10]
    elif case == "empty":
        chunks = []
    elif case == "chunk":
        chunks = ["not bytes"]
    else:
        chunks = [b"a" * (storage.CHUNK_BYTES + 1)]
    with pytest.raises(storage.StorageError):
        adapter.put(_key(), chunks, expected_sha256=expected, expected_bytes=count)
    assert _objects(adapter.root) == []
    assert not list(adapter.root.rglob("*.tmp"))


def test_stream_exception_and_publish_failure_clean_temporary_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = storage.PrivateLocalRecordingStorage(tmp_path / "private")

    def broken_stream() -> Any:
        yield b"fixture"
        raise RuntimeError("synthetic stream interruption")

    with pytest.raises(RuntimeError, match="synthetic stream interruption"):
        adapter.put(_key(), broken_stream(), expected_sha256=_hash(b"fixture"))

    def broken_publish(*args: Any, **kwargs: Any) -> None:
        del args, kwargs
        raise OSError("synthetic publication failure")

    monkeypatch.setattr(storage._Directory, "publish", broken_publish)
    with pytest.raises(storage.StorageError, match="filesystem_operation_failed"):
        adapter.put(_key(), [b"fixture"], expected_sha256=_hash(b"fixture"))
    assert _objects(adapter.root) == []
    assert not list(adapter.root.rglob("*.tmp"))


def test_hash_mismatch_fails_before_any_read_bytes_are_yielded(tmp_path: Path) -> None:
    adapter = storage.PrivateLocalRecordingStorage(tmp_path / "private")
    key = _key()
    adapter.put(key, [b"fixture"], expected_sha256=_hash(b"fixture"))
    iterator = adapter.iter_bytes(key, expected_sha256="0" * 64)
    with pytest.raises(storage.StorageError, match="digest_mismatch"):
        next(iterator)


def test_corrupt_oversized_object_is_not_read(tmp_path: Path) -> None:
    adapter = storage.PrivateLocalRecordingStorage(tmp_path / "private", max_bytes=16)
    key = _key()
    adapter.put(key, [b"fixture"], expected_sha256=_hash(b"fixture"))
    _objects(adapter.root)[0].write_bytes(b"corruption" * 10)
    with pytest.raises(storage.StorageError, match="object_limit"):
        next(adapter.iter_bytes(key, expected_sha256=_hash(b"corruption" * 10)))


def test_reopen_marked_root_and_refuse_unrelated_directory(tmp_path: Path) -> None:
    adapter = storage.PrivateLocalRecordingStorage(tmp_path / "private")
    key = _key()
    adapter.put(key, [b"fixture"], expected_sha256=_hash(b"fixture"))
    reopened = storage.PrivateLocalRecordingStorage(adapter.root)
    assert b"".join(reopened.iter_bytes(key, expected_sha256=_hash(b"fixture"))) == b"fixture"
    unrelated = tmp_path / "unrelated"
    unrelated.mkdir()
    (unrelated / "keep.txt").write_text("preserve unrelated file")
    with pytest.raises(storage.StorageError, match="root_not_owned"):
        storage.PrivateLocalRecordingStorage(unrelated)
    assert (unrelated / "keep.txt").read_text() == "preserve unrelated file"


@pytest.mark.parametrize("path", [Path("relative"), Path("/"), Path("C:/")])
def test_unsafe_root_configuration_rejected(path: Path) -> None:
    with pytest.raises(storage.StorageError, match="invalid_configuration"):
        storage.PrivateLocalRecordingStorage(path)


def test_repository_root_is_never_storage(tmp_path: Path) -> None:
    repository = tmp_path / "repo"
    repository.mkdir()
    (repository / ".git").write_text("synthetic worktree marker")
    with pytest.raises(storage.StorageError, match="outside_repository"):
        storage.PrivateLocalRecordingStorage(repository / "storage")
    assert not (repository / "storage").exists()


def test_missing_read_returns_sanitized_code(tmp_path: Path) -> None:
    adapter = storage.PrivateLocalRecordingStorage(tmp_path / "private")
    with pytest.raises(storage.StorageError, match="^storage_object_missing$"):
        next(adapter.iter_bytes(_key(), expected_sha256="0" * 64))


def _symlink(link: Path, target: Path, *, directory: bool = False) -> None:
    try:
        link.symlink_to(target, target_is_directory=directory)
    except OSError:
        pytest.skip("OS symlink privilege unavailable; no symlink behavior claim")


def test_symlink_root_and_parent_are_rejected(tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.mkdir()
    linked = tmp_path / "linked"
    _symlink(linked, target, directory=True)
    for root in (linked, linked / "new"):
        with pytest.raises(storage.StorageError):
            storage.PrivateLocalRecordingStorage(root)
    assert list(target.iterdir()) == []


def test_symlink_tenant_and_object_are_not_followed(tmp_path: Path) -> None:
    adapter = storage.PrivateLocalRecordingStorage(tmp_path / "private")
    key = _key()
    target = tmp_path / "target"
    target.mkdir()
    tenant = adapter.root / key.tenant_id.hex
    _symlink(tenant, target, directory=True)
    with pytest.raises(storage.StorageError):
        adapter.put(key, [b"fixture"], expected_sha256=_hash(b"fixture"))
    assert list(target.iterdir()) == []
    tenant.unlink()
    adapter.put(key, [b"fixture"], expected_sha256=_hash(b"fixture"))
    blob = _objects(adapter.root)[0]
    blob.unlink()
    protected = tmp_path / "protected.txt"
    protected.write_bytes(b"preserved outside content")
    _symlink(blob, protected)
    with pytest.raises(storage.StorageError):
        next(adapter.iter_bytes(key, expected_sha256=_hash(protected.read_bytes())))
    with pytest.raises(storage.StorageError):
        adapter.delete(key)
    assert protected.read_bytes() == b"preserved outside content"


def test_hardlinked_alias_is_not_read_or_deleted(tmp_path: Path) -> None:
    adapter = storage.PrivateLocalRecordingStorage(tmp_path / "private")
    key = _key()
    adapter.put(key, [b"fixture"], expected_sha256=_hash(b"fixture"))
    os.link(_objects(adapter.root)[0], tmp_path / "alias")
    with pytest.raises(storage.StorageError, match="unsafe_filesystem_entry"):
        next(adapter.iter_bytes(key, expected_sha256=_hash(b"fixture")))
    with pytest.raises(storage.StorageError, match="unsafe_filesystem_entry"):
        adapter.delete(key)


def test_put_does_not_recreate_deleted_root_without_private_initialization(tmp_path: Path) -> None:
    adapter = storage.PrivateLocalRecordingStorage(tmp_path / "private")
    (adapter.root / ".ac-recording-storage").unlink()
    adapter.root.rmdir()
    with pytest.raises(FileNotFoundError):
        adapter.put(_key(), [b"fixture"], expected_sha256=_hash(b"fixture"))
    assert not adapter.root.exists()


def test_private_root_and_file_permissions(tmp_path: Path) -> None:
    adapter = storage.PrivateLocalRecordingStorage(tmp_path / "private")
    adapter.put(_key(), [b"fixture"], expected_sha256=_hash(b"fixture"))
    if os.name != "nt":
        assert adapter.root.stat().st_mode & 0o777 == 0o700
        assert _objects(adapter.root)[0].stat().st_mode & 0o777 == 0o600
        return
    from ctypes import wintypes

    kernel, security = storage._windows_apis()
    security.GetFileSecurityW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
    ]
    security.ConvertSecurityDescriptorToStringSecurityDescriptorW.argtypes = [
        ctypes.c_void_p,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.LPWSTR),
        ctypes.POINTER(wintypes.DWORD),
    ]
    needed = wintypes.DWORD()
    security.GetFileSecurityW(str(adapter.root), 4, None, 0, ctypes.byref(needed))
    buffer = ctypes.create_string_buffer(needed.value)
    assert security.GetFileSecurityW(str(adapter.root), 4, buffer, needed, ctypes.byref(needed))
    sddl = wintypes.LPWSTR()
    assert security.ConvertSecurityDescriptorToStringSecurityDescriptorW(
        buffer,
        1,
        4,
        ctypes.byref(sddl),
        None,
    )
    try:
        descriptor = sddl.value or ""
        assert descriptor.startswith("D:P")
        assert ";;;SY)" in descriptor and ";;;BA)" in descriptor
        assert ";;;WD)" not in descriptor and ";;;BU)" not in descriptor
        assert ";;;AU)" not in descriptor
    finally:
        kernel.LocalFree(ctypes.cast(sddl, ctypes.c_void_p))


def test_recording_deletion_checks_inventory_and_preserves_other_recordings(tmp_path: Path) -> None:
    adapter = storage.PrivateLocalRecordingStorage(tmp_path / "private")
    key = _key()
    derivative = storage.ObjectKey(
        key.tenant_id, key.recording_id, uuid4(), storage.ObjectKind.SIGNAL_FEATURES
    )
    other = storage.ObjectKey(key.tenant_id, uuid4(), uuid4(), storage.ObjectKind.SOURCE_AUDIO)
    for item in (key, derivative, other):
        adapter.put(item, [b"fixture"], expected_sha256=_hash(b"fixture"))
    assert set(adapter.list_recording(key.tenant_id, key.recording_id)) == {key, derivative}
    with pytest.raises(storage.StorageError, match="inventory_mismatch"):
        adapter.delete_recording(key.tenant_id, key.recording_id, expected_keys=(key,))
    receipt = adapter.delete_recording(
        key.tenant_id, key.recording_id, expected_keys=(key, derivative)
    )
    assert receipt.local_inventory_empty is True
    assert receipt.domain_generation_fence_verified is False
    assert receipt.deleted_count == 2
    repeated = adapter.delete_recording(
        key.tenant_id, key.recording_id, expected_keys=(key, derivative)
    )
    assert repeated.deleted_count == 0
    assert repeated.already_absent_count == 2
    assert b"".join(adapter.iter_bytes(other, expected_sha256=_hash(b"fixture"))) == b"fixture"


def test_recording_deletion_rejects_cross_scope_inventory(tmp_path: Path) -> None:
    adapter = storage.PrivateLocalRecordingStorage(tmp_path / "private")
    key = _key()
    other = _key()
    with pytest.raises(storage.StorageError, match="inventory_scope_mismatch"):
        adapter.delete_recording(key.tenant_id, key.recording_id, expected_keys=(other,))


def test_recording_deletion_rejects_inflight_or_unexpected_files(tmp_path: Path) -> None:
    adapter = storage.PrivateLocalRecordingStorage(tmp_path / "private")
    key = _key()
    adapter.put(key, [b"fixture"], expected_sha256=_hash(b"fixture"))
    unexpected = _objects(adapter.root)[0].with_name(".upload-pending.tmp")
    unexpected.write_bytes(b"fixture")
    with pytest.raises(storage.StorageError, match="inventory_unexpected"):
        adapter.delete_recording(key.tenant_id, key.recording_id, expected_keys=(key,))
    assert b"".join(adapter.iter_bytes(key, expected_sha256=_hash(b"fixture"))) == b"fixture"


def test_new_object_during_deletion_prevents_empty_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = storage.PrivateLocalRecordingStorage(tmp_path / "private")
    key = _key()
    later = storage.ObjectKey(key.tenant_id, key.recording_id, uuid4(), key.kind)
    adapter.put(key, [b"fixture"], expected_sha256=_hash(b"fixture"))
    original_delete = adapter.delete

    def racing_delete(item: storage.ObjectKey) -> bool:
        deleted = original_delete(item)
        adapter.put(later, [b"fixture"], expected_sha256=_hash(b"fixture"))
        return deleted

    monkeypatch.setattr(adapter, "delete", racing_delete)
    with pytest.raises(storage.StorageError, match="deletion_incomplete"):
        adapter.delete_recording(key.tenant_id, key.recording_id, expected_keys=(key,))
