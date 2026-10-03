"""Pure withheld guard (AUT-519 D4–D5) and the checked-in guarded web fixtures.

Fictional text only. The fixtures under ``tests/fixtures/sensitive_segments`` are
generated here and parsed by the sales-xray-web and admin-web contract tests.
Set ``AC_UPDATE_FIXTURES=1`` to rewrite them after an intentional change.
"""

from __future__ import annotations

import copy
import json
import os
from pathlib import Path
from typing import Any
from uuid import UUID

from ac_platform.conversation_intelligence.report_access import (
    ReportAccess,
    ReportSourceBinding,
    project_bound_report,
)
from ac_platform.conversation_intelligence.reports import ReportDraft, parse_report_draft
from ac_platform.conversation_intelligence.sensitive_segments import (
    WITHHELD_MARKER,
    at_path,
    grams,
    markers,
    shared_grams,
    withheld_plan,
    withhold,
)
from tests.conversation_overview_fixtures import overview_for

FIXTURES = Path(__file__).parents[2] / "fixtures" / "sensitive_segments"
RECORDING_ID = UUID("11111111-1111-4111-8111-111111111111")
RUN_ID = UUID("22222222-2222-4222-8222-222222222222")
SOURCE_SHA256 = "a" * 64
REVISION = "scribe-fictional-r1"

S3 = "The purple otter paid the lighthouse invoice on Tuesday evening"
S4 = "She said the lighthouse invoice on Tuesday was late"  # shares a 4-gram with S3
S9 = "Our kettle whistles whenever the moon rises over the shed"
LINES = {
    "s1": "Thanks for joining the fictional demo today.",
    "s2": "Let us talk about the fictional widget pricing.",
    "s3": S3,
    "s4": S4,
    "s5": "Sounds good, send the fictional proposal over.",
    "s6": "We can start the fictional rollout next quarter.",
    "s7": "Which team would own the fictional rollout?",
    "s8": "Probably the fictional operations group.",
    "s9": S9,
}


def transcript() -> dict[str, Any]:
    segments = [
        {
            "id": segment_id,
            "speaker_id": "speaker_1" if index % 2 == 0 else "unattributed",
            "start_ms": index * 1_000,
            "end_ms": index * 1_000 + 900,
            "text": text,
        }
        for index, (segment_id, text) in enumerate(LINES.items())
    ]
    return {
        "source_sha256": SOURCE_SHA256,
        "revision": REVISION,
        "timebase_id": "elevenlabs-scribe-native-seconds",
        "duration_ms": len(segments) * 1_000,
        "segments": segments,
    }


def _evidence(segment_id: str, quote: str) -> dict[str, Any]:
    index = list(LINES).index(segment_id)
    return {
        "segment_id": segment_id,
        "quote": quote,
        "start_ms": index * 1_000,
        "end_ms": index * 1_000 + 900,
    }


def report() -> ReportDraft:
    """A valid fictional report whose dimension 1 cites s9, s3 and s4 in that order."""

    finding = {
        "title": "Clarify the stated barrier",
        "explanation": "The line gives a source bound reason to explore the barrier.",
        "evidence": [_evidence("s9", S9)],
    }
    payload = {
        "summary": "The draft describes observable conversation behaviour and its uncertainty.",
        "strengths": [finding],
        "missed_opportunities": [finding],
        "improvements": [finding],
        "objection_analysis": [finding],
        "closing_analysis": [finding],
        "verdict": "Qualitative draft for human review.",
        "review_status": "draft_not_dipak_adjudicated",
        "source_label": "model supplied label must not control provenance",
    }
    draft = parse_report_draft(payload, transcript(), source_label="Fictional call")
    value = draft.model_dump(mode="json")
    value["dimensions"][1]["evidence"] = [
        _evidence("s9", S9),
        _evidence("s3", S3[:30]),
        _evidence("s4", S4),
    ]
    value["dimensions"][1]["observation"] = f"Evidence: s3[2000-2900]: {S3}"
    value["overview"] = overview_for(value)
    value["overview"]["ethics_notes"] = [
        {"text": f"Opening: {S3}.", "evidence": [_evidence("s3", S3[:30])]}
    ]
    value["provider_extras"] = {"raw": S3 + " and more", "model": "fixture-1"}
    return ReportDraft.model_validate(value)


def plan():
    return withheld_plan(
        [(s["id"], s["text"]) for s in transcript()["segments"]], ["s3"], grams(S3)
    )


def envelope(guarded: bool) -> dict[str, Any]:
    bound = project_bound_report(
        report(),
        access=ReportAccess.ACCOUNT,
        source=ReportSourceBinding(RECORDING_ID, RUN_ID, SOURCE_SHA256, REVISION),
    )
    value = {"submission_id": str(RECORDING_ID), **bound}
    return withhold(value, plan()) if guarded else value


def admin_envelope(guarded: bool) -> dict[str, Any]:
    value = {
        "id": "44444444-4444-4444-8444-444444444444",
        "run_id": str(RUN_ID),
        "recording_id": str(RECORDING_ID),
        "tenant_id": "206ccee8-a246-433b-b6d3-78eb21592a5c",
        "source": {
            "sha256": SOURCE_SHA256,
            "revision": 1,
            "retention_until": "2026-10-22T12:00:00+00:00",
        },
        "report": report().model_dump(mode="json"),
        "message": "Private report loaded for authorized Admin review.",
    }
    return withhold(value, plan()) if guarded else value


def test_grams_normalise_and_window() -> None:
    assert grams("ONE two") == frozenset()
    assert grams("Ａ b c d e") == {("a", "b", "c", "d"), ("b", "c", "d", "e")}
    assert len(WITHHELD_MARKER.split()) == 3 and grams(WITHHELD_MARKER) == frozenset()


def test_plan_holds_ids_and_grams_only() -> None:
    value = plan()
    assert value.segment_ids == {"s3", "s4"}
    assert value.grams == grams(S3)
    assert S3 not in repr(value)


def test_empty_plan_returns_the_same_object() -> None:
    value = envelope(guarded=False)
    empty = withheld_plan([(s["id"], s["text"]) for s in transcript()["segments"]], [], [])
    assert empty.empty
    assert withhold(value, empty) is value


def test_rules_a_b_c_keep_shape_ids_and_timings() -> None:
    before = envelope(guarded=False)
    snapshot = copy.deepcopy(before)
    guarded = envelope(guarded=True)
    assert before == snapshot
    content = guarded["report"]["content"]
    evidence = content["dimensions"][1]["evidence"]
    assert [item["segment_id"] for item in evidence] == ["s9", "s3", "s4"]
    assert evidence[0]["quote"] == S9
    assert evidence[1]["quote"] == evidence[2]["quote"] == WITHHELD_MARKER
    assert [item["end_ms"] for item in evidence] == [8_900, 2_900, 3_900]
    assert content["dimensions"][1]["observation"] == WITHHELD_MARKER
    assert (
        content["dimensions"][0]["observation"]
        == snapshot["report"]["content"]["dimensions"][0]["observation"]
    )
    note = content["overview"]["ethics_notes"][0]
    assert note["text"] == note["evidence"][0]["quote"] == WITHHELD_MARKER
    assert note["evidence"][0]["segment_id"] == "s3"
    assert content["strengths"][0]["evidence"][0]["quote"] == S9
    assert _shape(guarded) == _shape(snapshot)
    assert shared_grams(snapshot, grams(S3)) == len(grams(S3))
    assert shared_grams(guarded, grams(S3)) == 0

    raw = withhold(report().model_dump(mode="json"), plan())
    assert raw["provider_extras"] == {"raw": WITHHELD_MARKER, "model": "fixture-1"}
    assert ReportDraft.model_validate(raw).transcript_revision == REVISION

    served = withhold(transcript(), plan())
    assert [s["text"] for s in served["segments"]][2:4] == [WITHHELD_MARKER, WITHHELD_MARKER]
    assert served["segments"][8]["text"] == S9
    assert [s["start_ms"] for s in served["segments"]] == [
        s["start_ms"] for s in transcript()["segments"]
    ]
    assert markers(served) == 2


def test_evidence_quote_follows_rule_a_only() -> None:
    value = withheld_plan([("s9", S9)], [], grams(S3))
    item = {"segment_id": "s9", "quote": S3, "label": S3}
    guarded = withhold(item, value)
    assert guarded["quote"] == S3 and guarded["label"] == WITHHELD_MARKER


def test_at_path_resolves_dimension_evidence() -> None:
    content = envelope(guarded=True)["report"]["content"]
    assert at_path(content, "dimensions[1].evidence[1]")["segment_id"] == "s3"
    assert at_path(content, "dimensions[1].evidence[1].quote") == WITHHELD_MARKER
    assert at_path(content, "dimensions[7].evidence[1]") is None
    assert at_path(content, "overview.missing.deeper") is None


def test_guarded_web_fixtures_are_checked_in() -> None:
    expected = {
        "acquisition-report.json": envelope(guarded=True),
        "transcript.json": withhold(transcript(), plan()),
        "admin-report.json": admin_envelope(guarded=True),
    }
    for name, value in expected.items():
        path = FIXTURES / name
        encoded = json.dumps(value, indent=2, sort_keys=True) + "\n"
        if os.getenv("AC_UPDATE_FIXTURES") == "1":
            path.write_text(encoded)
        assert path.read_text() == encoded, f"run with AC_UPDATE_FIXTURES=1 to refresh {name}"
        assert S3 not in encoded and shared_grams(value, grams(S3)) == 0


def _shape(value: Any, prefix: str = "") -> set[str]:
    out: set[str] = set()
    if isinstance(value, dict):
        for key, item in value.items():
            out.add(f"{prefix}.{key}")
            out |= _shape(item, f"{prefix}.{key}")
    elif isinstance(value, list):
        out.add(f"{prefix}#{len(value)}")
        for index, item in enumerate(value):
            out |= _shape(item, f"{prefix}[{index}]")
    return out
