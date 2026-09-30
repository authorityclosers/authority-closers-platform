from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from ac_platform.conversation_intelligence.call_metrics import (
    CALL_METRICS_RULES,
    CallMetrics,
    TimePromise,
    TranscriptSegment,
    compute_call_metrics,
    quiet_from,
    stored_summary,
    time_promise_overrun,
)

_ROOT = Path(__file__).resolve().parents[3]
_FIXTURE = _ROOT / "apps/sales-xray-web/tests/fixtures/call-metrics-vectors.json"
_VECTORS: list[dict[str, Any]] = json.loads(_FIXTURE.read_text(encoding="utf-8"))["vectors"]


def _segments(vector: dict[str, Any]) -> list[TranscriptSegment]:
    return [
        {
            "id": segment_id,
            "speaker_id": speaker_id,
            "start_ms": start_ms,
            "end_ms": end_ms,
            "text": text,
        }
        for segment_id, speaker_id, start_ms, end_ms, text in vector["segments"]
    ]


def _metrics_as_vector(metrics: CallMetrics) -> dict[str, Any]:
    speaker_ids = list(metrics["speakers"])
    return {
        "time_used_ms": metrics["time_used_ms"],
        "speakers": metrics["speakers"],
        "cut_ins": metrics["cut_ins"],
        "price_moments": metrics["price_moments"],
        "longest_reply_after_question": metrics["longest_reply_after_question"],
        "monologues": metrics["monologues"],
        "curve": {
            "start_ms": [bin_["start_ms"] for bin_ in metrics["curve"]],
            "shares": {
                speaker_id: [bin_["shares"][speaker_id] for bin_ in metrics["curve"]]
                for speaker_id in speaker_ids
            },
        },
    }


@pytest.mark.parametrize("vector", _VECTORS, ids=lambda vector: vector["name"])
def test_python_twin_matches_every_shared_vector(vector: dict[str, Any]) -> None:
    segments = _segments(vector)
    metrics = compute_call_metrics(segments, vector["duration_ms"])
    expected = vector["expected"]

    assert _metrics_as_vector(metrics) == expected["metrics"]
    assert {
        speaker_id: quiet_from(metrics, speaker_id) for speaker_id in expected["quiet"]
    } == expected["quiet"]
    promise: TimePromise | None = vector["time_promise"]
    assert time_promise_overrun(promise, segments, metrics["time_used_ms"]) == expected["overrun"]


def test_empty_transcript_has_zero_time_and_no_speakers_or_curve() -> None:
    metrics = compute_call_metrics([], None)

    assert metrics["time_used_ms"] == 0
    assert metrics["speakers"] == {}
    assert metrics["curve"] == []


def test_transcript_with_only_unattributed_segments_uses_duration() -> None:
    segments: list[TranscriptSegment] = [
        {
            "id": "segment-1",
            "speaker_id": None,
            "start_ms": 1000,
            "end_ms": 2000,
            "text": "Fictional unattributed speech.",
        }
    ]

    metrics = compute_call_metrics(segments, 60000)

    assert metrics["time_used_ms"] == 60000
    assert metrics["speakers"] == {}
    assert metrics["curve"] == [{"start_ms": 0, "shares": {}}]


def test_transcript_with_only_zero_length_segments_has_no_timed_curve() -> None:
    segments: list[TranscriptSegment] = [
        {
            "id": "segment-1",
            "speaker_id": "speaker-1",
            "start_ms": 1000,
            "end_ms": 1000,
            "text": "Fictional question?",
        }
    ]

    metrics = compute_call_metrics(segments, None)

    assert metrics["time_used_ms"] == 0
    assert metrics["speakers"] == {
        "speaker-1": {
            "talk_ms": 0,
            "talk_share": None,
            "questions": 1,
            "questions_per_minute": None,
            "cut_ins": 0,
            "longest_monologue_ms": 0,
        }
    }
    assert metrics["curve"] == []


def _string_values(value: Any) -> Iterator[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for nested in value.values():
            yield from _string_values(nested)
    elif isinstance(value, list):
        for nested in value:
            yield from _string_values(nested)


@pytest.mark.parametrize("vector", _VECTORS, ids=lambda vector: vector["name"])
def test_stored_summary_has_the_compact_contract_and_no_transcript_text(
    vector: dict[str, Any],
) -> None:
    segments = _segments(vector)
    metrics = compute_call_metrics(segments, vector["duration_ms"])
    summary = stored_summary(segments, vector["duration_ms"])

    assert set(summary) == {
        "rules",
        "time_used_ms",
        "speakers",
        "quiet",
        "cut_ins",
        "price_moments",
        "longest_reply_after_question",
    }
    assert summary["rules"] == CALL_METRICS_RULES
    assert summary["time_used_ms"] == metrics["time_used_ms"]
    assert summary["cut_ins"] == metrics["cut_ins"][:50]
    assert summary["price_moments"] == metrics["price_moments"]
    assert summary["longest_reply_after_question"] == metrics["longest_reply_after_question"]
    assert summary["quiet"] == {
        speaker_id: quiet_from(metrics, speaker_id) for speaker_id in metrics["speakers"]
    }
    assert all(
        set(speaker)
        == {
            "talk_ms",
            "talk_share",
            "questions",
            "questions_per_minute",
            "cut_ins",
            "longest_monologue_ms",
        }
        for speaker in summary["speakers"].values()
    )

    identifier_values = {
        identifier
        for segment in segments
        for identifier in (segment["id"], segment["speaker_id"])
        if identifier is not None
    }
    max_identifier_length = max(map(len, identifier_values), default=0)
    strings = list(_string_values(summary))
    assert set(strings) <= identifier_values | {CALL_METRICS_RULES}
    assert all(
        value == CALL_METRICS_RULES or len(value) <= max_identifier_length for value in strings
    )


def test_stored_summary_caps_cut_ins_at_fifty() -> None:
    segments: list[TranscriptSegment] = [
        {
            "id": f"s{index:02d}",
            "speaker_id": "a" if index % 2 == 0 else "b",
            "start_ms": index * 100,
            "end_ms": index * 100 + 1000,
            "text": "Fictional utterance.",
        }
        for index in range(52)
    ]
    metrics = compute_call_metrics(segments, None)
    summary = stored_summary(segments, None)

    assert len(metrics["cut_ins"]) == 51
    assert summary["cut_ins"] == metrics["cut_ins"][:50]
    assert len(summary["cut_ins"]) == 50
