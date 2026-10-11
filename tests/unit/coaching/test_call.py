"""One call is enough for a lesson; cache never supplies access authority."""

from typing import Any
from uuid import UUID

import pytest
from pydantic import ValidationError

from ac_platform.coaching.call import CallCoachingCache, CallCoachingView, build_call_coaching
from ac_platform.conversation_intelligence.sensitive_segments import WITHHELD_MARKER
from tests.unit.coaching.test_report_adapter import CALL, NOW, envelope

PERSON, TENANT = UUID(int=1), UUID(int=2)
CONTEXT = dict(submission_id=CALL, created_at=NOW, person_id=PERSON, tenant_id=TENANT)


def test_one_call_has_one_focus_lesson_practice_and_observable_mission() -> None:
    view = build_call_coaching(envelope(), **CONTEXT)
    assert view.state == "ready" and view.basis == "skill_evidence"
    assert view.focus.skill_id == "problem_impact_desire"
    assert view.mission.behavior == "Ask one impact question."
    assert view.mission.origin_submission_id == CALL
    assert view.lesson.own_call in view.evidence
    assert view.lesson.next_call_connection == view.mission.behavior
    assert view.root_cause.gap_type == "uncertain"
    assert view.practice.exercise == "Practise one follow-up."
    assert all(m.submission_id == CALL for m in view.evidence)


@pytest.mark.parametrize("missing", ["overview", "dimensions", "improvements", "evidence", "all"])
def test_sparse_or_clean_report_never_creates_a_not_enough_evidence_dead_end(missing: str) -> None:
    data = envelope()
    report = data["report"]["content"]
    if missing == "all":
        report.clear()
    elif missing == "evidence":
        report["dimensions"][0].pop("evidence")
        report["improvements"][0].pop("evidence")
    else:
        report.pop(missing)
    view = build_call_coaching(data, **CONTEXT)
    assert view.state == "ready" and view.focus and view.mission and view.lesson
    assert view.lesson.framework and view.lesson.checklist and view.lesson.when_not
    assert view.root_cause.confidence == "uncertain"
    if missing == "all":
        assert view.basis == "general_practice" and view.evidence == ()
        assert view.lesson.own_call is None
        assert "no assessed weakness" in view.focus.selected_reason


def test_a_strength_can_supply_the_call_lesson_without_inventing_a_weakness() -> None:
    data = envelope()
    report = data["report"]["content"]
    report["strengths"] = report.pop("improvements")
    report.pop("overview")
    report.pop("dimensions")
    view = build_call_coaching(data, **CONTEXT)
    assert view.state == "ready" and view.basis == "report_suggestion"
    assert view.focus.label == report["strengths"][0]["title"]
    assert view.evidence[0].quote == report["strengths"][0]["evidence"][0]["quote"]


def test_a_quoted_report_strength_is_offered_to_build_on() -> None:
    data = envelope()
    report = data["report"]["content"]
    ref = {"segment_id": "seg-2", "quote": "Tell me more.", "start_ms": 4000, "end_ms": 6000}
    report["strengths"] = [
        {"title": "Unquoted", "explanation": "No moment.", "evidence": []},
        {
            "title": "Withheld",
            "explanation": "Hidden.",
            "evidence": [{**ref, "quote": WITHHELD_MARKER}],
        },
        {"title": "Curious follow-up", "explanation": "You asked a follow-up.", "evidence": [ref]},
    ]
    view = build_call_coaching(data, **CONTEXT)
    assert view.strength is not None
    assert view.strength.title == "Curious follow-up"
    assert [m.quote for m in view.strength.evidence] == ["Tell me more."]
    assert view.strength.evidence[0].submission_id == CALL
    report.pop("strengths")
    assert build_call_coaching(data, **CONTEXT).strength is None


def test_a_malformed_strength_never_fails_the_call_coaching() -> None:
    data = envelope()
    bad = {"segment_id": "seg-2", "quote": "x" * 2001, "start_ms": 4000, "end_ms": 6000}
    data["report"]["content"]["strengths"] = [
        {"title": "Too long", "explanation": "Bad moment.", "evidence": [bad]}
    ]
    view = build_call_coaching(data, **CONTEXT)
    assert view.state == "ready" and view.strength is None


def test_the_strength_that_supplied_the_focus_is_not_repeated() -> None:
    data = envelope()
    report = data["report"]["content"]
    report["strengths"] = report.pop("improvements")
    report.pop("overview")
    report.pop("dimensions")
    view = build_call_coaching(data, **CONTEXT)
    assert view.focus.label == report["strengths"][0]["title"]
    assert view.strength is None


def test_strength_evidence_cannot_cross_into_another_source() -> None:
    view = build_call_coaching(envelope(), **CONTEXT)
    data = view.model_dump(by_alias=True)
    data["strength"] = {"title": "T", "explanation": "E", "evidence": [data["evidence"][0]]}
    assert CallCoachingView.model_validate(data).strength is not None
    data["strength"]["evidence"][0]["source_sha256"] = "b" * 64
    with pytest.raises(ValidationError, match="exact call source"):
        CallCoachingView.model_validate(data)


def test_withheld_evidence_cannot_be_relabelled_as_a_no_timestamp_finding() -> None:
    data = envelope()
    data["report"]["content"]["dimensions"] = []
    data["report"]["content"]["improvements"][0]["evidence"][0]["quote"] = WITHHELD_MARKER
    view = build_call_coaching(data, **CONTEXT)
    assert view.state == "unavailable" and not view.focus and not view.evidence
    assert "Explore one consequence" not in view.model_dump_json()


@pytest.mark.parametrize("change", ["access", "submission", "content"])
def test_caller_must_supply_the_exact_authorized_report(change: str) -> None:
    data = envelope()
    if change == "access":
        data["report"]["access"] = "guest_preview"
    elif change == "submission":
        data["submission_id"] = str(UUID(int=999))
    else:
        data["report"]["content"] = None
    with pytest.raises(ValueError):
        build_call_coaching(data, **CONTEXT)


def test_contract_rejects_cross_call_evidence_and_mission() -> None:
    view = build_call_coaching(envelope(), **CONTEXT)
    for part in ("mission", "evidence", "lesson"):
        data = view.model_dump(by_alias=True)
        if part == "mission":
            data[part]["origin_submission_id"] = UUID(int=999)
        else:
            target = data[part][0] if part == "evidence" else data[part]["own_call"]
            target["submission_id"] = UUID(int=999)
        with pytest.raises(ValidationError):
            CallCoachingView.model_validate(data)


def test_derived_cache_is_scoped_bounded_and_invalidated_by_withholding(monkeypatch: Any) -> None:
    clock = [10.0]
    monkeypatch.setattr("ac_platform.coaching.call.monotonic", lambda: clock[0])
    cache = CallCoachingCache(capacity=2, ttl_seconds=60)
    data = envelope()
    first = cache.read(data, **CONTEXT)
    assert cache.read(data, **CONTEXT) is first
    other = cache.read(data, **{**CONTEXT, "person_id": UUID(int=3)})
    assert other is not first and other.person_id == UUID(int=3)
    other_tenant = cache.read(data, **{**CONTEXT, "tenant_id": UUID(int=4)})
    assert other_tenant.tenant_id == UUID(int=4) and len(cache._entries) == 2
    fresh = cache.read(data, **CONTEXT)
    assert fresh is not first
    data["report"]["content"]["improvements"][0]["evidence"][0]["quote"] = WITHHELD_MARKER
    withheld = cache.read(data, **CONTEXT)
    assert withheld.state == "unavailable" and withheld.report_revision != first.report_revision
    clock[0] += 61
    assert cache.read(data, **CONTEXT) is not withheld
    assert len(cache._entries) == 1
