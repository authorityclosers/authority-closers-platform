"""Deep pipeline rules: audio features, segment labels, and the merge with earlier facts.

Pure unit tests: no database, no provider. Transcript lines are fictional.
"""

from __future__ import annotations

import math
import struct
from uuid import uuid4

import pytest

from ac_platform.call_data import audio, classifier, deep, taxonomy
from ac_platform.call_data.extraction import Draft, Segment
from ac_platform.call_data.values import CallValueError, display, validate_value

SEGMENTS = [
    Segment("s1", "Namaste ji, main Rohan bol raha hoon", 0, 4000, "speaker_0"),
    Segment("s2", "Haan boliye, kya hai", 4500, 6000, "speaker_1"),
    Segment("s3", "Aapki team kitne logon ki hai abhi", 9000, 12000, "speaker_0"),
    Segment("s4", "Aath log hain aur sales sab mere upar hai", 11500, 16000, "speaker_1"),
]
ROLES = {"speaker_0": "salesperson", "speaker_1": "prospect"}


def _blob(rows: list[tuple[float, float, float, int]], rate: int = 16000) -> bytes:
    header = struct.pack("<8sIIQIIQ", b"ACAAF001", rate, 1, 0, 640, 160, len(rows))
    body = b""
    for time_ms, dbfs, f0, flags in rows:
        values = [0.0] * 14
        values[1], values[12], values[13] = dbfs, f0, 0.9
        body += struct.pack("<IBHHB14f", int(time_ms * rate / 1000), 0, 640, 0, flags, *values)
    return header + body


def test_audio_features_join_frames_with_the_transcript() -> None:
    rows = [(t, -20.0, 180.0, 0) for t in range(0, 4000, 10)]  # salesperson, s1
    rows += [(t, -26.0, 240.0, 0) for t in range(11500, 16000, 10)]  # overlap + prospect s4
    rows += [(t, -90.0, math.nan, 4) for t in range(6000, 9000, 10)]  # silence, no pitch
    rate, frames = audio.frames(_blob(sorted(rows)))
    assert rate == 16000
    value = audio.features(
        SEGMENTS,
        roles=ROLES,
        duration_ms=16000,
        display_dbfs=[-90.0, -20.0, -30.0, -60.0] * 100,
        frame_rows=list(frames),
    )
    sales, prospect = value["speakers"]["salesperson"], value["speakers"]["prospect"]
    assert sales["pitch_hz"] == 180.0 and prospect["pitch_hz"] == 240.0
    # Overlapping speech (s3 and s4) counts for both speakers.
    assert sales["loudness_dbfs"] == pytest.approx(-20.0, abs=0.6)
    assert round(sales["share"] + prospect["share"], 3) == 1.0
    assert value["pauses"] == {"count": 1, "long": 1, "total_ms": 3000, "longest_ms": 3000}
    assert value["overlap_ms"] == 500  # s4 starts 0.5 s before s3 ends
    assert len(value["peaks"]) <= audio.PEAK_POINTS and max(value["peaks"]) <= 1
    assert value["source"] == "audioatlas frames"
    checked = validate_value(taxonomy.TYPES["audio.features"], value)
    assert "long pauses" in display(taxonomy.TYPES["audio.features"], checked)
    ratio = audio.talk_ratio(checked)
    assert ratio is not None and abs(sum(ratio["parts"].values()) - 1) < 0.01
    with pytest.raises(audio.AudioError):
        audio.frames(b"ACAAF001" + b"\0" * 10)


def test_audio_without_frames_still_measures_timings() -> None:
    value = audio.features(SEGMENTS, roles={}, duration_ms=16000)
    assert value["source"] == "transcript timings only" and "pitch_hz" not in value
    assert set(value["speakers"]) == {"speaker_0", "speaker_1"}  # no roles: speaker ids
    with pytest.raises(CallValueError):
        validate_value(taxonomy.TYPES["audio.features"], {**value, "peaks": [2.0]})


def test_segment_labels_are_checked_one_per_segment() -> None:
    assert classifier.chunks(SEGMENTS, size=3) == [(0, 3), (3, 4)]
    system, user = classifier.build_prompt(SEGMENTS, 0, 2, roles=ROLES)
    assert "objection_handling" in system and "[s1] LABEL" in user and "[s3] context" in user
    raw = {
        "labels": [
            {
                "segment": "s1",
                "intent": "greeting",
                "act": "statement",
                "sentiment": "positive",
                "tone": "warm",
                "topics": ["intro", None, ""],
            },
            {
                "segment": "s1",
                "intent": "pitch",
                "act": "statement",
                "sentiment": "neutral",
                "tone": "neutral",
                "topics": [],
            },  # a second label for s1 is dropped
            {
                "segment": "s2",
                "intent": "made_up",
                "act": "statement",
                "sentiment": "neutral",
                "tone": "neutral",
                "topics": [],
            },
            {
                "segment": "s9",
                "intent": "pain",
                "act": "statement",
                "sentiment": "neutral",
                "tone": "neutral",
                "topics": [],
            },
        ]
    }
    drafts, dropped = classifier.validate_labels(raw, SEGMENTS, 0, 2)
    assert [d.evidence[0]["segment_id"] for d in drafts] == ["s1"]
    assert drafts[0].value == {
        "intent": "greeting",
        "act": "statement",
        "sentiment": "positive",
        "tone": "warm",
        "topics": ["intro"],
    }
    assert drafts[0].display == "Greeting · statement · positive · warm"
    assert dropped == {"segment": 2, "segment_labels": 1, "unlabelled": 1}


def _draft(type_key: str, text: str, confidence: float = 0.9) -> Draft:
    kind_type = taxonomy.TYPES[type_key]
    return Draft(
        type_key,
        kind_type.category,
        {"text": text},
        text,
        confidence,
        "observed",
        2,
        [{"segment_id": "s2", "quote": "q", "start_ms": 0, "end_ms": 1, "speaker": "a"}],
    )


def _current(type_key: str, text: str, *, decision: str | None, confidence: float = 0.9):
    return deep.Current(
        uuid4(), type_key, text, {"text": text}, [], confidence, "observed", 1, "fast", decision
    )


def test_deep_supersedes_machine_facts_keeps_a_persons_and_retracts_weak_ones() -> None:
    pain = _current("need.primary_pain", "Sales on Amit", decision="asked")
    name = _current("person.name", "Amit S", decision="edited")
    weak = _current("need.goal", "Grow fast", decision=None, confidence=0.5)
    strong = _current("market.competitor", "Acme", decision=None, confidence=0.9)
    segment = deep.Current(
        uuid4(),
        "conversation.segment",
        "Pain",
        {},
        [{"segment_id": "s2"}],
        0.8,
        "inferred",
        1,
        "deep",
        None,
    )
    merge = deep.plan_merge(
        [
            _draft("need.primary_pain", "Every sale needs Amit"),
            _draft("person.name", "Amit Sharma"),
            _draft("money.budget", "2 lakh"),
        ],
        [pain, name, weak, strong, segment],
        lead=None,
        auto_filled={},
        rejected=frozenset(),
    )
    assert [d.type_key for d in merge.drafts] == ["need.primary_pain", "money.budget"]
    assert merge.supersedes == [pain.id, None]
    assert merge.person_kept == 1
    assert [c.id for c in merge.retract] == [weak.id]  # strong and segment labels stay
    assert deep.identity("conversation.segment", "x", [{"segment_id": "s7"}]) == (
        "conversation.segment",
        "s7",
    )


def test_labels_match_by_id_in_any_form_or_by_the_segments_words() -> None:
    def label(**key: object) -> dict[str, object]:
        return {
            **key,
            "intent": "pain",
            "act": "statement",
            "sentiment": "negative",
            "tone": "frustrated",
            "topics": [],
        }

    raw = {
        "labels": [
            label(segment_id="[s1]"),
            label(segment_id="2"),
            label(segment_id=SEGMENTS[2].text),  # the model answered with the words
            label(segment_id="s4 LABEL"),
        ]
    }
    drafts, dropped = classifier.validate_labels(raw, SEGMENTS, 0, 4)
    assert [d.evidence[0]["segment_id"] for d in drafts] == ["s1", "s2", "s3", "s4"]
    assert dropped == {}
    assert "segment_id" in classifier.response_schema()["properties"]["labels"]["items"]["required"]
