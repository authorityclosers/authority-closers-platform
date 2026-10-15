"""Server-measured original upload admission through the existing native helper.

The API receives only the helper's validated files; it never decodes media or
holds Docker/provider credentials. Scratch is disposed by the caller after the
joined helper returns. This preflight is not a canonical C1 checkpoint: the
durable worker still publishes C0/C1 under its job lease.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO
from uuid import UUID

from ac_platform.conversation_intelligence.acquisition_sessions import MeasuredSource
from ac_platform.conversation_intelligence.application import ConversationError
from ac_platform.conversation_intelligence.checkpoints import content_hash
from ac_platform.conversation_intelligence.contracts import AudioType, IntakeIntent
from ac_platform.conversation_intelligence.limits import MAX_AUDIO_BYTES
from ac_platform.conversation_intelligence.native_runtime import (
    HOSTED_C1_RATE,
    DockerNativeRuntime,
    NativeRuntime,
    NativeRuntimeError,
)
from ac_platform.conversation_intelligence.signals import _HEADER, MAX_SECONDS, file_sha256


class NativePreflightTimeout(ConversationError):
    """The bounded upload admission window expired before native verification."""

    status = 408


_ASF_HEADER = UUID("75b22630-668e-11cf-a6d9-00aa0062ce6c").bytes_le
_ASF_STREAM = UUID("b7dc0791-a9b7-11cf-8ee6-00c00c205365").bytes_le
_ASF_AUDIO = UUID("f8699e40-5b4d-11cf-a8fd-00805f5c442b").bytes_le
_ASF_VIDEO = UUID("bc19efc0-5b4d-11cf-a8fd-00805f5c442b").bytes_le
_ASF_EXTENSION = UUID("5fbf03b5-a92e-11cf-8ee3-00c00c205365").bytes_le
_ASF_METADATA = frozenset(
    UUID(value).bytes_le
    for value in (
        "44231c94-9498-49d1-a141-1d134e457054",  # Metadata Library
        "c5f8cbea-5baf-4877-8467-aa8c44fa4cca",  # Metadata
        "7c4346a9-efe0-4bfc-b229-393ede415c85",  # Language List
    )
)


def original_content_type(header: bytes) -> AudioType:
    # This allowlist selects a playback type. The isolated decoder must still
    # validate the complete source; a magic signature is never duration proof.
    if len(header) >= 12 and header[:4] in {b"RIFF", b"RF64"} and header[8:12] == b"WAVE":
        return "audio/wav"
    if header.startswith(b"OggS"):
        return "audio/ogg"
    if header.startswith(b"fLaC"):
        return "audio/flac"
    if header.startswith(b"caff"):
        return "audio/x-caf"
    if header.startswith(_ASF_HEADER):
        return "video/x-ms-asf"
    if header.startswith(b"#!AMR-WB\n"):
        return "audio/amr-wb"
    if header.startswith(b"#!AMR\n"):
        return "audio/amr"
    if len(header) >= 12 and header[:4] == b"FORM" and header[8:12] in {b"AIFF", b"AIFC"}:
        return "audio/aiff"
    if header.startswith(b"\x1a\x45\xdf\xa3") and b"\x42\x82\x84webm" in header:
        return "audio/webm"
    if header.startswith(b"\x1a\x45\xdf\xa3") and b"\x42\x82\x88matroska" in header:
        return "video/x-matroska"
    if len(header) >= 12 and header[4:8] == b"ftyp":
        if header[8:11] == b"3gp":
            return "audio/3gpp"
        if header[8:12] in {b"M4A ", b"M4B "}:
            return "audio/mp4"
        if header[8:12] == b"qt  ":
            return "video/quicktime"
        return "video/mp4"
    # Older QuickTime files can start with their movie/media atom, without ftyp.
    if len(header) >= 8 and header[4:8] in {b"moov", b"mdat", b"wide"}:
        return "video/quicktime"
    # ADTS shares MPEG's sync bits; its zero layer bits distinguish AAC.
    if len(header) >= 7 and header[0] == 255 and header[1] & 0xF6 == 0xF0:
        return "audio/aac"
    if header.startswith(b"ID3") or (
        len(header) >= 2 and header[0] == 255 and header[1] & 0xE0 == 0xE0
    ):
        return "audio/mpeg"
    raise ConversationError("Choose a supported audio or video file up to 100 MB.")


def _iso_track_handlers(path: Path) -> frozenset[bytes] | None:
    """Read bounded container metadata; decoding and duration stay native-owned.

    Skip media payloads rather than reading them into the API. A malformed or
    unrecognized layout returns unknown and still goes through native validation.
    """
    remaining = 2048
    found_movie = False
    handlers: set[bytes] = set()

    def boxes(stream: BinaryIO, start: int, end: int, depth: int) -> None:
        nonlocal remaining, found_movie
        if depth > 4:
            raise ValueError("container_depth")
        position = start
        while position < end:
            remaining -= 1
            if remaining < 0 or end - position < 8:
                raise ValueError("container_bounds")
            stream.seek(position)
            header = stream.read(8)
            size, kind = int.from_bytes(header[:4], "big"), header[4:8]
            prefix = 8
            if size == 1:
                extended = stream.read(8)
                if len(extended) != 8:
                    raise ValueError("container_bounds")
                size, prefix = int.from_bytes(extended, "big"), 16
            elif size == 0:
                size = end - position
            if size < prefix or position + size > end:
                raise ValueError("container_bounds")
            payload = position + prefix
            if kind in {b"moov", b"trak", b"mdia"}:
                if kind == b"moov":
                    found_movie = True
                boxes(stream, payload, position + size, depth + 1)
            elif kind == b"hdlr" and depth == 3:
                if size - prefix < 12:
                    raise ValueError("container_handler")
                stream.seek(payload + 8)
                handlers.add(stream.read(4))
            position += size

    try:
        with path.open("rb") as stream:
            boxes(stream, 0, path.stat().st_size, 0)
    except (OSError, ValueError):
        return None
    return frozenset(handlers) if found_movie else None


def _iso_sound_track(path: Path) -> bool | None:
    handlers = _iso_track_handlers(path)
    return b"soun" in handlers if handlers is not None else None


def _matroska_sound_track(path: Path) -> bool | None:
    """Inspect bounded EBML Tracks metadata without reading packet payloads."""
    remaining = 2048
    found_tracks = False
    found_audio = False

    def integer(stream: BinaryIO, *, identifier: bool) -> tuple[int, bool]:
        first = stream.read(1)
        if not first or not first[0]:
            raise ValueError("container_integer")
        width = 9 - first[0].bit_length()
        if width > (4 if identifier else 8):
            raise ValueError("container_integer")
        tail = stream.read(width - 1)
        if len(tail) != width - 1:
            raise ValueError("container_integer")
        encoded = int.from_bytes(first + tail, "big")
        value = encoded if identifier else encoded & ((1 << (7 * width)) - 1)
        return value, not identifier and value == (1 << (7 * width)) - 1

    def elements(stream: BinaryIO, start: int, end: int, depth: int) -> None:
        nonlocal remaining, found_tracks, found_audio
        if depth > 3:
            raise ValueError("container_depth")
        position = start
        while position < end:
            remaining -= 1
            if remaining < 0:
                raise ValueError("container_bounds")
            stream.seek(position)
            kind, _ = integer(stream, identifier=True)
            size, unknown = integer(stream, identifier=False)
            payload = stream.tell()
            if unknown:
                if kind != 0x18538067:
                    raise ValueError("container_unknown_size")
                size = end - payload
            if payload + size > end:
                raise ValueError("container_bounds")
            if kind in {0x18538067, 0x1654AE6B, 0xAE}:
                if kind == 0x1654AE6B:
                    found_tracks = True
                elements(stream, payload, payload + size, depth + 1)
            elif kind == 0x83 and depth == 3:
                if not 1 <= size <= 8:
                    raise ValueError("container_track_type")
                found_audio |= int.from_bytes(stream.read(size), "big") == 2
            position = payload + size

    try:
        with path.open("rb") as stream:
            elements(stream, 0, path.stat().st_size, 0)
    except (OSError, ValueError):
        return None
    return found_audio if found_tracks else None


def _asf_track_types(path: Path) -> frozenset[bytes] | None:
    """Read bounded ASF header objects; native decoding remains authoritative.

    Unknown nested or stream metadata stays unknown rather than asserting a
    missing sound track. Packet payloads and large metadata objects are skipped.
    """
    tracks: set[bytes] = set()
    uncertain = False
    remaining = 2048

    def objects(stream: BinaryIO, start: int, end: int, depth: int) -> int:
        nonlocal remaining, uncertain
        if depth > 1:
            raise ValueError("container_depth")
        position, count = start, 0
        while position < end:
            remaining -= 1
            if remaining < 0 or end - position < 24:
                raise ValueError("container_bounds")
            stream.seek(position)
            obj = stream.read(24)
            size = int.from_bytes(obj[16:24], "little")
            if len(obj) != 24 or size < 24 or position + size > end:
                raise ValueError("container_bounds")
            if obj[:16] == _ASF_STREAM:
                if size < 78:
                    raise ValueError("container_stream")
                kind = stream.read(16)
                if kind in {_ASF_AUDIO, _ASF_VIDEO}:
                    tracks.add(kind)
                else:
                    uncertain = True
            elif obj[:16] == _ASF_EXTENSION:
                if size < 46:
                    raise ValueError("container_extension")
                extension = stream.read(22)
                nested_size = int.from_bytes(extension[18:22], "little")
                if nested_size != size - 46:
                    raise ValueError("container_extension")
                objects(stream, position + 46, position + size, depth + 1)
            elif depth and obj[:16] not in _ASF_METADATA:
                # Extended stream properties can embed additional streams.
                # An unsupported nested layout must not imply missing audio.
                uncertain = True
            position += size
            count += 1
        return count

    try:
        with path.open("rb") as stream:
            header = stream.read(30)
            if len(header) != 30 or header[:16] != _ASF_HEADER:
                return None
            end = int.from_bytes(header[16:24], "little")
            count = int.from_bytes(header[24:28], "little")
            if not 30 <= end <= path.stat().st_size or not 0 < count <= 2048:
                return None
            if objects(stream, 30, end, 0) != count or uncertain:
                return None
    except (OSError, ValueError):
        return None
    return frozenset(tracks) if tracks else None


@dataclass(frozen=True)
class MeasuredUpload:
    source: MeasuredSource
    intent: IntakeIntent


@dataclass(frozen=True)
class NativeUploadPreflight:
    runtime: NativeRuntime

    def measure(self, path: Path, submission_id: UUID, expected_sha256: str) -> MeasuredUpload:
        if type(submission_id) is not UUID or not path.is_file() or path.is_symlink():
            raise ConversationError("The original upload is unavailable.")
        source_bytes = path.stat().st_size
        if source_bytes <= 0:
            raise ConversationError("The original upload is unavailable.")
        if source_bytes > MAX_AUDIO_BYTES:
            raise ConversationError("Choose an audio or video file up to 100 MB.")
        digest = file_sha256(path)
        if digest != expected_sha256:
            raise ConversationError("The uploaded file differs from the file you selected.")
        with path.open("rb") as stream:
            media_type = original_content_type(stream.read(4096))
        sound_track = None
        if media_type in {"audio/mp4", "audio/3gpp", "video/mp4", "video/quicktime", "video/3gpp"}:
            handlers = _iso_track_handlers(path)
            sound_track = b"soun" in handlers if handlers is not None else None
            if media_type in {"audio/3gpp", "video/3gpp"} and handlers is not None:
                media_type = "video/3gpp" if b"vide" in handlers else "audio/3gpp"
        elif media_type in {"audio/webm", "video/x-matroska"}:
            sound_track = _matroska_sound_track(path)
        elif media_type == "video/x-ms-asf":
            tracks = _asf_track_types(path)
            if tracks is not None:
                sound_track = _ASF_AUDIO in tracks
                if _ASF_VIDEO not in tracks and sound_track:
                    media_type = "audio/x-ms-wma"
        if sound_track is False:
            raise ConversationError("This file has no sound track.")
        destination = path.parent / "preflight"
        try:
            validate_source = getattr(self.runtime, "validate_source", None)
            if callable(validate_source):
                returned = validate_source(
                    path, destination, job_id=submission_id, rate=HOSTED_C1_RATE
                )
                payload = DockerNativeRuntime._validate_source_output(
                    destination, source_sha256=digest, source_bytes=source_bytes
                )
                decoded = payload["decoded"]
                sample_count, channels = (
                    decoded["sample_count"],
                    decoded["channels"],
                )
            else:
                returned = self.runtime.inspect(
                    path, destination, job_id=submission_id, rate=HOSTED_C1_RATE
                )
                payload = DockerNativeRuntime._validate_output(
                    destination, source_sha256=digest, source_bytes=source_bytes
                )
                acoustics = payload["acoustics"]
                sample_count, channels = acoustics["sample_count"], acoustics["channels"]
            if content_hash(returned) != content_hash(payload):
                raise ValueError("measurement_envelope_differs")
            duration = payload["media_duration_ms"]
            if type(sample_count) is not int or type(channels) is not int:
                raise ValueError("measurement_duration_differs")
            if callable(validate_source):
                if not (
                    0 < sample_count <= HOSTED_C1_RATE * MAX_SECONDS
                    and channels in (1, 2)
                    and type(duration) is int
                    and duration == round(sample_count * 1000 / HOSTED_C1_RATE)
                    and 0 < duration <= MAX_SECONDS * 1000
                ):
                    raise ValueError("measurement_duration_differs")
            else:
                with (destination / "features.aaf").open("rb") as features:
                    header = _HEADER.unpack(features.read(_HEADER.size))
                if (
                    not 0 < sample_count <= HOSTED_C1_RATE * MAX_SECONDS
                    or channels not in (1, 2)
                    or header[1:4] != (HOSTED_C1_RATE, channels, sample_count)
                    or type(duration) is not int
                    or duration != round(sample_count * 1000 / HOSTED_C1_RATE)
                    or not 0 < duration <= MAX_SECONDS * 1000
                ):
                    raise ValueError("measurement_duration_differs")
        except NativeRuntimeError as error:
            if error.code == "native_runtime_timeout":
                raise NativePreflightTimeout(
                    "The recording took too long to verify before the upload window expired."
                ) from None
            raise ConversationError(
                "The audio length could not be verified. Try another file."
            ) from None
        except (ValueError, KeyError, TypeError, OSError):
            raise ConversationError(
                "The audio length could not be verified. Try another file."
            ) from None
        # Include the complete canonical helper receipt's digest, not browser
        # duration, filesystem mtime, or the container's nominal metadata length.
        measured = MeasuredSource(submission_id, digest, duration, content_hash(payload))
        return MeasuredUpload(
            measured,
            IntakeIntent(
                source_sha256=digest,
                source_bytes=source_bytes,
                content_type=media_type,
                duration_ms=duration,
                purpose="internal_analysis",
            ),
        )
