"""Real FFmpeg attempt namespaces on the private local video filesystem.

These checks exercise only the processor and storage boundary. They do not
claim worker leasing, database finalization, READY state, or runtime activation.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from uuid import uuid4

import pytest

from ac_platform.media.errors import MediaProcessingError
from ac_platform.media.models import CaptionKind, MediaPurpose
from ac_platform.media.processing import (
    CaptionPassthrough,
    FFmpegMediaProcessor,
    ProcessingQuota,
    TranscodeProfile,
)
from ac_platform.media.video_file_storage import VideoFileStorage
from ac_platform.media.video_probe import FFprobeVideoProbe

pytestmark = pytest.mark.skipif(
    not shutil.which("ffmpeg") or not shutil.which("ffprobe"),
    reason="requires FFmpeg + ffprobe",
)


def _read(storage: VideoFileStorage, object_key: str) -> bytes:
    return b"".join(storage.iter_range(object_key, chunk_size=64 * 1024))


def _materialize_attempt(
    storage: VideoFileStorage, *, prefix: str, destination: Path
) -> tuple[set[str], Path]:
    keys = set(storage.list_prefix(prefix))
    assert keys
    for object_key in keys:
        relative = object_key.removeprefix(f"{prefix}/")
        output = destination / relative
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(_read(storage, object_key))
    return keys, destination


def _decode(path: Path) -> None:
    subprocess.run(  # noqa: S603 - fixed local executable and generated test path
        [  # noqa: S607 - executable on the controlled test host's PATH
            "ffmpeg",
            "-nostdin",
            "-v",
            "error",
            "-protocol_whitelist",
            "file",
            "-i",
            str(path),
            "-f",
            "null",
            "-",
        ],
        check=True,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        timeout=30,
    )


def test_real_ffmpeg_attempts_are_disjoint_playable_and_immutable(tmp_path: Path) -> None:
    source_path = tmp_path / "synthetic.mp4"
    subprocess.run(  # noqa: S603 - fixed local executable and generated test path
        [  # noqa: S607 - executable on the controlled test host's PATH
            "ffmpeg",
            "-nostdin",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=c=blue:s=320x180:r=24:d=1.25",
            "-c:v",
            "libx264",
            "-threads",
            "1",
            "-pix_fmt",
            "yuv420p",
            str(source_path),
        ],
        check=True,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        timeout=30,
    )
    source_bytes = source_path.read_bytes()
    source_key = f"tenants/{uuid4()}/media/video/{uuid4()}/{uuid4()}/original"
    caption_key = f"{source_key}/inputs/en.vtt"
    caption_bytes = b"WEBVTT\n\n00:00.000 --> 00:01.000\nSynthetic test\n"
    storage = VideoFileStorage(
        root=tmp_path / "video-objects",
        max_object_bytes=8 * 1024 * 1024,
        max_store_bytes=32 * 1024 * 1024,
    )
    storage.put(object_key=source_key, body=source_bytes, content_type="video/mp4")
    storage.put(object_key=caption_key, body=caption_bytes, content_type="text/vtt")
    caption = CaptionPassthrough(
        language="en",
        kind=CaptionKind.CAPTIONS,
        content_type="text/vtt",
        source_key=caption_key,
        is_default=True,
    )
    processor = FFmpegMediaProcessor(
        profiles=(TranscodeProfile("180p", 160, 90, 200),),
        quota=ProcessingQuota(
            max_source_bytes=1024 * 1024,
            max_output_bytes=8 * 1024 * 1024,
            max_renditions=2,
            max_duration_seconds=5,
            max_output_files=16,
            max_temp_bytes=16 * 1024 * 1024,
        ),
    )
    first_attempt, second_attempt = uuid4(), uuid4()
    assert first_attempt.int and second_attempt.int and first_attempt != second_attempt

    first = processor.process(
        storage=storage,
        version_id=uuid4(),
        purpose=MediaPurpose.VIDEO,
        source_key=source_key,
        content_type="video/mp4",
        crop=None,
        captions=(caption,),
        attempt_id=first_attempt,
    )
    first_prefix = f"{source_key}/attempts/{first_attempt}"
    first_keys, first_directory = _materialize_attempt(
        storage, prefix=first_prefix, destination=tmp_path / "first-attempt"
    )
    assert first_keys == set(first.object_keys)
    assert all(key.startswith(f"{first_prefix}/") for key in first_keys)
    assert storage.head(source_key) is not None
    assert _read(storage, source_key) == source_bytes
    assert _read(storage, caption_key) == caption_bytes
    assert len(first.captions) == 1
    assert first.captions[0].object_key.startswith(f"{first_prefix}/")
    assert _read(storage, first.captions[0].object_key) == caption_bytes

    first_bytes = {key: _read(storage, key) for key in first_keys}
    with pytest.raises(MediaProcessingError, match="already exists"):
        processor.process(
            storage=storage,
            version_id=uuid4(),
            purpose=MediaPurpose.VIDEO,
            source_key=source_key,
            content_type="video/mp4",
            crop=None,
            captions=(caption,),
            attempt_id=first_attempt,
        )
    assert {key: _read(storage, key) for key in first_keys} == first_bytes
    assert _read(storage, source_key) == source_bytes
    assert _read(storage, caption_key) == caption_bytes

    second = processor.process(
        storage=storage,
        version_id=uuid4(),
        purpose=MediaPurpose.VIDEO,
        source_key=source_key,
        content_type="video/mp4",
        crop=None,
        captions=(caption,),
        attempt_id=second_attempt,
    )
    second_prefix = f"{source_key}/attempts/{second_attempt}"
    second_keys, second_directory = _materialize_attempt(
        storage, prefix=second_prefix, destination=tmp_path / "second-attempt"
    )
    assert second_keys == set(second.object_keys)
    assert all(key.startswith(f"{second_prefix}/") for key in second_keys)
    assert first_keys.isdisjoint(second_keys)
    assert {key: _read(storage, key) for key in first_keys} == first_bytes
    assert _read(storage, source_key) == source_bytes
    assert _read(storage, caption_key) == caption_bytes
    assert len(second.captions) == 1
    assert second.captions[0].object_key.startswith(f"{second_prefix}/")
    assert _read(storage, second.captions[0].object_key) == caption_bytes

    for directory, result, prefix in (
        (first_directory, first, first_prefix),
        (second_directory, second, second_prefix),
    ):
        assert result.hls_manifest is not None
        # The master is materialized beneath the attempt directory; find it from
        # the result key so the assertion remains tied to the returned inventory.
        master = directory / result.hls_manifest.master_object_key.removeprefix(f"{prefix}/")
        assert master.is_file()
        _decode(master)
        progressive = next(item for item in result.renditions if item.protocol == "progressive")
        progressive_path = directory / progressive.object_key.removeprefix(f"{prefix}/")
        metadata = FFprobeVideoProbe()(progressive_path)
        assert (metadata.width, metadata.height) == (320, 180)
        assert metadata.duration_seconds == pytest.approx(1.25, abs=0.2)
        _decode(progressive_path)
