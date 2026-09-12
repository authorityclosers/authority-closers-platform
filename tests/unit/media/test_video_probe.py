from __future__ import annotations

import io
import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from ac_platform.media.errors import MediaProcessingError
from ac_platform.media.video_probe import FFprobeVideoProbe, VideoMetadata, parse_video_metadata


def metadata(**stream: object) -> bytes:
    return json.dumps(
        {
            "streams": [{"width": 1920, "height": 1080, "sample_aspect_ratio": "1:1", **stream}],
            "format": {"duration": "12.5"},
        }
    ).encode()


def test_probe_parses_display_geometry_and_duration() -> None:
    assert parse_video_metadata(metadata()) == VideoMetadata(1920, 1080, 12.5)
    assert parse_video_metadata(metadata(side_data_list=[{"rotation": -90}])) == VideoMetadata(
        1080, 1920, 12.5
    )
    assert parse_video_metadata(metadata(width=1440, sample_aspect_ratio="4:3")) == VideoMetadata(
        1920, 1080, 12.5
    )


@pytest.mark.parametrize(
    "patch",
    [
        {"width": True},
        {"height": "1080"},
        {"width": 0},
        {"width": 8000},
        {"sample_aspect_ratio": "1:0"},
        {"sample_aspect_ratio": "1:99"},
        {"sample_aspect_ratio": []},
        {"sample_aspect_ratio": "NaN"},
        {"side_data_list": [{"rotation": 23}]},
        {"side_data_list": [{"rotation": 90.0}]},
        {"side_data_list": [{"rotation": 90}, {"rotation": 180}]},
    ],
)
def test_probe_rejects_invalid_geometry(patch: dict[str, object]) -> None:
    with pytest.raises(MediaProcessingError):
        parse_video_metadata(metadata(**patch))


@pytest.mark.parametrize(
    "body",
    [
        b"",
        b"not json",
        b"[]",
        b"{}",
        b"x" * 65537,
        b'{"streams":[],"format":{"duration":"1"}}',
        metadata().replace(b'"12.5"', b'"NaN"'),
        metadata().replace(b'"12.5"', b'"Infinity"'),
        metadata().replace(b'"12.5"', b'"0"'),
        metadata().replace(b'"12.5"', b"true"),
    ],
    ids=[
        "empty",
        "invalid-json",
        "array",
        "missing",
        "oversize",
        "no-video",
        "nan",
        "infinite",
        "zero",
        "boolean",
    ],
)
def test_probe_rejects_invalid_or_unbounded_metadata(body: bytes) -> None:
    with pytest.raises(MediaProcessingError):
        parse_video_metadata(body)


@pytest.mark.parametrize("binary", ["../ffprobe", "ffprobe --help", "C:/ffprobe.exe", "-x", ""])
def test_probe_executable_is_a_leaf_name(binary: str) -> None:
    with pytest.raises(ValueError):
        FFprobeVideoProbe(binary=binary)


@pytest.mark.parametrize("mode", ["success", "stderr", "stdout", "nonzero", "timeout"])
def test_probe_process_boundaries(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, mode: str
) -> None:
    source = tmp_path / "source.bin"
    source.write_bytes(b"synthetic")
    calls: list[tuple[object, dict[str, Any]]] = []

    class Process:
        stdout = io.BytesIO(b"x" * 65537 if mode == "stdout" else metadata())
        stderr = io.BytesIO(b"private-source-label" * 4000 if mode == "stderr" else b"")
        killed = False

        def wait(self, timeout: int | None = None) -> int:
            if mode == "timeout" and not self.killed:
                raise subprocess.TimeoutExpired("probe", timeout or 30)
            return 1 if mode == "nonzero" else 0

        def kill(self) -> None:
            self.killed = True

        def poll(self) -> int | None:
            return None if mode == "timeout" and not self.killed else 0

    process = Process()

    def popen(command: object, **kwargs: Any) -> Process:
        calls.append((command, kwargs))
        return process

    monkeypatch.setattr(subprocess, "Popen", popen)
    if mode == "success":
        assert FFprobeVideoProbe()(source) == VideoMetadata(1920, 1080, 12.5)
    else:
        with pytest.raises(MediaProcessingError) as caught:
            FFprobeVideoProbe()(source)
        assert "private-source-label" not in str(caught.value)
    command, kwargs = calls[0]
    assert isinstance(command, tuple)
    assert command[command.index("-protocol_whitelist") + 1] == "file"
    assert command[command.index("-format_whitelist") + 1] == "mov,matroska,webm,mpegts"
    assert command[-1] == str(source)
    assert kwargs["shell"] is False and kwargs["stdin"] == subprocess.DEVNULL
    assert process.stdout.closed and process.stderr.closed
    if mode in {"timeout", "stdout", "stderr"}:
        assert process.killed
