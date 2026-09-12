"""Retry isolation with real private files and explicitly injected encoder bytes.

These tests prove namespace and cleanup behavior, not playable output or a
worker lease. Real FFmpeg checks live in the corresponding integration tests.
"""

from __future__ import annotations

import hashlib
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from typing import Any
from uuid import UUID, uuid4

import pytest

from ac_platform.media.errors import MediaConflict, MediaProcessingError
from ac_platform.media.models import CaptionKind, MediaPurpose
from ac_platform.media.processing import (
    CaptionPassthrough,
    FFmpegMediaProcessor,
    ProcessingQuota,
    ProcessingResult,
    TranscodeProfile,
)
from ac_platform.media.signing import MediaSigner
from ac_platform.media.storage import InMemoryPrivateObjectStorage
from ac_platform.media.video_file_storage import VideoFileStorage
from ac_platform.media.video_probe import VideoMetadata


def _encoder(command: tuple[str, ...], cwd: Path) -> None:
    del cwd
    output = Path(command[-1])
    if output.suffix == ".m3u8":
        output.write_text(
            "#EXTM3U\n#EXTINF:6.0,\nsegment-00000.ts\n#EXT-X-ENDLIST\n", encoding="utf-8"
        )
        output.with_name("segment-00000.ts").write_bytes(b"synthetic-encoded-segment")
    else:
        output.write_bytes(b"synthetic-progressive")


def _processor(*, fail_progressive: bool = False) -> FFmpegMediaProcessor:
    def runner(command: tuple[str, ...], cwd: Path) -> None:
        if fail_progressive and Path(command[-1]).suffix == ".mp4":
            raise MediaProcessingError("synthetic encoding interruption")
        _encoder(command, cwd)

    return FFmpegMediaProcessor(
        profiles=(TranscodeProfile("360p", 640, 360, 800),),
        command_runner=runner,
        video_probe=lambda path: VideoMetadata(640, 360, 6.0),
        quota=ProcessingQuota(
            max_source_bytes=1024,
            max_output_bytes=1024**2,
            max_temp_bytes=4 * 1024**2,
            max_duration_seconds=10,
        ),
    )


@pytest.fixture
def media(tmp_path: Path) -> tuple[VideoFileStorage, str, CaptionPassthrough]:
    storage = VideoFileStorage(
        root=tmp_path / "video-objects",
        max_object_bytes=1024**2,
        max_store_bytes=8 * 1024**2,
    )
    key = f"tenants/{uuid4()}/media/video/{uuid4()}/{uuid4()}/original"
    storage.put(object_key=key, body=b"synthetic-source", content_type="video/mp4")
    caption_key = f"{key}/inputs/en.vtt"
    storage.put(
        object_key=caption_key,
        body=b"WEBVTT\n\n00:00.000 --> 00:01.000\nSynthetic test\n",
        content_type="text/vtt",
    )
    return (
        storage,
        key,
        CaptionPassthrough(
            language="en",
            kind=CaptionKind.CAPTIONS,
            content_type="text/vtt",
            source_key=caption_key,
            is_default=True,
        ),
    )


def _run(
    media: tuple[VideoFileStorage, str, CaptionPassthrough],
    attempt_id: Any,
    *,
    fail_progressive: bool = False,
    purpose: MediaPurpose = MediaPurpose.VIDEO,
) -> ProcessingResult:
    storage, key, caption = media
    return _processor(fail_progressive=fail_progressive).process(
        storage=storage,
        version_id=uuid4(),
        purpose=purpose,
        source_key=key,
        content_type="video/mp4",
        crop=None,
        captions=(caption,),
        attempt_id=attempt_id,
    )


def test_each_attempt_owns_all_renditions_and_captions_without_changing_sources(
    media: tuple[VideoFileStorage, str, CaptionPassthrough],
) -> None:
    storage, key, caption = media
    originals = {item: storage.read(item) for item in (key, caption.source_key)}
    first_id, second_id = uuid4(), uuid4()
    first = _run(media, first_id)
    first_bytes = {item: storage.read(item) for item in first.object_keys}
    second = _run(media, second_id)
    for result, attempt_id in ((first, first_id), (second, second_id)):
        prefix = f"{key}/attempts/{attempt_id}/"
        assert result.object_keys and all(item.startswith(prefix) for item in result.object_keys)
        assert {item.object_key for item in result.renditions}.issubset(result.object_keys)
        assert {item.object_key for item in result.captions}.issubset(result.object_keys)
        assert result.hls_manifest is not None
        assert result.hls_manifest.master_object_key == f"{prefix}renditions/master.m3u8"
        assert result.captions[0].source_object_key == caption.source_key
        assert storage.read(result.captions[0].object_key) == originals[caption.source_key]
    assert set(first.object_keys).isdisjoint(second.object_keys)
    assert {item: storage.read(item) for item in first_bytes} == first_bytes
    assert {item: storage.read(item) for item in originals} == originals
    assert storage.head(f"{key}/renditions/master.m3u8") is None


def test_failed_attempt_cleanup_preserves_other_attempt_and_originals(
    media: tuple[VideoFileStorage, str, CaptionPassthrough],
) -> None:
    storage, key, _ = media
    _run(media, uuid4())
    before = {item: storage.read(item) for item in storage.list_prefix(key)}
    failed_id = uuid4()
    with pytest.raises(MediaProcessingError, match="synthetic encoding interruption"):
        _run(media, failed_id, fail_progressive=True)
    assert storage.list_prefix(f"{key}/attempts/{failed_id}/") == ()
    assert {item: storage.read(item) for item in storage.list_prefix(key)} == before


def test_reusing_an_attempt_rejects_existing_output_without_deleting_it(
    media: tuple[VideoFileStorage, str, CaptionPassthrough],
) -> None:
    storage, key, _ = media
    attempt_id = uuid4()
    _run(media, attempt_id)
    before = {item: storage.read(item) for item in storage.list_prefix(key)}
    with pytest.raises(MediaProcessingError, match="already exists"):
        _run(media, attempt_id)
    assert {item: storage.read(item) for item in storage.list_prefix(key)} == before


def test_concurrent_same_attempt_loser_cannot_delete_winning_video(
    media: tuple[VideoFileStorage, str, CaptionPassthrough], monkeypatch: pytest.MonkeyPatch
) -> None:
    storage, key, caption = media
    other_handle = VideoFileStorage(
        root=storage.root,
        max_object_bytes=storage.max_object_bytes,
        max_store_bytes=storage.max_store_bytes,
    )
    attempt_id = uuid4()
    first_output = f"{key}/attempts/{attempt_id}/renditions/hls/360p/index.m3u8"
    rendezvous = Barrier(2, timeout=10)
    original = VideoFileStorage.put_stream

    def contend(self, **kwargs):
        if kwargs["object_key"] == first_output:
            # Both processors have observed head(None). Exercise the actual
            # filesystem's cross-handle create boundary, not a mocked receipt.
            rendezvous.wait()
        return original(self, **kwargs)

    monkeypatch.setattr(VideoFileStorage, "put_stream", contend)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [
            pool.submit(_run, state, attempt_id) for state in (media, (other_handle, key, caption))
        ]
        outcomes = []
        for future in futures:
            try:
                outcomes.append(future.result(timeout=15))
            except MediaConflict as error:
                outcomes.append(error)
    winners = [item for item in outcomes if isinstance(item, ProcessingResult)]
    assert len(winners) == 1
    assert sum(isinstance(item, MediaConflict) for item in outcomes) == 1
    winner = winners[0]
    assert set(storage.list_prefix(f"{key}/attempts/{attempt_id}")) == set(winner.object_keys)
    assert all(storage.head(item) is not None for item in winner.object_keys)
    assert storage.read(key) == b"synthetic-source"
    assert not tuple(storage.root.glob("*.part"))


@pytest.mark.parametrize("phase", ["master", "progressive", "caption"])
def test_late_output_collision_is_not_owned_by_failed_attempt_cleanup(
    media: tuple[VideoFileStorage, str, CaptionPassthrough],
    monkeypatch: pytest.MonkeyPatch,
    phase: str,
) -> None:
    storage, key, _ = media
    attempt_id = uuid4()
    original = VideoFileStorage.put_stream
    collided: list[str] = []
    other_bytes = b"output-owned-by-the-other-operation"

    def collide(self, **kwargs):
        object_key = kwargs["object_key"]
        matches = (
            object_key.endswith("/master.m3u8")
            if phase == "master"
            else object_key.endswith("/progressive.mp4")
            if phase == "progressive"
            else "/captions/" in object_key
        )
        if matches and not collided:
            collided.append(object_key)
            original(
                self,
                object_key=object_key,
                chunks=(other_bytes,),
                content_type=kwargs["content_type"],
                content_length=len(other_bytes),
                checksum_sha256=hashlib.sha256(other_bytes).hexdigest(),
            )
        return original(self, **kwargs)

    monkeypatch.setattr(VideoFileStorage, "put_stream", collide)
    with pytest.raises((MediaConflict, MediaProcessingError)):
        _run(media, attempt_id)
    assert len(collided) == 1
    assert storage.read(collided[0]) == other_bytes
    assert storage.list_prefix(f"{key}/attempts/{attempt_id}") == tuple(collided)
    assert storage.read(key) == b"synthetic-source"


@pytest.mark.parametrize("attempt_id", [UUID(int=0), "../other", str(uuid4()), True, 1])
def test_attempt_id_must_be_a_nonzero_uuid_before_any_output_is_written(
    media: tuple[VideoFileStorage, str, CaptionPassthrough], attempt_id: Any
) -> None:
    storage, key, _ = media
    before = storage.list_prefix(key)
    with pytest.raises(MediaProcessingError, match="attempt"):
        _run(media, attempt_id)
    assert storage.list_prefix(key) == before


def test_attempt_namespace_cannot_silently_fall_back_to_nonvideo_copy(
    media: tuple[VideoFileStorage, str, CaptionPassthrough],
) -> None:
    storage, key, _ = media
    before = storage.list_prefix(key)
    with pytest.raises(MediaProcessingError, match="video"):
        _run(media, uuid4(), purpose=MediaPurpose.AVATAR)
    assert storage.list_prefix(key) == before


def test_attempt_namespace_cannot_fall_back_to_nonexclusive_generic_storage() -> None:
    storage = InMemoryPrivateObjectStorage(MediaSigner("attempt-synthetic-generic-signer-value"))
    key = f"tenants/{uuid4()}/media/video/{uuid4()}/{uuid4()}/original"
    storage.put(object_key=key, body=b"synthetic-source", content_type="video/mp4")
    with pytest.raises(MediaProcessingError, match="exclusive private video adapter"):
        _processor().process(
            storage=storage,
            version_id=uuid4(),
            purpose=MediaPurpose.VIDEO,
            source_key=key,
            content_type="video/mp4",
            crop=None,
            attempt_id=uuid4(),
        )
    assert storage.list_prefix(key) == (key,)
