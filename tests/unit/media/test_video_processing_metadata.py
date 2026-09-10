from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest

from ac_platform.media.errors import MediaProcessingError, MediaQuotaExceeded
from ac_platform.media.models import MediaPurpose
from ac_platform.media.processing import FFmpegMediaProcessor, ProcessingQuota, TranscodeProfile
from ac_platform.media.signing import MediaSigner
from ac_platform.media.storage import InMemoryPrivateObjectStorage
from ac_platform.media.video_probe import VideoMetadata


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        (VideoMetadata(1920, 1080, 10), [(640, 360), (1280, 720), (1920, 1080)]),
        (VideoMetadata(320, 180, 10), [(320, 180)]),
        (VideoMetadata(1080, 1920, 10), [(202, 360), (404, 720), (606, 1080)]),
        (VideoMetadata(1000, 1000, 10), [(360, 360), (720, 720), (1000, 1000)]),
    ],
)
def test_ladder_fits_source_without_duplicate_or_upscaled_sizes(
    source: VideoMetadata, expected: list[tuple[int, int]]
) -> None:
    processor = FFmpegMediaProcessor()
    assert [(p.width, p.height) for p in processor._source_profiles(source)] == expected


@pytest.mark.parametrize("profiles", [(), (TranscodeProfile("x", 640, 360, 800),) * 2])
def test_ladder_requires_unique_bounded_profile_names(
    profiles: tuple[TranscodeProfile, ...],
) -> None:
    with pytest.raises(ValueError):
        FFmpegMediaProcessor(profiles=profiles)


@pytest.mark.parametrize("failure", ["long-source", "cut-output", "wrong-shape", "bad-progressive"])
def test_worker_rejects_partial_or_mislabeled_video_and_cleans_outputs(failure: str) -> None:
    storage = InMemoryPrivateObjectStorage(MediaSigner("metadata-test-signer-32-byte-value!!"))
    source_key = "tenants/tenant/media/video/asset/version/original"
    storage.put(object_key=source_key, body=b"synthetic", content_type="video/mp4")
    commands: list[tuple[str, ...]] = []

    def probe(path: Path) -> VideoMetadata:
        if failure == "long-source" and path.name == "source.bin":
            return VideoMetadata(640, 360, 31)
        if failure == "wrong-shape" and path.suffix == ".ts":
            return VideoMetadata(638, 360, 6)
        if failure == "bad-progressive" and path.suffix == ".mp4":
            return VideoMetadata(640, 360, 1)
        return VideoMetadata(640, 360, 6)

    def runner(command: tuple[str, ...], cwd: Path) -> None:
        del cwd
        commands.append(command)
        destination = Path(command[-1])
        if destination.suffix == ".m3u8":
            duration = 1 if failure == "cut-output" else 6
            destination.write_text(
                f"#EXTM3U\n#EXTINF:{duration},\nsegment-00000.ts\n#EXT-X-ENDLIST\n"
            )
            destination.with_name("segment-00000.ts").write_bytes(b"encoded")
        else:
            destination.write_bytes(b"encoded")

    with pytest.raises((MediaProcessingError, MediaQuotaExceeded)):
        FFmpegMediaProcessor(
            profiles=(TranscodeProfile("360p", 640, 360, 800),),
            command_runner=runner,
            video_probe=probe,
            quota=ProcessingQuota(
                max_source_bytes=100, max_output_bytes=10000, max_duration_seconds=30
            ),
        ).process(
            storage=storage,
            version_id=uuid4(),
            purpose=MediaPurpose.VIDEO,
            source_key=source_key,
            content_type="video/mp4",
            crop=None,
        )
    assert storage.list_prefix(source_key) == (source_key,)
    if failure == "long-source":
        assert commands == []


@pytest.mark.parametrize("duration", [None, 3.5])
def test_commands_encode_compatible_pixels_with_network_inputs_disabled(
    duration: float | None,
) -> None:
    worker = FFmpegMediaProcessor()
    commands = [
        worker.build_hls_command(
            input_path=Path("source.bin"),
            playlist_path=Path("index.m3u8"),
            segment_pattern=Path("segment-%05d.ts"),
            profile=TranscodeProfile("square", 360, 360, 800),
            max_duration_seconds=duration,
        ),
        worker.build_progressive_command(
            input_path=Path("source.bin"),
            output_path=Path("progressive.mp4"),
            dimensions=(640, 360),
            max_duration_seconds=duration,
        ),
    ]
    for command in commands:
        assert command[command.index("-protocol_whitelist") + 1] == "file"
        assert command[command.index("-format_whitelist") + 1] == "mov,matroska,webm"
        assert command[command.index("-pix_fmt") + 1] == "yuv420p"
        assert "setsar=1" in command[command.index("-vf") + 1]
        assert "0:V:0" in command and "0:a:0?" in command
        if duration is None:
            assert "tpad" not in command[command.index("-vf") + 1]
        else:
            assert command[command.index("-t") + 1] == str(duration)
            assert (
                f"tpad=stop_mode=clone:stop_duration={duration}"
                in command[command.index("-vf") + 1]
            )
