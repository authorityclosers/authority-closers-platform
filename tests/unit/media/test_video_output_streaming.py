from __future__ import annotations

import hashlib
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock

import pytest

from ac_platform.media.errors import (
    MediaProcessingError,
    MediaQuotaExceeded,
    MediaStorageUnavailable,
)
from ac_platform.media.processing import FFmpegMediaProcessor
from ac_platform.media.signing import MediaSigner
from ac_platform.media.storage import InMemoryPrivateObjectStorage
from ac_platform.media.video_file_storage import VideoFileStorage

MIB = 1024 * 1024
KEY = (
    "tenants/11111111-1111-4111-8111-111111111111/media/video/"
    "22222222-2222-4222-8222-222222222222/33333333-3333-4333-8333-333333333333/"
    "original/renditions/progressive.mp4"
)


def memory_store():
    return InMemoryPrivateObjectStorage(MediaSigner("output-streaming-test-key-32-bytes!"))


def disk_store(tmp_path):
    return VideoFileStorage(
        root=tmp_path / "video-objects", max_object_bytes=8 * MIB, max_store_bytes=16 * MIB
    )


def save(storage, path, *, max_bytes=8 * MIB, created=None):
    return FFmpegMediaProcessor()._store_file(
        storage,
        path=path,
        object_key=KEY,
        content_type="video/mp4",
        max_bytes=max_bytes,
        created_keys=created if created is not None else [],
    )


def test_large_real_file_streams_to_private_disk_without_buffered_put(tmp_path, monkeypatch):
    source = tmp_path / "progressive.mp4"
    block = b"v" * MIB
    with source.open("wb") as stream:
        for _ in range(3):
            stream.write(block)
        stream.write(b"tail")
    adapter = disk_store(tmp_path)
    monkeypatch.setattr(Path, "read_bytes", Mock(side_effect=AssertionError("No whole-file read")))
    monkeypatch.setattr(adapter, "put", Mock(side_effect=AssertionError("Must use streaming")))
    original = adapter.put_stream
    lengths = []

    def tracked(**kwargs):
        original_chunks = kwargs["chunks"]

        def chunks():
            for chunk in original_chunks:
                lengths.append(len(chunk))
                yield chunk

        return original(**{**kwargs, "chunks": chunks()})

    monkeypatch.setattr(adapter, "put_stream", tracked)
    created = []
    assert save(adapter, source, created=created) == 3 * MIB + 4
    assert lengths == [MIB, MIB, MIB, 4]
    assert created == [KEY]
    digest = hashlib.sha256()
    for chunk in adapter.iter_range(KEY):
        digest.update(chunk)
    assert digest.hexdigest() == adapter.head(KEY).checksum_sha256


def test_small_legacy_output_still_supported_without_read_bytes(tmp_path, monkeypatch):
    source = tmp_path / "small.mp4"
    source.write_bytes(b"video")
    adapter = memory_store()
    monkeypatch.setattr(Path, "read_bytes", Mock(side_effect=AssertionError("No whole-file read")))
    assert save(adapter, source) == 5
    assert adapter.read(KEY) == b"video"


def test_large_legacy_output_fails_before_read_or_mutation(tmp_path, monkeypatch):
    source = tmp_path / "large.mp4"
    with source.open("wb") as stream:
        stream.truncate(MIB + 1)
    adapter = memory_store()
    put = Mock(side_effect=AssertionError("Must not put"))
    monkeypatch.setattr(adapter, "put", put)
    created = []
    with pytest.raises(MediaProcessingError, match="streaming storage"):
        save(adapter, source, created=created)
    assert not created
    put.assert_not_called()


@pytest.mark.parametrize("body,limit", [(b"", MIB), (b"large", 4)])
def test_empty_or_overquota_output_never_stored(tmp_path, body, limit):
    source = tmp_path / "invalid.mp4"
    source.write_bytes(body)
    adapter = memory_store()
    created = []
    with pytest.raises((MediaProcessingError, MediaQuotaExceeded)):
        save(adapter, source, max_bytes=limit, created=created)
    assert created == []
    assert adapter.head(KEY) is None


def test_changed_output_between_hash_and_transfer_is_rejected(tmp_path, monkeypatch):
    source = tmp_path / "changed.mp4"
    source.write_bytes(b"video")
    adapter = disk_store(tmp_path)
    original = adapter.put_stream

    def change_then_store(**kwargs):
        source.write_bytes(b"CHANG")
        return original(**kwargs)

    monkeypatch.setattr(adapter, "put_stream", change_then_store)
    with pytest.raises((MediaProcessingError, MediaStorageUnavailable), match="changed|checksum"):
        save(adapter, source)
    assert adapter.head(KEY) is None
    assert not tuple(adapter.root.glob("*.part"))


def test_storage_metadata_mismatch_cannot_report_success(tmp_path, monkeypatch):
    source = tmp_path / "small.mp4"
    source.write_bytes(b"video")
    adapter = memory_store()
    original = adapter.put

    def wrong_metadata(**kwargs):
        return replace(original(**kwargs), checksum_sha256="0" * 64)

    monkeypatch.setattr(adapter, "put", wrong_metadata)
    created = []
    with pytest.raises(MediaProcessingError, match="metadata"):
        save(adapter, source, created=created)
    assert created == [KEY]  # Caller owns cleanup after uncertain provider completion.


def test_existing_destination_is_never_overwritten(tmp_path):
    source = tmp_path / "output.mp4"
    source.write_bytes(b"new")
    adapter = memory_store()
    adapter.put(object_key=KEY, body=b"original", content_type="video/mp4")
    with pytest.raises(MediaProcessingError):
        save(adapter, source)
    assert adapter.read(KEY) == b"original"


def test_tree_applies_remaining_quota_after_each_actual_write(tmp_path, monkeypatch):
    directory = tmp_path / "hls"
    directory.mkdir()
    (directory / "first.ts").write_bytes(b"one")
    (directory / "second.ts").write_bytes(b"two")
    processor = FFmpegMediaProcessor()
    limits = []

    def stored(storage, **kwargs):
        limits.append(kwargs["max_bytes"])
        return 3

    monkeypatch.setattr(processor, "_store_file", stored)
    assert (
        processor._store_tree(
            memory_store(),
            directory=directory,
            object_prefix=KEY,
            remaining_bytes=7,
            created_keys=[],
        )
        == 6
    )
    assert limits == [7, 4]
