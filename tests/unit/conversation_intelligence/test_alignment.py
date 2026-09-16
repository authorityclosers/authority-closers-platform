from __future__ import annotations

from copy import deepcopy
from typing import Any

import pytest

from ac_platform.conversation_intelligence.alignment import (
    ALIGNMENT_SCHEMA,
    AlignmentError,
    build_alignment,
)
from ac_platform.conversation_intelligence.signals import NATIVE_SOURCE_SHA256

SOURCE_SHA = "a" * 64


def _signal(*, channels: int = 1, source_sha256: str = SOURCE_SHA) -> dict[str, Any]:
    rate = 16_000
    sample_count = 16_000
    hop_samples = 160
    rows = ((sample_count + hop_samples - 1) // hop_samples) * channels
    return {
        "schema": "ac.sales-xray.signal-checkpoint/1",
        "stage": "C1",
        "source_sha256": source_sha256,
        "source_bytes": 12_345,
        "source_rate": 48_000,
        "source_channels": channels,
        "media_duration_ms": 1_000,
        "feature_sha256": "b" * 64,
        "acoustics": {
            "format": "ac.audioatlas.features/1",
            "source_sha256": source_sha256,
            "feature_sha256": "b" * 64,
            "rate": rate,
            "channels": channels,
            "sample_count": sample_count,
            "rows": rows,
            "window_samples": 640,
            "hop_samples": hop_samples,
            "window_ms": 40,
            "hop_ms": 10,
            "clock": "decoded_audio_track",
            "profile": "audioatlas-native-0.1-40ms-10ms",
            "support": (
                "[start_sample, start_sample + valid_samples); attribution needs full windows"
            ),
        },
        "native_receipt": {
            "source_sha256": NATIVE_SOURCE_SHA256,
            "binary_sha256": "c" * 64,
            "mode": "fft",
            "rows": rows,
        },
        "timebase": {
            "clock": "decoded_audio_track",
            "rate": rate,
            "sample_zero": 0,
            "sample_to_seconds": {"numerator": 1, "denominator": rate},
            "source_sample_rate": 48_000,
            "source_track_start_seconds": None,
            "source_track_time_base": "1/48000",
            "nominal_source_samples_per_decoded_sample": {"numerator": 48_000, "denominator": rate},
            "resampled": True,
            "silence_removed": False,
            "gain_normalized": False,
            "denoised": False,
            "source_mapping_status": "uncertified_codec_delay_origin_and_discontinuities",
            "container_video_sync_certified": False,
        },
        "compatibility": {
            "audioatlas": {"window_ms": 40, "hop_ms": 10, "join": "full_support"},
            "interchangeable": False,
        },
    }


def _transcript(
    *segments: dict[str, Any],
    timebase_id: str = "elevenlabs-scribe-native-seconds",
    duration_ms: int | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "source_sha256": SOURCE_SHA,
        "revision": "scribe-response-revision",
        "timebase_id": timebase_id,
        "alignment_to_audioatlas": "unverified",
        "speaker_identity": "unverified_provider_labels",
        "segments": list(segments),
    }
    if duration_ms is not None:
        result["duration_ms"] = duration_ms
    return result


def _segment(
    identifier: str, start_ms: int, end_ms: int, speaker_id: str = "closer"
) -> dict[str, Any]:
    return {
        "id": identifier,
        "speaker_id": speaker_id,
        "start_ms": start_ms,
        "end_ms": end_ms,
        "text": "Synthetic utterance",
    }


def test_build_alignment_accepts_current_scribe_shape_and_is_deterministic() -> None:
    signal = _signal()
    transcript = _transcript(_segment("s1", 100, 200), _segment("s2", 200, 400, "prospect"))
    first = build_alignment(signal, transcript)
    second = build_alignment(signal, transcript)

    assert first == second
    assert first["schema"] == ALIGNMENT_SCHEMA
    assert first["stage"] == "C3"
    assert first["source_sha256"] == SOURCE_SHA
    assert first["duration_ms"] == 1_000
    assert first["transcript_duration_source"] == "c1_media_duration"
    assert first["timebase"]["mapping_status"] == (
        "provider_native_clock_unmapped_to_decoded_audio_track"
    )
    assert first["timebase"]["mapping_certified"] is False
    assert first["segments"][0]["support"]["status"] == "unavailable_clock_mapping"
    assert first["segments"][0]["support"]["candidate_full_window_count"] is None
    assert first["segments"][0]["channel"] is None
    assert first["segments"][0]["speaker_identity"] == "unverified_provider_label"
    assert first["segments"][0]["measurement_status"] == "not_computed_by_alignment_helper"
    assert "emotion" not in first["segments"][0]
    assert "skill" not in first["segments"][0]
    assert "No emotion" in first["limitations"][1]


def test_shared_decoded_clock_reports_support_without_measurements() -> None:
    result = build_alignment(
        _signal(),
        _transcript(
            _segment("s1", 100, 200),
            timebase_id="decoded_audio_track",
            duration_ms=1_000,
        ),
    )
    segment = result["segments"][0]
    assert result["timebase"]["mapping_status"] == "decoded_clock_shared_source_origin_unverified"
    assert segment["support"] == {
        "status": "candidate_full_window_support",
        "candidate_full_window_count": 7,
        "window_ms": 40,
        "hop_ms": 10,
    }
    assert segment["attribution_status"] == "abstained_no_verified_speaker_channel_mapping"
    assert result["measurement_parent"]["feature_sha256"] == "b" * 64


def test_deepgram_native_clock_remains_unmapped_and_unverified() -> None:
    result = build_alignment(
        _signal(),
        _transcript(
            _segment("s1", 100, 200),
            timebase_id="deepgram-native-seconds",
            duration_ms=1_000,
        ),
    )

    assert result["timebase"]["transcript_timebase_id"] == "deepgram-native-seconds"
    assert result["timebase"]["mapping_status"] == (
        "provider_native_clock_unmapped_to_decoded_audio_track"
    )
    assert result["timebase"]["mapping_certified"] is False
    assert result["segments"][0]["channel"] is None
    assert result["segments"][0]["attribution_status"] == (
        "abstained_no_verified_speaker_channel_mapping"
    )


@pytest.mark.parametrize(
    ("field", "value", "error"),
    [
        ("source_sha256", "d" * 64, "alignment_source_mismatch"),
        ("media_duration_ms", 999, "alignment_duration_mismatch"),
        ("feature_sha256", "d" * 64, "alignment_feature_hash_mismatch"),
    ],
)
def test_alignment_rejects_cross_source_or_duration_mismatch(
    field: str, value: Any, error: str
) -> None:
    signal = _signal()
    transcript = _transcript(_segment("s1", 0, 200))
    if field == "source_sha256":
        transcript[field] = value
    else:
        signal[field] = value
    with pytest.raises(AlignmentError, match=f"^{error}$"):
        build_alignment(signal, transcript)


@pytest.mark.parametrize(
    ("field", "value", "error"),
    [
        ("profile", "other-profile", "alignment_acoustics_metadata_invalid"),
        ("source_rate", 44_100, "alignment_source_rate_mismatch"),
        ("source_channels", 2, "alignment_source_channels_mismatch"),
        ("source_mapping_status", "certified", "alignment_timebase_metadata_invalid"),
        ("binary_sha256", "short", "alignment_native_binary_sha256_invalid"),
        ("interchangeable", True, "alignment_audioatlas_provenance_invalid"),
    ],
)
def test_alignment_requires_declared_audioatlas_provenance(
    field: str, value: Any, error: str
) -> None:
    signal = _signal()
    if field == "profile":
        signal["acoustics"][field] = value
    elif field in {"source_rate", "source_channels"}:
        signal[field] = value
    elif field == "source_mapping_status":
        signal["timebase"][field] = value
    elif field == "binary_sha256":
        signal["native_receipt"][field] = value
    else:
        signal["compatibility"][field] = value
    with pytest.raises(AlignmentError, match=f"^{error}$"):
        build_alignment(signal, _transcript(_segment("s1", 0, 200)))


@pytest.mark.parametrize(
    ("change", "error"),
    [
        (lambda t: t["segments"][0].update({"start_ms": -1}), "alignment_segment_start_ms_invalid"),
        (lambda t: t["segments"][0].update({"end_ms": 1_001}), "alignment_segment_bounds_invalid"),
        (
            lambda t: t["segments"].append(_segment("s1", 300, 500)),
            "alignment_duplicate_segment_id",
        ),
        (
            lambda t: t["segments"].append(_segment("s2", 50, 100)),
            "alignment_segments_out_of_order",
        ),
    ],
)
def test_alignment_rejects_malformed_segment_timing(change: Any, error: str) -> None:
    transcript = _transcript(_segment("s1", 100, 200))
    change(transcript)
    with pytest.raises(AlignmentError, match=f"^{error}$"):
        build_alignment(_signal(), transcript)


def test_alignment_rejects_ambiguous_or_claimed_clock_mapping() -> None:
    transcript = _transcript(_segment("s1", 0, 200))
    transcript["clock"] = "container"
    with pytest.raises(AlignmentError, match="^alignment_transcript_clock_invalid$"):
        build_alignment(_signal(), transcript)

    transcript = _transcript(_segment("s1", 0, 200))
    transcript["alignment_to_audioatlas"] = "certified"
    with pytest.raises(AlignmentError, match="^alignment_claimed_audioatlas_certification$"):
        build_alignment(_signal(), transcript)


def test_alignment_preserves_overlap_as_uncertain_support() -> None:
    result = build_alignment(
        _signal(),
        _transcript(_segment("s1", 0, 500), _segment("s2", 400, 700, "prospect")),
    )
    assert [item["overlap_present"] for item in result["segments"]] == [True, True]
    assert all(item["channel_mapping"] == "unverified_no_assignment" for item in result["segments"])


def test_alignment_does_not_mutate_input_payloads() -> None:
    signal = _signal()
    transcript = _transcript(_segment("s1", 0, 200))
    original_signal = deepcopy(signal)
    original_transcript = deepcopy(transcript)
    build_alignment(signal, transcript)
    assert signal == original_signal
    assert transcript == original_transcript
