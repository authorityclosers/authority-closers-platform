"""Bounded metadata inspection of staged video bytes, never a remote URL.

This is a worker primitive, not a malware verdict or provider activation.
The worker host must still provide its reviewed process/container isolation.
"""

from __future__ import annotations

import json
import math
import re
import subprocess
from contextlib import suppress
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from threading import Thread
from typing import BinaryIO, Literal

from ac_platform.media.errors import MediaProcessingError

_MAX_PROBE_BYTES = 64 * 1024
_BINARY = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,80}\Z")


@dataclass(frozen=True, slots=True)
class VideoMetadata:
    """Square-pixel display dimensions after the source's rotation is applied."""

    width: int
    height: int
    duration_seconds: float

    def __post_init__(self) -> None:
        if (
            type(self.width) is not int
            or type(self.height) is not int
            or not 2 <= self.width <= 7680
            or not 2 <= self.height <= 7680
            or isinstance(self.duration_seconds, bool)
            or not isinstance(self.duration_seconds, (int, float))
            or not math.isfinite(self.duration_seconds)
            or self.duration_seconds <= 0
        ):
            raise MediaProcessingError("The video dimensions or duration are invalid.")


def parse_video_metadata(body: bytes) -> VideoMetadata:
    """Parse only selected ffprobe fields; malformed/ambiguous values fail closed."""

    try:
        if not 0 < len(body) <= _MAX_PROBE_BYTES:
            raise ValueError
        value = json.loads(body)
        streams = value["streams"]
        if not isinstance(streams, list) or len(streams) != 1:
            raise ValueError
        stream = streams[0]
        width, height = stream["width"], stream["height"]
        if type(width) is not int or type(height) is not int:
            raise ValueError
        if not 2 <= width <= 7680 or not 2 <= height <= 7680:
            raise ValueError
        sar = stream.get("sample_aspect_ratio", "1:1")
        # Unspecified SAR means square pixels in FFmpeg. Invalid ratios do not.
        if sar in {"N/A", "0:1"}:
            sar = "1:1"
        if not isinstance(sar, str) or re.fullmatch(r"[0-9]{1,5}:[0-9]{1,5}", sar) is None:
            raise ValueError
        numerator, denominator = (int(part) for part in sar.split(":"))
        ratio = Fraction(numerator, denominator)
        if not Fraction(1, 16) <= ratio <= 16:
            raise ValueError
        width = round(width * ratio)
        rotations = [
            item["rotation"] for item in stream.get("side_data_list", []) if "rotation" in item
        ]
        if len(rotations) > 1:
            raise ValueError
        rotation = rotations[0] if rotations else 0
        if type(rotation) is not int or rotation % 90:
            raise ValueError
        if rotation % 180:
            width, height = height, width
        raw_duration = value["format"]["duration"]
        if isinstance(raw_duration, bool) or not isinstance(raw_duration, (str, int, float)):
            raise ValueError
        return VideoMetadata(width, height, float(raw_duration))
    except (
        KeyError,
        TypeError,
        ValueError,
        ZeroDivisionError,
        OverflowError,
        RecursionError,
    ) as error:
        raise MediaProcessingError("The video metadata could not be verified.") from error


class FFprobeVideoProbe:
    def __init__(
        self, *, binary: str = "ffprobe", format_name: Literal["mpegts"] | None = None
    ) -> None:
        if _BINARY.fullmatch(binary) is None:
            raise ValueError("ffprobe binary must be a leaf executable name")
        if format_name not in {None, "mpegts"}:
            raise ValueError("only worker-owned MPEG-TS segments may force their container")
        self.binary = binary
        self.format_name = format_name

    def __call__(self, path: Path) -> VideoMetadata:
        if not path.is_absolute() or path.is_symlink() or not path.is_file():
            raise MediaProcessingError("The staged video is unavailable.")
        command = (
            self.binary,
            "-v",
            "error",
            "-protocol_whitelist",
            "file",
            "-format_whitelist",
            "mov,matroska,webm,mpegts",
            "-select_streams",
            "V:0",
            "-show_entries",
            "stream=width,height,sample_aspect_ratio:stream_side_data=rotation:format=duration",
            "-of",
            "json",
            *(("-f", self.format_name) if self.format_name is not None else ()),
            "-i",
            str(path),
        )
        process: subprocess.Popen[bytes] | None = None
        output = bytearray()
        overflow = False

        def drain(pipe: BinaryIO, *, capture: bool) -> None:
            nonlocal overflow
            size = 0
            while chunk := pipe.read(8192):
                size += len(chunk)
                if size > _MAX_PROBE_BYTES:
                    overflow = True
                    if process is not None:
                        with suppress(OSError):
                            process.kill()
                    return
                if capture:
                    output.extend(chunk)

        readers: list[Thread] = []
        try:
            process = subprocess.Popen(  # noqa: S603 - fixed local argv, no shell or URLs
                command,
                cwd=path.parent,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                shell=False,
            )
            assert process.stdout is not None and process.stderr is not None
            for pipe, capture in ((process.stdout, True), (process.stderr, False)):
                reader = Thread(
                    target=drain, args=(pipe,), kwargs={"capture": capture}, daemon=True
                )
                readers.append(reader)
                reader.start()
            result = process.wait(timeout=30)
            for reader in readers:
                reader.join(timeout=5)
            if overflow or result != 0 or any(reader.is_alive() for reader in readers):
                raise MediaProcessingError("The video metadata probe failed.")
            return parse_video_metadata(bytes(output))
        except (OSError, subprocess.SubprocessError) as error:
            # stderr can contain source paths and embedded media tags. Never surface it.
            raise MediaProcessingError("The video metadata probe failed.") from error
        finally:
            if process is not None:
                if process.poll() is None:
                    process.kill()
                    process.wait()
                for reader in readers:
                    reader.join(timeout=5)
                for output_pipe in (process.stdout, process.stderr):
                    if output_pipe is not None:
                        output_pipe.close()
