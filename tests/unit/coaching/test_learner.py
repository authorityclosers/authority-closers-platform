"""Fictional coaching evidence: stability, uncertainty and version boundaries."""

from datetime import UTC, datetime, timedelta
from uuid import UUID

from ac_platform.coaching.contracts import CallHistory, Mission, Moment, SkillObservation
from ac_platform.coaching.learner import build_learner

PERSON, TENANT = UUID(int=1), UUID(int=2)
NOW = datetime(2026, 10, 10, tzinfo=UTC)


def call(
    index: int,
    *,
    skill: str = "problem_impact_desire",
    attention: bool = True,
    version: str = "reviewed-comparable-v1",
    source: str | None = None,
) -> CallHistory:
    identifier = UUID(int=100 + index)
    moment = Moment(
        submission_id=identifier,
        recording_id=UUID(int=200 + index),
        source_sha256=source or f"{index:064x}",
        transcript_revision="fictional-transcript-v1",
        created_at=NOW + timedelta(days=index),
        call_label=f"Fictional call {index}",
        segment_id="seg-1",
        quote="Our handover takes time.",
        start_ms=1000,
        end_ms=4000,
        observation="The handover consequence was left unclear.",
    )
    mission = Mission(
        skill_id=skill,
        behavior="Ask one consequence question before recommending a solution.",
        context="When a problem's impact is unclear.",
        done_when="One relevant consequence is explored.",
        cue="Understand the impact before choosing a solution.",
        active_since=moment.created_at,
        origin_submission_id=identifier,
    )
    observation = SkillObservation(
        skill_id=skill,
        label=skill,
        report_status="partial" if attention else "observed",
        observation=moment.observation,
        evidence=(moment,),
        improvement="Explore the impact of the handover." if attention else None,
        mission=mission if attention else None,
    )
    return CallHistory(
        submission_id=identifier,
        source_sha256=moment.source_sha256,
        created_at=moment.created_at,
        comparison_key=version,
        skills=(observation,),
    )


def view(*history: CallHistory):
    return build_learner(history, person_id=PERSON, tenant_id=TENANT)


def test_no_history_or_no_supported_mission_never_manufactures_a_focus() -> None:
    for result in (view(), view(call(1, attention=False))):
        assert result.state == "not_enough_evidence"
        assert result.focus is result.mission is result.lesson is None
        assert result.mastery.correct_count is None


def test_one_call_is_provisional_and_repeat_evidence_is_distinct() -> None:
    single = view(call(1))
    assert single.focus.status == "provisional"
    assert "recurring pattern is not established" in single.pattern.summary
    repeated = view(call(1), call(2), call(3))
    assert repeated.focus.status == "active"
    assert repeated.pattern.attention_call_count == 3
    assert len({m.submission_id for m in repeated.evidence}) == 3
    assert repeated.root_cause.gap_type == "uncertain"
    assert repeated.mastery.state == "not_enough_evidence"
    assert repeated.mastery.correct_count is repeated.mastery.relevant_count is None
    assert repeated.pattern.occurrence_count is None


def test_a_minor_new_focus_a_new_date_or_one_observed_call_cannot_rotate_or_complete_mission() -> (
    None
):
    first = view(call(1), call(2))
    later = view(call(1), call(2), call(3, skill="qualification"), call(4, attention=False))
    assert later.focus.skill_id == first.focus.skill_id
    assert later.mission == first.mission
    assert later.mission.status == "active"
    assert later.lesson.next_call_connection == later.mission.behavior


def test_duplicate_sources_are_not_extra_learning_opportunities() -> None:
    result = view(call(1), call(2, source=f"{1:064x}"))
    assert result.analysed_calls == 1
    assert result.pattern.relevant_call_count == 1
    assert len(result.evidence) == 1


def test_unlinked_versions_and_unrelated_skills_do_not_establish_trend_or_pattern() -> None:
    result = view(call(1), call(2, version="unlinked-v2"), call(3, skill="qualification"))
    assert result.pattern.relevant_call_count == 1
    assert result.mastery.trend == "not_enough_evidence"
    assert result.mastery.baseline is None
    assert result.development_path.likely_next is None


def test_path_is_derived_and_history_limit_is_honest() -> None:
    result = build_learner(
        (call(1), call(2), call(3, skill="qualification"), call(4, skill="qualification")),
        person_id=PERSON,
        tenant_id=TENANT,
        history_limited=True,
    )
    assert result.development_path.likely_next == "qualification"
    assert any("40 retained" in line for line in result.limitations)
    assert result.feedback_available is False
