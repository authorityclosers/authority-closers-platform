from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock

import pytest

from ac_platform.media.errors import MediaProcessingError, MediaQuotaExceeded
from ac_platform.media.processing import (
    ProcessingQuota,
    _ffmpeg_source_metadata,
    _stage_ffmpeg_source,
)
from ac_platform.media.signing import MediaSigner
from ac_platform.media.storage import InMemoryPrivateObjectStorage, StoredObjectMetadata

KEY = "tenants/example/media/video/asset/version/original"
MIB = 1024 * 1024


def fixture_storage(
    body: bytes = b"video",
) -> tuple[InMemoryPrivateObjectStorage, StoredObjectMetadata]:
    storage = InMemoryPrivateObjectStorage(MediaSigner("streaming-unit-test-signing-key-32!!"))
    metadata = storage.put(object_key=KEY, body=body, content_type="video/mp4")
    return storage, metadata


def test_stages_source_with_bounded_chunks_and_no_buffered_read(tmp_path: Path) -> None:
    body = b"x" * (3 * MIB + 73)
    storage, metadata = fixture_storage(body)
    storage.read = Mock(side_effect=AssertionError("Must not buffer source"))  # type: ignore[method-assign]
    storage.read_prefix = Mock(side_effect=AssertionError("Must not buffer source"))  # type: ignore[method-assign]
    stream = Mock(wraps=storage.iter_range)
    storage.iter_range = stream  # type: ignore[method-assign]
    head = _ffmpeg_source_metadata(storage, KEY, "video/mp4", ProcessingQuota())
    destination = tmp_path / "source.bin"
    _stage_ffmpeg_source(storage, head, destination)
    stream.assert_called_once_with(KEY, start=0, end=len(body) - 1, chunk_size=MIB)
    assert destination.read_bytes() == body
    assert head == metadata


@pytest.mark.parametrize(
    "change",
    [
        {"object_key": "another/source"},
        {"content_type": "text/plain"},
        {"content_length": True},
        {"content_length": 1.5},
        {"checksum_sha256": ""},
        {"checksum_sha256": "not-a-sha256"},
        {"storage_version_id": ""},
        {"storage_version_id": "x" * 256},
    ],
)
def test_rejects_invalid_source_metadata_before_reading(change: dict[str, object]) -> None:
    storage, metadata = fixture_storage()
    storage.head = Mock(return_value=replace(metadata, **change))  # type: ignore[method-assign, arg-type]
    storage.iter_range = Mock(side_effect=AssertionError("Must not stream"))  # type: ignore[method-assign]
    with pytest.raises(MediaProcessingError, match="metadata"):
        _ffmpeg_source_metadata(storage, KEY, "video/mp4", ProcessingQuota())


def test_source_limit_is_checked_before_streaming() -> None:
    storage, _ = fixture_storage()
    with pytest.raises(MediaQuotaExceeded):
        _ffmpeg_source_metadata(storage, KEY, "video/mp4", ProcessingQuota(max_source_bytes=4))


@pytest.mark.parametrize("revision_length", [129, 255])
def test_preserves_existing_normalized_mime_and_storage_revision_contract(
    tmp_path: Path, revision_length: int
) -> None:
    storage, metadata = fixture_storage()
    metadata = replace(
        metadata, content_type=" Video/MP4; codecs=avc1", storage_version_id="x" * revision_length
    )
    storage.head = Mock(return_value=metadata)  # type: ignore[method-assign]
    head = _ffmpeg_source_metadata(storage, KEY, "video/mp4", ProcessingQuota())
    destination = tmp_path / "source.bin"
    _stage_ffmpeg_source(storage, head, destination)
    assert destination.read_bytes() == b"video"


@pytest.mark.parametrize(
    "chunks", [[b"vide"], [b"VIDEO"], [b"video!"], [b""], ["video"], [b"x" * (MIB + 1)]]
)
def test_rejects_truncated_changed_overrun_empty_or_unbounded_stream(
    tmp_path: Path, chunks: list[object]
) -> None:
    storage, metadata = fixture_storage()
    storage.iter_range = Mock(return_value=iter(chunks))  # type: ignore[method-assign]
    with pytest.raises(MediaProcessingError):
        _stage_ffmpeg_source(storage, metadata, tmp_path / "source.bin")


def test_revision_change_is_detected_even_when_bytes_match(tmp_path: Path) -> None:
    storage, metadata = fixture_storage()
    storage.head = Mock(return_value=replace(metadata, storage_version_id="replacement"))  # type: ignore[method-assign]
    with pytest.raises(MediaProcessingError, match="changed"):
        _stage_ffmpeg_source(storage, metadata, tmp_path / "source.bin")


def test_staging_never_overwrites_an_existing_file(tmp_path: Path) -> None:
    storage, metadata = fixture_storage()
    destination = tmp_path / "source.bin"
    destination.write_bytes(b"preserve")
    with pytest.raises(MediaProcessingError, match="stage"):
        _stage_ffmpeg_source(storage, metadata, destination)
    assert destination.read_bytes() == b"preserve"


def test_transport_failure_is_not_accepted_as_end_of_file(tmp_path: Path) -> None:
    storage, metadata = fixture_storage()

    def failing_stream(*args: object, **kwargs: object):  # type: ignore[no-untyped-def]
        yield b"vi"
        raise OSError("Disconnected")

    storage.iter_range = failing_stream  # type: ignore[method-assign, assignment]
    with pytest.raises(MediaProcessingError, match="stage"):
        _stage_ffmpeg_source(storage, metadata, tmp_path / "source.bin")
