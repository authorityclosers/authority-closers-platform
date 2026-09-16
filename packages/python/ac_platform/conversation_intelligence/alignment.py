"""Pure C3 source-clock alignment checks for the local AudioAtlas checkpoint.

This module deliberately stops at source and timing support.  It does not read a
feature file, assign a speaker to a physical channel, or turn measurements into
emotion, skill, or sales conclusions.  C1's decoded clock and C2's native
transcript clock are kept explicit so an uncertain mapping cannot be mistaken
for an attribution result.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, NoReturn

from .checkpoints import content_hash, require_sha256
from .signals import NATIVE_SOURCE_SHA256

ALIGNMENT_SCHEMA = "ac.sales-xray.alignment-checkpoint/1"
_SIGNAL_SCHEMA = "ac.sales-xray.signal-checkpoint/1"
_AUDIOATLAS_PROFILE = "audioatlas-native-0.1-40ms-10ms"
_AUDIOATLAS_SUPPORT = "[start_sample, start_sample + valid_samples); attribution needs full windows"
_MAX_SOURCE_BYTES = 128 * 1024 * 1024
_MAX_DURATION_MS = 7_200_000
_MAX_SEGMENTS = 2_000
_KNOWN_TRANSCRIPT_TIMEBASES = frozenset(
    {
        "decoded_audio_track",
        "elevenlabs-scribe-native-seconds",
        "deepgram-native-seconds",
    }
)


class AlignmentError(ValueError):
    """Stable, non-content-bearing failure from the C3 source-clock validator."""


def _fail(code: str) -> NoReturn:
    raise AlignmentError(code)


def _object(value: Any, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        _fail(f"alignment_{field}_invalid")
    return value


def _text(value: Any, field: str, *, maximum: int = 512) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        _fail(f"alignment_{field}_invalid")
    return value


def _digest(value: Any, field: str) -> str:
    try:
        return require_sha256(value, field)
    except ValueError:
        _fail(f"alignment_{field}_invalid")


def _integer(value: Any, field: str, *, minimum: int = 0, maximum: int | None = None) -> int:
    if type(value) is not int or value < minimum or (maximum is not None and value > maximum):
        _fail(f"alignment_{field}_invalid")
    return value


def _boolean(value: Any, field: str) -> bool:
    if type(value) is not bool:
        _fail(f"alignment_{field}_invalid")
    return value


def _finite_number(value: Any, field: str) -> float:
    if type(value) not in {int, float} or not math.isfinite(float(value)):
        _fail(f"alignment_{field}_invalid")
    return float(value)


@dataclass(frozen=True, slots=True)
class _SignalInfo:
    source_sha256: str
    source_bytes: int
    duration_ms: int
    feature_sha256: str
    rate: int
    channels: int
    sample_count: int
    window_samples: int
    hop_samples: int
    native_source_sha256: str
    mapping_status: str
    source_timebase: dict[str, Any]


@dataclass(frozen=True, slots=True)
class _TranscriptSegment:
    segment_id: str
    speaker_id: str
    start_ms: int
    end_ms: int


@dataclass(frozen=True, slots=True)
class _TranscriptInfo:
    source_sha256: str
    revision: str
    timebase_id: str
    duration_ms: int
    duration_declared: bool
    segments: tuple[_TranscriptSegment, ...]


def _validate_audioatlas(signal_payload: dict[str, Any]) -> _SignalInfo:
    if signal_payload.get("schema") != _SIGNAL_SCHEMA:
        _fail("alignment_signal_schema_invalid")
    if signal_payload.get("stage") != "C1":
        _fail("alignment_signal_stage_invalid")

    source_sha256 = _digest(signal_payload.get("source_sha256"), "source_sha256")
    source_bytes = _integer(
        signal_payload.get("source_bytes"),
        "source_bytes",
        minimum=1,
        maximum=_MAX_SOURCE_BYTES,
    )
    duration_ms = _integer(
        signal_payload.get("media_duration_ms"),
        "media_duration_ms",
        minimum=1,
        maximum=_MAX_DURATION_MS,
    )
    feature_sha256 = _digest(signal_payload.get("feature_sha256"), "feature_sha256")

    acoustics = _object(signal_payload.get("acoustics"), "acoustics")
    if acoustics.get("format") != "ac.audioatlas.features/1":
        _fail("alignment_acoustics_format_invalid")
    rate = _integer(acoustics.get("rate"), "acoustics_rate", minimum=8_000, maximum=96_000)
    channels = _integer(acoustics.get("channels"), "acoustics_channels", minimum=1, maximum=2)
    sample_count = _integer(acoustics.get("sample_count"), "acoustics_sample_count", minimum=1)
    if sample_count > rate * 1_800:
        _fail("alignment_acoustics_duration_invalid")
    rows = _integer(acoustics.get("rows"), "acoustics_rows", minimum=1)
    window_samples = rate * 40 // 1_000
    hop_samples = rate * 10 // 1_000
    expected_rows = ((sample_count + hop_samples - 1) // hop_samples) * channels
    if (
        acoustics.get("source_sha256") != source_sha256
        or acoustics.get("clock") != "decoded_audio_track"
        or acoustics.get("profile") != _AUDIOATLAS_PROFILE
        or acoustics.get("support") != _AUDIOATLAS_SUPPORT
        or acoustics.get("window_samples") != window_samples
        or acoustics.get("hop_samples") != hop_samples
        or rows != expected_rows
        or acoustics.get("window_ms") not in (None, 40)
        or acoustics.get("hop_ms") not in (None, 10)
    ):
        _fail("alignment_acoustics_metadata_invalid")
    if acoustics.get("feature_sha256") != feature_sha256:
        _fail("alignment_feature_hash_mismatch")

    expected_duration_ms = round(sample_count / rate * 1_000)
    if duration_ms != expected_duration_ms:
        _fail("alignment_duration_mismatch")

    native_receipt = _object(signal_payload.get("native_receipt"), "native_receipt")
    native_source_sha256 = _digest(native_receipt.get("source_sha256"), "native_source_sha256")
    if (
        native_source_sha256 != NATIVE_SOURCE_SHA256
        or native_receipt.get("mode") != "fft"
        or native_receipt.get("rows") != rows
    ):
        _fail("alignment_native_provenance_invalid")
    _digest(native_receipt.get("binary_sha256"), "native_binary_sha256")

    timebase = _object(signal_payload.get("timebase"), "timebase")
    source_rate = _integer(
        timebase.get("source_sample_rate"),
        "source_sample_rate",
        minimum=1_000,
        maximum=384_000,
    )
    if (
        timebase.get("clock") != "decoded_audio_track"
        or timebase.get("rate") != rate
        or timebase.get("sample_zero") != 0
        or timebase.get("sample_to_seconds") != {"numerator": 1, "denominator": rate}
        or timebase.get("nominal_source_samples_per_decoded_sample")
        != {
            "numerator": source_rate,
            "denominator": rate,
        }
        or timebase.get("silence_removed") is not False
        or timebase.get("gain_normalized") is not False
        or timebase.get("denoised") is not False
        or timebase.get("container_video_sync_certified") is not False
        or timebase.get("source_mapping_status")
        != "uncertified_codec_delay_origin_and_discontinuities"
    ):
        _fail("alignment_timebase_metadata_invalid")
    if signal_payload.get("source_rate") != source_rate:
        _fail("alignment_source_rate_mismatch")
    if signal_payload.get("source_channels") != channels:
        _fail("alignment_source_channels_mismatch")
    if timebase["nominal_source_samples_per_decoded_sample"] != {
        "numerator": source_rate,
        "denominator": rate,
    }:
        _fail("alignment_timebase_metadata_invalid")
    _boolean(timebase.get("resampled"), "resampled")
    start_seconds = timebase.get("source_track_start_seconds")
    if start_seconds is not None:
        _finite_number(start_seconds, "source_track_start_seconds")
    source_track_time_base = timebase.get("source_track_time_base")
    if source_track_time_base is not None:
        _text(source_track_time_base, "source_track_time_base", maximum=128)

    compatibility = _object(signal_payload.get("compatibility"), "compatibility")
    audioatlas = _object(compatibility.get("audioatlas"), "audioatlas_compatibility")
    if (
        audioatlas.get("window_ms") != 40
        or audioatlas.get("hop_ms") != 10
        or audioatlas.get("join") != "full_support"
        or compatibility.get("interchangeable") is not False
    ):
        _fail("alignment_audioatlas_provenance_invalid")

    return _SignalInfo(
        source_sha256=source_sha256,
        source_bytes=source_bytes,
        duration_ms=duration_ms,
        feature_sha256=feature_sha256,
        rate=rate,
        channels=channels,
        sample_count=sample_count,
        window_samples=window_samples,
        hop_samples=hop_samples,
        native_source_sha256=native_source_sha256,
        mapping_status=str(timebase["source_mapping_status"]),
        source_timebase={
            "clock": "decoded_audio_track",
            "rate": rate,
            "sample_zero": 0,
            "sample_to_seconds": {"numerator": 1, "denominator": rate},
            "source_rate": source_rate,
            "source_track_start_seconds": start_seconds,
            "source_track_time_base": source_track_time_base,
            "resampled": bool(timebase["resampled"]),
            "silence_removed": False,
            "gain_normalized": False,
            "denoised": False,
            "source_mapping_status": str(timebase["source_mapping_status"]),
            "container_video_sync_certified": False,
        },
    )


def _validate_transcript(transcript: dict[str, Any], signal: _SignalInfo) -> _TranscriptInfo:
    source_sha256 = _digest(transcript.get("source_sha256"), "transcript_source_sha256")
    if source_sha256 != signal.source_sha256:
        _fail("alignment_source_mismatch")
    revision = _text(transcript.get("revision"), "transcript_revision", maximum=256)
    timebase_id = _text(transcript.get("timebase_id"), "transcript_timebase_id", maximum=256)
    if timebase_id not in _KNOWN_TRANSCRIPT_TIMEBASES:
        _fail("alignment_transcript_timebase_invalid")
    declared_clock = transcript.get("clock")
    if declared_clock is not None:
        declared_clock = _text(declared_clock, "transcript_clock", maximum=128)
        if declared_clock not in _KNOWN_TRANSCRIPT_TIMEBASES:
            _fail("alignment_transcript_clock_invalid")
        if declared_clock != timebase_id:
            _fail("alignment_transcript_clock_ambiguous")
    if transcript.get("alignment_to_audioatlas", "unverified") != "unverified":
        _fail("alignment_claimed_audioatlas_certification")
    if (
        transcript.get("speaker_identity", "unverified_provider_labels")
        != "unverified_provider_labels"
    ):
        _fail("alignment_claimed_speaker_identity")

    duration_value = transcript.get("duration_ms")
    duration_declared = duration_value is not None
    if duration_declared:
        duration = _integer(duration_value, "transcript_duration_ms", minimum=1)
        if duration != signal.duration_ms:
            _fail("alignment_duration_mismatch")
    else:
        # scribe_transcript() intentionally leaves C1's actual media duration to
        # the coordinator.  C1 is authoritative here; no duration is invented.
        duration = signal.duration_ms

    raw_segments = transcript.get("segments")
    if not isinstance(raw_segments, list) or len(raw_segments) > _MAX_SEGMENTS:
        _fail("alignment_segments_invalid")
    segments: list[_TranscriptSegment] = []
    seen: set[str] = set()
    previous_start = -1
    for raw in raw_segments:
        segment = _object(raw, "segment")
        segment_id = _text(segment.get("id"), "segment_id", maximum=128)
        speaker_id = _text(segment.get("speaker_id"), "speaker_id", maximum=128)
        text = segment.get("text")
        if not isinstance(text, str) or not text.strip() or len(text) > 20_000:
            _fail("alignment_segment_text_invalid")
        start_ms = _integer(segment.get("start_ms"), "segment_start_ms")
        end_ms = _integer(segment.get("end_ms"), "segment_end_ms")
        if segment_id in seen:
            _fail("alignment_duplicate_segment_id")
        if start_ms < previous_start:
            _fail("alignment_segments_out_of_order")
        if not start_ms < end_ms <= duration:
            _fail("alignment_segment_bounds_invalid")
        seen.add(segment_id)
        previous_start = start_ms
        segments.append(_TranscriptSegment(segment_id, speaker_id, start_ms, end_ms))
    return _TranscriptInfo(
        source_sha256=source_sha256,
        revision=revision,
        timebase_id=timebase_id,
        duration_ms=duration,
        duration_declared=duration_declared,
        segments=tuple(segments),
    )


def _candidate_window_count(
    segment: _TranscriptSegment,
    *,
    rate: int,
    window_samples: int,
    hop_samples: int,
    sample_count: int,
) -> int:
    """Count C1 full-window candidates without reading or recreating features."""

    count = 0
    for index in range((sample_count + hop_samples - 1) // hop_samples):
        start_sample = index * hop_samples
        end_sample = start_sample + window_samples
        if end_sample > sample_count:
            break
        # Compare in integer sample-clock space; segment times remain literal C2 ms.
        if (
            start_sample * 1_000 >= segment.start_ms * rate
            and end_sample * 1_000 <= segment.end_ms * rate
        ):
            count += 1
    return count


def build_alignment(signal_payload: dict[str, Any], transcript: dict[str, Any]) -> dict[str, Any]:
    """Build a deterministic, source-bound C3 alignment support record.

    The returned record carries only C1 metadata and C2 segment references.  A
    provider-native Scribe clock is retained as unmapped, so its intervals do
    not receive AudioAtlas measurements or physical-channel assignments.
    """

    signal = _validate_audioatlas(signal_payload)
    native_transcript = _validate_transcript(transcript, signal)
    shared_decoded_clock = native_transcript.timebase_id == "decoded_audio_track"
    if shared_decoded_clock:
        mapping_status = "decoded_clock_shared_source_origin_unverified"
        mapping_reason = (
            "Both artifacts name the decoded audio clock, but codec delay, origin, "
            "and discontinuities are not certified."
        )
    else:
        mapping_status = "provider_native_clock_unmapped_to_decoded_audio_track"
        mapping_reason = (
            "Scribe native seconds have no certified mapping to the AudioAtlas decoded "
            "audio-track clock."
        )

    normalized_segments: list[dict[str, Any]] = []
    for segment in native_transcript.segments:
        overlap = any(
            other.segment_id != segment.segment_id
            and other.start_ms < segment.end_ms
            and segment.start_ms < other.end_ms
            for other in native_transcript.segments
        )
        candidate_count = (
            _candidate_window_count(
                segment,
                rate=signal.rate,
                window_samples=signal.window_samples,
                hop_samples=signal.hop_samples,
                sample_count=signal.sample_count,
            )
            if shared_decoded_clock
            else None
        )
        normalized_segments.append(
            {
                "segment_id": segment.segment_id,
                "speaker_id": segment.speaker_id,
                "speaker_identity": "unverified_provider_label",
                "start_ms": segment.start_ms,
                "end_ms": segment.end_ms,
                "overlap_present": overlap,
                "support": {
                    "status": (
                        "candidate_full_window_support"
                        if shared_decoded_clock
                        else "unavailable_clock_mapping"
                    ),
                    "candidate_full_window_count": candidate_count,
                    "window_ms": 40,
                    "hop_ms": 10,
                },
                "channel": None,
                "channel_mapping": "unverified_no_assignment",
                "attribution_status": "abstained_no_verified_speaker_channel_mapping",
                "measurement_status": "not_computed_by_alignment_helper",
            }
        )

    result: dict[str, Any] = {
        "schema": ALIGNMENT_SCHEMA,
        "stage": "C3",
        "source_sha256": signal.source_sha256,
        "source_bytes": signal.source_bytes,
        "duration_ms": signal.duration_ms,
        "transcript_revision": native_transcript.revision,
        "transcript_duration_source": (
            "c2_declared_and_c1_match"
            if native_transcript.duration_declared
            else "c1_media_duration"
        ),
        "measurement_parent": {
            "stage": "C1",
            "feature_sha256": signal.feature_sha256,
            "native_source_sha256": signal.native_source_sha256,
            "audioatlas_profile": _AUDIOATLAS_PROFILE,
            "clock": "decoded_audio_track",
            "rate": signal.rate,
            "channels": signal.channels,
            "window_ms": 40,
            "hop_ms": 10,
            "support": "full_window_only",
        },
        "timebase": {
            "audioatlas": signal.source_timebase,
            "transcript_timebase_id": native_transcript.timebase_id,
            "mapping_status": mapping_status,
            "mapping_certified": False,
            "mapping_reason": mapping_reason,
        },
        "alignment_to_audioatlas": "unverified",
        "speaker_identity": "unverified_provider_labels",
        "segments": normalized_segments,
        "limitations": [
            "No physical speaker-to-channel mapping was supplied or inferred.",
            "No emotion, vocal-tone, skill, intent, or sales conclusion is produced.",
            "AudioAtlas measurements remain in the C1 checkpoint; this record only "
            "describes timing support.",
        ],
    }
    result["revision"] = content_hash(result)
    return result
