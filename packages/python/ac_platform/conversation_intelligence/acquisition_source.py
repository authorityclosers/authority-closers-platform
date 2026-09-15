"""Server-measured original upload admission through the existing native helper.

The API receives only the helper's validated files; it never decodes media or
holds Docker/provider credentials. Scratch is disposed by the caller after the
joined helper returns. This preflight is not a canonical C1 checkpoint: the
durable worker still publishes C0/C1 under its job lease.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal
from uuid import UUID

from ac_platform.conversation_intelligence.acquisition_sessions import MeasuredSource
from ac_platform.conversation_intelligence.application import ConversationError
from ac_platform.conversation_intelligence.checkpoints import content_hash
from ac_platform.conversation_intelligence.contracts import IntakeIntent
from ac_platform.conversation_intelligence.limits import MAX_AUDIO_BYTES
from ac_platform.conversation_intelligence.native_runtime import (
    HOSTED_C1_RATE,
    DockerNativeRuntime,
    NativeRuntime,
    NativeRuntimeError,
)
from ac_platform.conversation_intelligence.signals import _HEADER, MAX_SECONDS, file_sha256

AudioType = Literal["audio/mpeg", "audio/wav", "audio/ogg", "audio/flac", "audio/mp4"]


class NativePreflightTimeout(ConversationError):
    """The bounded upload admission window expired before native verification."""

    status = 408


def original_content_type(header: bytes) -> AudioType:
    # This allowlist selects a playback type. The isolated decoder must still
    # validate the complete source; a magic signature is never duration proof.
    if len(header) >= 12 and header[:4] in {b"RIFF", b"RF64"} and header[8:12] == b"WAVE":
        return "audio/wav"
    if header.startswith(b"OggS"):
        return "audio/ogg"
    if header.startswith(b"fLaC"):
        return "audio/flac"
    if len(header) >= 12 and header[4:8] == b"ftyp":
        return "audio/mp4"
    if header.startswith(b"ID3") or (
        len(header) >= 2 and header[0] == 255 and header[1] & 0xE0 == 0xE0
    ):
        return "audio/mpeg"
    raise ConversationError("Choose a supported original audio file.")


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
            raise ConversationError("Choose an audio file up to 32 MiB.")
        digest = file_sha256(path)
        if digest != expected_sha256:
            raise ConversationError("The uploaded file differs from the file you selected.")
        with path.open("rb") as stream:
            media_type = original_content_type(stream.read(64))
        destination = path.parent / "preflight"
        try:
            returned = self.runtime.inspect(
                path, destination, job_id=submission_id, rate=HOSTED_C1_RATE
            )
            payload = DockerNativeRuntime._validate_output(
                destination, source_sha256=digest, source_bytes=source_bytes
            )
            if content_hash(returned) != content_hash(payload):
                raise ValueError("measurement_envelope_differs")
            acoustics = payload["acoustics"]
            sample_count, channels = acoustics["sample_count"], acoustics["channels"]
            duration = payload["media_duration_ms"]
            with (destination / "features.aaf").open("rb") as features:
                header = _HEADER.unpack(features.read(_HEADER.size))
            if (
                type(sample_count) is not int
                or not 0 < sample_count <= HOSTED_C1_RATE * MAX_SECONDS
                or type(channels) is not int
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
