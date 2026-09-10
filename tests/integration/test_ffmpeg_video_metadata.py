"""Real local encoder checks. No database, network, learner content or activation."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from uuid import uuid4

import pytest

from ac_platform.media.models import MediaPurpose
from ac_platform.media.processing import FFmpegMediaProcessor, ProcessingQuota, TranscodeProfile
from ac_platform.media.signing import MediaSigner
from ac_platform.media.storage import InMemoryPrivateObjectStorage
from ac_platform.media.video_file_storage import VideoFileStorage
from ac_platform.media.video_probe import FFprobeVideoProbe


@pytest.mark.skipif(
    not shutil.which("ffmpeg") or not shutil.which("ffprobe"), reason="requires FFmpeg + ffprobe"
)
@pytest.mark.parametrize(
    ("width", "height", "variant"),
    [
        (320, 180, "plain"),
        (180, 320, "plain"),
        (320, 180, "rotated"),
        (240, 180, "anamorphic"),
        (320, 180, "audio"),
        (320, 180, "audio-tail"),
        (320, 180, "low-fps"),
    ],
)
@pytest.mark.parametrize("storage_kind", ["memory", "private-files"])
def test_real_encoder_emits_playable_correctly_sized_ladder(
    tmp_path: Path, width: int, height: int, variant: str, storage_kind: str
) -> None:
    source = tmp_path / "synthetic.mp4"
    subprocess.run(  # noqa: S603 - fixed synthetic local test source
        [  # noqa: S607 - executable on the test host's controlled PATH
            "ffmpeg",
            "-nostdin",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            f"color=c=blue:s={width}x{height}:r={1 if variant == 'low-fps' else 24}:d=1.5",
            *(
                [
                    "-f",
                    "lavfi",
                    "-i",
                    f"sine=frequency=440:duration={3 if variant == 'audio-tail' else 1.5}",
                    "-c:a",
                    "aac",
                ]
                if variant in {"audio", "audio-tail"}
                else []
            ),
            *(["-vf", "setsar=4/3"] if variant == "anamorphic" else []),
            "-c:v",
            "libx264",
            "-threads",
            "1",
            "-pix_fmt",
            "yuv420p",
            str(source),
        ],
        check=True,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        timeout=30,
    )
    if variant == "rotated":
        rotated = tmp_path / "rotated.mp4"
        subprocess.run(  # noqa: S603 - fixed local metadata-only test fixture
            [  # noqa: S607 - executable on the test host's controlled PATH
                "ffmpeg",
                "-nostdin",
                "-v",
                "error",
                "-display_rotation:v:0",
                "90",
                "-i",
                str(source),
                "-c",
                "copy",
                str(rotated),
            ],
            check=True,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            timeout=30,
        )
        source = rotated
        width, height = height, width
    elif variant == "anamorphic":
        width = round(width * 4 / 3)
    assert (FFprobeVideoProbe()(source).width, FFprobeVideoProbe()(source).height) == (
        width,
        height,
    )
    storage = (
        VideoFileStorage(
            root=tmp_path / "video-objects",
            max_object_bytes=10 * 1024**2,
            max_store_bytes=32 * 1024**2,
        )
        if storage_kind == "private-files"
        else InMemoryPrivateObjectStorage(MediaSigner("real-encoder-synthetic-test-32-bytes!!"))
    )
    key = f"tenants/{uuid4()}/media/video/{uuid4()}/{uuid4()}/original"
    storage.put(object_key=key, body=source.read_bytes(), content_type="video/mp4")
    result = FFmpegMediaProcessor(
        profiles=(
            TranscodeProfile("144p", 256, 144, 100),
            TranscodeProfile("360p", 640, 360, 300),
            TranscodeProfile("720p", 1280, 720, 800),
        ),
        quota=ProcessingQuota(
            max_source_bytes=1024**2,
            max_output_bytes=10 * 1024**2,
            max_temp_bytes=16 * 1024**2,
            max_duration_seconds=5,
        ),
    ).process(
        storage=storage,
        version_id=uuid4(),
        purpose=MediaPurpose.VIDEO,
        source_key=key,
        content_type="video/mp4",
        crop=None,
    )
    assert (result.width, result.height) == (width, height)
    expected_duration = {"low-fps": 2.0, "audio-tail": 3.0}.get(variant, 1.5)
    assert result.duration_seconds == pytest.approx(expected_duration, abs=0.1)
    assert result.hls_manifest is not None
    assert len(result.hls_manifest.renditions) == 2  # duplicate upscaled tiers are absent
    master = storage.read(result.hls_manifest.master_object_key).decode()
    for profile in result.hls_manifest.renditions:
        assert profile.width <= width and profile.height <= height
        assert f"RESOLUTION={profile.width}x{profile.height}" in master
    progressive = next(r for r in result.renditions if r.protocol == "progressive")
    assert (progressive.width, progressive.height) == (width, height)
    encoded = tmp_path / "encoded.mp4"
    encoded.write_bytes(storage.read(progressive.object_key))
    assert FFprobeVideoProbe()(encoded).duration_seconds == pytest.approx(
        expected_duration, abs=0.1
    )
    if variant in {"audio", "audio-tail"}:
        audio_probe = subprocess.run(  # noqa: S603 - generated local output only
            [  # noqa: S607 - controlled test-host executable
                "ffprobe",
                "-v",
                "error",
                "-select_streams",
                "a:0",
                "-show_entries",
                "stream=duration",
                "-of",
                "json",
                str(encoded),
            ],
            check=True,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            timeout=30,
        )
        assert float(json.loads(audio_probe.stdout)["streams"][0]["duration"]) == pytest.approx(
            expected_duration, abs=0.1
        )
    subprocess.run(  # noqa: S603 - decode only generated local bytes
        [  # noqa: S607 - executable on the test host's controlled PATH
            "ffmpeg",
            "-nostdin",
            "-v",
            "error",
            "-protocol_whitelist",
            "file",
            "-i",
            str(encoded),
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
