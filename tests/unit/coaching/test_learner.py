"""Fictional coaching evidence: stability, uncertainty and version boundaries."""

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from pydantic import ValidationError

from ac_platform.coaching.contracts import (
    CallHistory,
    Mission,
    Moment,
    SkillObservation,
    Strength,
)
from ac_platform.coaching.learner import build_learner, recurring_focus

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
    assert "isn't a pattern yet" in single.pattern.summary
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
    assert any("40 most recent calls" in line for line in result.limitations)
    assert result.feedback_available is False


def test_unclassified_report_suggestions_do_not_become_a_repeated_skill_pattern() -> None:
    suggestions = []
    for index in (1, 2):
        original = call(index, skill="report_next_step")
        suggestions.append(
            original.model_copy(
                update={
                    "skills": (
                        original.skills[0].model_copy(update={"basis": "report_suggestion"}),
                    ),
                }
            )
        )
    result = view(*suggestions)
    assert result.state == "ready"
    assert result.focus.status == "provisional"
    assert result.focus.selected_reason == "Your call's report suggested this."
    assert result.pattern.relevant_call_count == 1
    assert result.mastery.trend == "not_enough_evidence"
    assert result.root_cause.gap_type == "uncertain"
    assert any("one report’s suggestion" in row for row in result.limitations)


def test_progress_strip_reports_what_comparable_calls_said_never_success() -> None:
    history = (
        call(1),
        call(2, attention=False),
        call(3, skill="qualification"),
        call(4, version="other-evaluator-v2"),
    )
    view = build_learner(history, person_id=PERSON, tenant_id=TENANT)
    assert view.focus is not None and view.mission is not None
    # Other evaluator versions are not comparable and never appear.
    assert [(point.state, point.after_mission) for point in view.progress] == [
        ("suggested", False),
        ("no_suggestion", True),
        ("not_covered", True),
    ]
    assert [point.submission_id for point in view.progress] == [
        UUID(int=101),
        UUID(int=102),
        UUID(int=103),
    ]
    assert view.mastery.state == "not_enough_evidence"


def test_report_suggestion_focus_progress_stays_one_call() -> None:
    first = call(1)
    row, mission = first.skills[0], first.skills[0].mission
    assert mission is not None
    unlinked = first.model_copy(
        update={
            "skills": (
                row.model_copy(
                    update={
                        "basis": "report_suggestion",
                        "skill_id": "report_next_step",
                        "mission": mission.model_copy(update={"skill_id": "report_next_step"}),
                    }
                ),
            )
        }
    )
    view = build_learner((unlinked, call(2)), person_id=PERSON, tenant_id=TENANT)
    assert view.focus is not None and view.focus.skill_id == "report_next_step"
    assert [point.submission_id for point in view.progress] == [UUID(int=101)]


def test_my_coaching_offers_the_newest_calls_quoted_strength() -> None:
    first, second, third = call(1), call(2), call(3)

    def with_strength(history: CallHistory, title: str) -> CallHistory:
        moment = history.skills[0].evidence[0].model_copy(update={"quote": "Tell me more."})
        strength = Strength(title=title, explanation="You asked a follow-up.", evidence=(moment,))
        return history.model_copy(update={"strength": strength})

    view = build_learner(
        (with_strength(first, "Older strength"), with_strength(second, "Newest strength"), third),
        person_id=PERSON,
        tenant_id=TENANT,
    )
    assert view.state == "ready"
    assert view.strength is not None and view.strength.title == "Newest strength"
    assert view.strength.evidence[0].submission_id == second.submission_id
    assert build_learner((first, third), person_id=PERSON, tenant_id=TENANT).strength is None


def test_a_strength_cannot_cross_into_another_calls_history() -> None:
    first, second = call(1), call(2)
    strength = Strength(
        title="Borrowed", explanation="Not this call.", evidence=second.skills[0].evidence
    )
    data = first.model_dump()
    data["strength"] = strength.model_dump()
    with pytest.raises(ValidationError, match="cannot cross a source"):
        CallHistory.model_validate(data)


def test_a_calls_focus_recurs_only_in_another_comparable_call_with_the_same_skill() -> None:
    first, second = call(1), call(2)
    other_skill = call(3, skill="qualification")
    other_version = call(4, version="other-evaluator-v2")
    flags = recurring_focus((first, second, other_skill, other_version))
    assert flags[first.submission_id] is True and flags[second.submission_id] is True
    # One call alone, or only in another evaluator version, is not a pattern.
    assert flags[other_skill.submission_id] is False
    assert flags[other_version.submission_id] is False
    # A re-upload of the same source is one call, not a repeat.
    again = call(5, source=f"{1:064x}")
    assert recurring_focus((first, again))[first.submission_id] is False
    # No assessed skill (a report suggestion) or no focus: unknown, not "no".
    suggestion = call(6)
    suggestion = suggestion.model_copy(
        update={
            "skills": tuple(
                s.model_copy(update={"basis": "report_suggestion"}) for s in suggestion.skills
            )
        }
    )
    quiet = call(7, attention=False)
    flags = recurring_focus((first, second, suggestion, quiet))
    assert flags[suggestion.submission_id] is None and flags[quiet.submission_id] is None


def test_the_pattern_line_counts_every_flagged_call_not_only_the_four_moments() -> None:
    result = view(*(call(index) for index in range(1, 7)))
    assert len(result.evidence) == 4 and result.pattern.attention_call_count == 6
    assert result.pattern.summary.startswith("It came up on 6 different calls")
    assert "6 of your last 6 calls" in result.focus.selected_reason


def test_a_call_without_a_comparable_evaluator_version_cannot_recur() -> None:
    first, second = call(1, version="unlinked:a"), call(2, version="unlinked:a")
    assert set(recurring_focus((first, second)).values()) == {None}


def test_a_repeated_focus_comes_before_a_one_call_focus_and_then_stays() -> None:
    # A one-call focus first, then a skill that is the focus on two calls.
    result = view(call(1, skill="qualification"), call(2), call(3))
    assert result.focus.skill_id == "problem_impact_desire"
    assert result.focus.status == "active"
    assert result.mission.origin_submission_id == UUID(int=102)
    # The first skill also repeats later: the earlier pattern stays the focus.
    later = view(call(1, skill="qualification"), call(2), call(3), call(4, skill="qualification"))
    assert later.focus.skill_id == "problem_impact_desire"
    assert later.mission == result.mission
    # No pattern at all: the first supported mission stays, as before.
    single = view(call(1, skill="qualification"), call(2))
    assert single.focus.skill_id == "qualification" and single.focus.status == "provisional"


def test_an_admins_read_of_shared_coaching_talks_about_the_rep() -> None:
    history = tuple(call(index) for index in range(1, 4))
    theirs = build_learner(history, person_id=PERSON, tenant_id=TENANT, their=True)
    assert theirs.focus.selected_reason == "It came up in 3 of their last 3 calls on this skill."
    assert theirs.pattern.summary.endswith("see what they did each time.")
    assert theirs.development_path.explanation.startswith("Their next focus depends on their")
    assert all(" your " not in f" {line} " for line in theirs.limitations)
    assert "This is Sales Xray's reading of their calls." in theirs.limitations[0]
    assert "Their reports don't count" in theirs.mastery.explanation
    # The rep's own exercise and question stay addressed to the rep.
    assert theirs.reflection_question == "What stopped you here?"
    # The same history read by the rep is unchanged.
    mine = view(*history)
    assert mine.focus.selected_reason == "It came up in 3 of your last 3 calls on this skill."
    assert mine.limitations[0].startswith("This is Sales Xray's reading of your calls.")
    assert "Your reports don't count" in mine.mastery.explanation
    assert mine.mission == theirs.mission and mine.evidence == theirs.evidence
    empty = build_learner((), person_id=PERSON, tenant_id=TENANT, their=True)
    assert empty.pattern.summary == "Their calls don't show one skill to work on yet."
