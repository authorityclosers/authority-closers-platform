"""Read-only artifact storage must never become an arbitrary file server."""

from __future__ import annotations

import hashlib
import os
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from ac_platform.media.errors import MediaStorageUnavailable
from ac_platform.media.file_storage import FileMediaObject, ReadOnlyFileMediaStorage
from ac_platform.media.storage import PrivateObjectStorage

KEY = "tenants/tenant-1/media/video/asset-1/version-1/source.mp4"


def entry(body: bytes = b"0123456789") -> FileMediaObject:
    return FileMediaObject(
        KEY, "source.mp4", "video/mp4", len(body), hashlib.sha256(body).hexdigest(), "v1"
    )


def storage(tmp_path: Path, body: bytes = b"0123456789") -> ReadOnlyFileMediaStorage:
    (tmp_path / "source.mp4").write_bytes(body)
    return ReadOnlyFileMediaStorage(root=tmp_path, inventory=[entry(body)])


def test_protocol_metadata_small_reads_and_inclusive_ranges(tmp_path: Path) -> None:
    adapter = storage(tmp_path)
    assert isinstance(adapter, PrivateObjectStorage)
    metadata = adapter.head(KEY)
    assert metadata is not None
    assert metadata.content_length == 10
    assert metadata.storage_version_id == "v1"
    assert metadata.checksum_sha256 == entry().checksum_sha256
    assert adapter.read(KEY) == b"0123456789"
    assert adapter.read_prefix(KEY, max_bytes=3) == b"012"
    assert list(adapter.iter_range(KEY, start=2, end=7, chunk_size=2)) == [b"23", b"45", b"67"]
    assert list(adapter.iter_range(KEY, start=9)) == [b"9"]


def test_inventory_is_not_filesystem_discovery(tmp_path: Path) -> None:
    adapter = storage(tmp_path)
    (tmp_path / "not-authorized.mp4").write_bytes(b"private")
    assert adapter.head("not-authorized.mp4") is None
    assert adapter.head("../source.mp4") is None
    with pytest.raises(MediaStorageUnavailable):
        adapter.read("not-authorized.mp4")
    assert adapter.list_prefix("tenants/tenant-1/") == (KEY,)
    assert adapter.list_prefix("tenants/tenant") == ()
    assert adapter.list_prefix("") == ()
    assert adapter.list_prefix("../") == ()


@pytest.mark.parametrize("operation", ["create_upload_intent", "put", "copy", "delete"])
def test_mutation_is_unconditionally_denied(tmp_path: Path, operation: str) -> None:
    adapter = storage(tmp_path)
    with pytest.raises(MediaStorageUnavailable, match="read-only"):
        if operation == "delete":
            adapter.delete(KEY)
        else:
            getattr(adapter, operation)()
    assert adapter.read(KEY) == b"0123456789"


@pytest.mark.parametrize(
    "unsafe",
    [
        "../source.mp4",
        "/source.mp4",
        "a//b",
        "a/./b",
        "a/../b",
        "a\\b",
        "a:b",
        "a b",
        "a\nb",
        "a./b",
        "a%2fb",
    ],
)
@pytest.mark.parametrize("field", ["object_key", "relative_path"])
def test_unsafe_inventory_paths_are_rejected(tmp_path: Path, unsafe: str, field: str) -> None:
    (tmp_path / "source.mp4").write_bytes(b"0123456789")
    with pytest.raises(MediaStorageUnavailable):
        ReadOnlyFileMediaStorage(root=tmp_path, inventory=[replace(entry(), **{field: unsafe})])


@pytest.mark.parametrize(
    "change",
    [
        {"checksum_sha256": "0" * 64},
        {"checksum_sha256": "not-a-hash"},
        {"content_length": 9},
        {"content_length": True},
        {"content_length": 0},
        {"content_length": 8 * 1024**3 + 1},
        {"content_type": "video/mp4\r\nInjected: yes"},
        {"storage_version_id": "../v1"},
    ],
)
def test_metadata_must_match_verified_bytes(tmp_path: Path, change: dict[str, Any]) -> None:
    (tmp_path / "source.mp4").write_bytes(b"0123456789")
    with pytest.raises(MediaStorageUnavailable):
        ReadOnlyFileMediaStorage(root=tmp_path, inventory=[replace(entry(), **change)])


def test_inventory_and_root_limits(tmp_path: Path) -> None:
    (tmp_path / "source.mp4").write_bytes(b"0123456789")
    for inventory in ([], [entry(), entry()], [entry()] * 8193):
        with pytest.raises(MediaStorageUnavailable):
            ReadOnlyFileMediaStorage(root=tmp_path, inventory=inventory)
    for root in (Path("relative"), tmp_path / "missing", tmp_path / "source.mp4"):
        with pytest.raises(MediaStorageUnavailable):
            ReadOnlyFileMediaStorage(root=root, inventory=[entry()])


@pytest.mark.parametrize(
    "bounds",
    [
        {"start": -1},
        {"start": True},
        {"start": 10},
        {"end": 10},
        {"end": -1},
        {"end": False},
        {"start": 5, "end": 4},
        {"chunk_size": 0},
        {"chunk_size": True},
        {"chunk_size": 16 * 1024**2 + 1},
    ],
)
def test_invalid_range_is_denied(tmp_path: Path, bounds: dict[str, Any]) -> None:
    adapter = storage(tmp_path)
    with pytest.raises(MediaStorageUnavailable):
        list(adapter.iter_range(KEY, **bounds))


@pytest.mark.parametrize("max_bytes", [0, -1, True, 1024**2 + 2])
def test_prefix_memory_bound(tmp_path: Path, max_bytes: int) -> None:
    with pytest.raises(MediaStorageUnavailable):
        storage(tmp_path).read_prefix(KEY, max_bytes=max_bytes)


def test_large_objects_require_streaming(tmp_path: Path) -> None:
    body = b"x" * (1024**2 + 7)
    adapter = storage(tmp_path, body)
    with pytest.raises(MediaStorageUnavailable, match="bounded streaming"):
        adapter.read(KEY)
    chunks = list(adapter.iter_range(KEY, chunk_size=1024**2))
    assert [len(chunk) for chunk in chunks] == [1024**2, 7]
    assert b"".join(chunks) == body


def test_hls_prefix_can_read_one_oversize_detection_byte(tmp_path: Path) -> None:
    body = b"x" * (1024**2 + 2)
    adapter = storage(tmp_path, body)
    prefix = adapter.read_prefix(KEY, max_bytes=1024**2 + 1)
    assert len(prefix) == 1024**2 + 1
    with pytest.raises(MediaStorageUnavailable, match="bounded streaming"):
        adapter.read(KEY)


@pytest.mark.parametrize("change", ["delete", "replace", "overwrite", "truncate"])
def test_verified_file_cannot_silently_change(tmp_path: Path, change: str) -> None:
    adapter = storage(tmp_path)
    path = tmp_path / "source.mp4"
    if change == "delete":
        path.unlink()
    elif change == "replace":
        replacement = tmp_path / "replacement"
        replacement.write_bytes(b"0123456789")
        replacement.replace(path)
    elif change == "overwrite":
        previous = path.stat()
        path.write_bytes(b"abcdefghij")
        os.utime(path, ns=(previous.st_atime_ns, previous.st_mtime_ns + 1_000_000_000))
    else:
        path.write_bytes(b"short")
    with pytest.raises(MediaStorageUnavailable):
        adapter.head(KEY)
    with pytest.raises(MediaStorageUnavailable):
        adapter.read(KEY)


def test_mutation_mid_stream_is_denied_before_next_chunk(tmp_path: Path) -> None:
    adapter = storage(tmp_path)
    iterator = adapter.iter_range(KEY, chunk_size=2)
    assert next(iterator) == b"01"
    path = tmp_path / "source.mp4"
    previous = path.stat()
    with path.open("r+b") as target:
        target.write(b"abcdefghij")
    os.utime(path, ns=(previous.st_atime_ns, previous.st_mtime_ns + 1_000_000_000))
    with pytest.raises(MediaStorageUnavailable):
        next(iterator)


@pytest.mark.parametrize("link_root", [False, True])
def test_symlink_components_are_denied(tmp_path: Path, link_root: bool) -> None:
    actual = tmp_path / "actual"
    actual.mkdir()
    (actual / "source.mp4").write_bytes(b"0123456789")
    alias = tmp_path / "alias"
    try:
        alias.symlink_to(
            actual if link_root else actual / "source.mp4", target_is_directory=link_root
        )
    except OSError:
        pytest.skip("This account cannot create symlinks; POSIX CI exercises this case.")
    with pytest.raises(MediaStorageUnavailable):
        ReadOnlyFileMediaStorage(
            root=alias if link_root else tmp_path,
            inventory=[entry() if link_root else replace(entry(), relative_path="alias")],
        )
