"""Fictional C5 evidence caps and narrowly provable offset repairs."""

from copy import deepcopy
from typing import Any

import pytest

from ac_platform.conversation_intelligence.reports import (
    ReportError,
    _normalise_c5_evidence,
    parse_report_draft,
)
from tests.conversation_overview_fixtures import overview_for
from tests.unit.conversation_intelligence.test_reports import _payload, _transcript

FINDINGS = (
    "strengths",
    "missed_opportunities",
    "improvements",
    "objection_analysis",
    "closing_analysis",
)


def _case() -> tuple[dict[str, Any], dict[str, Any]]:
    transcript = _transcript(count=12)
    payload = {key: deepcopy(value) for key, value in _payload(transcript).items()}
    payload["overview"] = overview_for(payload)
    return transcript, payload


def _refs(start: int = 1, stop: int = 10) -> list[dict[str, Any]]:
    return [{"segment_id": f"s{index}"} for index in range(start, stop)]


def _note(start: int = 1) -> dict[str, Any]:
    return {"text": "Fictional source observation.", "evidence": _refs(start, start + 4)}


def _nested() -> dict[str, Any]:
    return {
        "finding_index": 0,
        "prospect_signal": _note(),
        "closer_response": _note(5),
        "follow_up": "Ask about timing.",
        "potential_impact": "This may clarify the next step.",
    }


@pytest.mark.parametrize("field", FINDINGS)
def test_finding_caps_validate_then_keep_first_eight_and_count_lists(field: str) -> None:
    transcript, payload = _case()
    payload[field][0]["evidence"] = _refs()
    payload[field].append(deepcopy(payload[field][0]))
    original = deepcopy(payload)
    report = parse_report_draft(payload, transcript)
    assert payload == original
    assert [span.segment_id for span in getattr(report, field)[0].evidence] == [
        f"s{i}" for i in range(1, 9)
    ]
    assert report.provider_extras["compatibility"]["evidence_truncated"] == {field: 2}


def test_combined_diagnosis_strength_and_golden_moment_caps() -> None:
    transcript, payload = _case()
    payload["strengths"][0]["evidence"] = _refs()
    payload["overview"]["diagnosis"] = _note()
    payload["overview"]["golden_moments"] = [
        {"strength_index": 0, "evidence_index": i, "why_effective": "Source-bound reason."}
        for i in (7, 8)
    ]
    report = parse_report_draft(payload, transcript)
    assert len(report.strengths[0].evidence) == 8
    assert report.overview is not None and report.overview.diagnosis is not None
    assert len(report.overview.diagnosis.evidence) == 3
    assert [item.evidence_index for item in report.overview.golden_moments] == [7]
    assert report.provider_extras["compatibility"] == {
        "evidence_truncated": {"strengths": 1},
        "overview_drops": {
            "diagnosis": {"evidence_truncated": 1},
            "golden_moments": {"reference_out_of_range": 1},
        },
    }
    assert report.review_status == "draft_not_dipak_adjudicated"


@pytest.mark.parametrize(
    "field,children,limit",
    [
        ("diagnosis", ("",), 3),
        ("outcome", ("",), 3),
        ("improvement_details", ("what_happened",), 3),
        ("missed_details", ("prospect_signal", "closer_response"), 3),
        ("prospect_interpretations", ("source",), 3),
        ("rewatch", ("",), 1),
        ("ethics_notes", ("",), 3),
        ("conversation_change", ("before", "change", "after"), 3),
    ],
)
def test_overview_model_caps(field: str, children: tuple[str, ...], limit: int) -> None:
    transcript, payload = _case()
    item = {
        "diagnosis": _note(),
        "outcome": {**_note(), "kind": "unclear"},
        "improvement_details": {
            **payload["overview"]["improvement_details"][0],
            "what_happened": _note(),
        },
        "missed_details": _nested(),
        "prospect_interpretations": {
            "source": _note(),
            "possible_concern": "Timing may matter.",
            "interpretation_kind": "inference",
        },
        "rewatch": {**_note(), "purpose": "watch"},
        "ethics_notes": _note(),
        "conversation_change": {
            "before": _note(),
            "change": _note(5),
            "after": _note(9),
            "possible_effect": "The timing may be clearer.",
            "interpretation_kind": "inference",
        },
    }[field]
    many = isinstance(payload["overview"][field], list)
    payload["overview"][field] = [item] if many else item
    report = parse_report_draft(payload, transcript)
    kept = report.overview.model_dump()[field]
    kept = kept[0] if many else kept
    for child in children:
        actual, source = (kept[child], item[child]) if child else (kept, item)
        assert [span["segment_id"] for span in actual["evidence"]] == [
            span["segment_id"] for span in source["evidence"][:limit]
        ]
    assert report.provider_extras["compatibility"]["overview_drops"][field] == {
        "evidence_truncated": len(children)
    }


@pytest.mark.parametrize("tail", [4, 5], ids=["ordered", "overlapping"])
def test_conversation_change_checks_chronology_before_truncation(tail: int) -> None:
    transcript, payload = _case()
    payload["overview"]["conversation_change"] = {
        "before": {**_note(), "evidence": [*_refs(1, 4), {"segment_id": f"s{tail}"}]},
        "change": {**_note(5), "evidence": _refs(5, 6)},
        "after": {**_note(9), "evidence": _refs(9, 10)},
        "possible_effect": "The timing may be clearer.",
        "interpretation_kind": "inference",
    }
    report = parse_report_draft(payload, transcript)
    assert report.overview is not None
    change = report.overview.conversation_change
    if tail == 4:
        assert change is not None
        assert [span.segment_id for span in change.before.evidence] == ["s1", "s2", "s3"]
    else:
        assert change is None
    assert report.provider_extras["compatibility"]["overview_drops"]["conversation_change"] == {
        "evidence_truncated" if tail == 4 else "chronology_invalid": 1
    }


@pytest.mark.parametrize(
    "bad",
    [
        [],
        "wrong",
        None,
        [{"segment_id": "absent"}],
        [{"segment_id": "s1", "quote_start": 2, "quote_end": 1}],
    ],
)
@pytest.mark.parametrize("nested", [False, True])
def test_overview_bad_evidence_stays_rejected(bad: Any, nested: bool) -> None:
    transcript, payload = _case()
    note = {"text": "Fictional observation.", "evidence": bad}
    if nested:
        payload["overview"]["improvement_details"][0]["what_happened"] = note
    else:
        payload["overview"]["diagnosis"] = note
    with pytest.raises(ReportError, match="report_evidence_"):
        parse_report_draft(payload, transcript)


def test_overview_length_plus_other_error_is_not_salvaged() -> None:
    transcript, payload = _case()
    payload["overview"]["diagnosis"] = {**_note(), "text": ""}
    with pytest.raises(ReportError, match="report_evidence_invalid"):
        parse_report_draft(payload, transcript)


def _put_evidence(
    payload: dict[str, Any], transcript: dict[str, Any], field: str, refs: Any
) -> None:
    if field == "overview":
        payload["overview"]["diagnosis"] = {**_note(), "evidence": refs}
    elif field == "nested":
        item = _nested()
        item["closer_response"]["evidence"] = refs
        payload["missed_opportunities"] = [item]
    elif field == "dimensions":
        payload["dimensions"] = parse_report_draft(_payload(transcript), transcript).model_dump()[
            "dimensions"
        ]
        for item in payload["dimensions"]:
            item["evidence"] = []
        payload["dimensions"][0].update(status="observed", evidence=refs)
    else:
        payload[field][0]["evidence"] = refs


@pytest.mark.parametrize("field", [*FINDINGS, "nested", "dimensions", "overview"])
def test_bad_reference_after_cap_still_rejects_report(field: str) -> None:
    transcript, payload = _case()
    _put_evidence(payload, transcript, field, [*_refs(), {"segment_id": "absent"}])
    with pytest.raises(ReportError, match="report_evidence_segment_invalid"):
        parse_report_draft(payload, transcript, canonical_read=True)


def test_nested_missed_opportunity_keeps_first_eight_unique_references() -> None:
    transcript, payload = _case()
    _put_evidence(payload, transcript, "nested", _refs())
    report = parse_report_draft(payload, transcript)
    assert [span.segment_id for span in report.missed_opportunities[0].evidence] == [
        f"s{i}" for i in range(1, 9)
    ]
    assert report.provider_extras["compatibility"]["evidence_truncated"] == {
        "missed_opportunities": 1
    }


@pytest.mark.parametrize(
    "revision,canonical", [("coaching-v4", True), ("coaching-v5", False), ("coaching-v6", False)]
)
def test_dimension_caps(revision: Any, canonical: bool) -> None:
    transcript, payload = _case()
    _put_evidence(payload, transcript, "dimensions", _refs())
    report = parse_report_draft(
        payload, transcript, coaching_prompt_revision=revision, canonical_read=canonical
    )
    assert [span.segment_id for span in report.dimensions[0].evidence] == [
        f"s{i}" for i in range(1, 9)
    ]
    assert report.provider_extras["compatibility"]["evidence_truncated"] == {"dimensions": 1}


@pytest.mark.parametrize("field", ["strengths", "nested", "dimensions", "overview"])
@pytest.mark.parametrize(
    "start,end,reason",
    [(0, 10000, "offset_end_past_segment"), (1000, 1900, "offset_timestamp_copy")],
)
def test_exact_intent_offsets_equal_segment_reference(
    field: str, start: int, end: int, reason: str
) -> None:
    transcript, payload = _case()
    _put_evidence(payload, transcript, field, [{"segment_id": "s2"}])
    expected = parse_report_draft(payload, transcript, canonical_read=True).model_dump()
    _put_evidence(
        payload, transcript, field, [{"segment_id": "s2", "quote_start": start, "quote_end": end}]
    )
    actual = parse_report_draft(payload, transcript, canonical_read=True).model_dump()
    assert actual.pop("provider_extras")["compatibility"]["evidence_salvaged"] == {reason: 1}
    expected.pop("provider_extras", None)
    assert actual == expected


@pytest.mark.parametrize(
    "text,start,end",
    [
        ("Source", 8, 10),
        ("Source", 4, 2),
        ("Source", -1, 2),
        ("  Source", 0, 2),
        ("Source", True, 2),
        ("Source", 0, 2.5),
        ("x" * 2001, 0, 3000),
        ("x" * 2001, 0, 2001),
        ("x" * 2001, 1, 2002),
        ("   ", 0, 10),
        ("   ", 1000, 1900),
    ],
    ids=lambda value: f"text-{len(value)}" if isinstance(value, str) else str(value),
)
def test_other_invalid_offsets_stay_rejected(text: str, start: Any, end: Any) -> None:
    transcript, payload = _case()
    transcript["segments"][1]["text"] = text
    with pytest.raises(ReportError, match="report_evidence_invalid"):
        _normalise_c5_evidence(
            {"segment_id": "s2", "quote_start": start, "quote_end": end}, transcript
        )


def test_full_quotes_remain_exact_and_are_not_counted_as_salvaged() -> None:
    transcript, payload = _case()
    report = parse_report_draft(payload, transcript)
    assert "evidence_salvaged" not in report.provider_extras.get("compatibility", {})
    payload["strengths"][0]["evidence"][0]["quote"] = "Not in the source."
    with pytest.raises(ReportError, match="report_evidence_quote_mismatch"):
        parse_report_draft(payload, transcript)


def test_valid_offsets_matching_timestamps_preserve_literal_slice() -> None:
    transcript, payload = _case()
    text = transcript["segments"][0]["text"].ljust(1000, "x")
    transcript["segments"][0]["text"] = text
    payload["strengths"][0]["evidence"] = [{"segment_id": "s1", "quote_start": 0, "quote_end": 900}]
    report = parse_report_draft(payload, transcript)
    assert report.strengths[0].evidence[0].quote == text[:900]
    assert "evidence_salvaged" not in report.provider_extras.get("compatibility", {})


@pytest.mark.parametrize("length", [2000, 2001])
def test_timestamp_repair_obeys_whole_segment_size_limit(length: int) -> None:
    transcript = _transcript(count=1)
    transcript["segments"][0].update(text="x" * length, start_ms=3000, end_ms=3900)
    reference = {"segment_id": "s1", "quote_start": 3000, "quote_end": 3900}
    salvaged: dict[str, int] = {}
    if length > 2000:
        with pytest.raises(ReportError, match="report_evidence_invalid"):
            _normalise_c5_evidence(reference, transcript, salvaged)
        assert salvaged == {}
    else:
        result = _normalise_c5_evidence(reference, transcript, salvaged)
        assert result["quote"] == "x" * length
        assert salvaged == {"offset_timestamp_copy": 1}
