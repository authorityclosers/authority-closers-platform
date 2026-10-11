"""AC Sandbox Coaching maps authored fictional coaching; it never guesses a field."""

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import pytest
from pydantic import ValidationError

from ac_platform.coaching.sandbox import (
    FICTIONAL,
    call_uuid,
    call_view,
    index_call,
    rep_uuid,
    rep_view,
    skill_for,
    team_view,
)
from ac_platform.coaching.team import TeamCoachingView, TeamRep

TENANT, VIEWER = uuid4(), uuid4()
HEADER = {"synthetic": True, "schema_version": "synthetic-sales-v1.0"}


def sandbox_bundle(
    call: str = "syn-fixture-J01-C-01",
    *,
    rep: str = "syn-fixture-R1",
    rep_name: str = "Nikhil Nivsekar",
    skill: str = "skill-7",
    label: str = "Agree an observable next step",
    at: str = "2026-07-24T10:00:00+05:30",
    sequence: int = 1,
    cited: tuple[str, ...] = (),
) -> dict[str, Any]:
    """A fictional bundle shaped like synthetic-v1 `import_ready` calls."""
    business = "syn-fixture"
    moment = {
        **HEADER,
        "call_id": call,
        "line_ids": [f"{call}:L002"],
        "start_ms": 4000,
        "end_ms": 7500,
        "quote": "Sure, we will be in touch sometime. Thanks, bye.",
        "timing_source": "estimated",
        "playable": False,
    }
    buyer_moment = {
        **moment,
        "line_ids": [f"{call}:L001"],
        "start_ms": 1000,
        "end_ms": 3500,
        "quote": "माझा प्रश्न scope बद्दल आहे. What would we test first?",
    }
    behaviour = "Before ending the call, agree an owner, action and date."
    return {
        "schema": "synthetic-call-bundle/1",
        "synthetic": True,
        "metadata": {
            **HEADER,
            "call_id": call,
            "business_id": business,
            "rep_id": rep,
            "at": at,
            "sequence": sequence,
            "private_coaching": True,
        },
        "transcript": {
            **HEADER,
            "participants": [
                {**HEADER, "person_id": rep, "speaker": "rep", "name": rep_name},
                {**HEADER, "person_id": "syn-fixture-BUY", "speaker": "prospect", "name": "Ira K."},
            ],
            "lines": [
                {"line_id": f"{call}:L001", "person_id": "syn-fixture-BUY", "text": "…"},
                {"line_id": f"{call}:L002", "person_id": rep, "text": "…"},
            ],
        },
        "coaching": {
            **HEADER,
            "call_id": call,
            "current_focus": {
                **HEADER,
                "skill_id": skill,
                "label": label,
                "status": "Active",
                "selected_reason": "The labelled behaviour occurs in this call.",
            },
            "diagnosis": {
                **HEADER,
                "root_cause_hypothesis": "A friendly ending may feel like a commitment.",
                "gap_type": "Judgment",
                "confidence": "Low",
                "alternatives": ["Time pressure could also explain it."],
                "pattern": "The focus behaviour was missed in 2 of the last 2 relevant calls.",
                "playable_moments": [moment, buyer_moment],
                "pattern_counts": {
                    **HEADER,
                    "occurrence_count": 2,
                    "relevant_opportunities": 2,
                    "call_ids": [*cited, call],
                },
            },
            "teaching": {
                **HEADER,
                "media": None,
                "text_lesson": {
                    **HEADER,
                    "title": label,
                    "quick_idea": behaviour,
                    "framework": "Action → Owner → Date → Confirmation",
                    "why_it_matters": "The buyer needs decision clarity.",
                    "own_call_example": moment,
                    "better_direction": behaviour,
                    "when_not": "A lost deal needs no invented follow-up.",
                    "checklist": ["The buyer confirms an action and a date."],
                },
            },
            "action": {
                **HEADER,
                "practice": {**HEADER, "exercise": "Rewrite the ending.", "estimated_minutes": 3},
                "mission": {
                    **HEADER,
                    "behaviour": behaviour,
                    "context": "Next relevant buyer opening",
                    "done_when": "The buyer confirms an action and a dated event.",
                    "cue": "Agree an observable next step",
                    "status": "Active",
                    "active_since": "2026-07-20T10:00:00+05:30",
                },
            },
            "progress": {
                **HEADER,
                "mastery_state": "Emerging",
                "trend": None,
                "reason": "Chronological, relevant opportunities only.",
                "relevant_opportunities": 2,
                "correct_execution_count": 0,
                "baseline_relevant_opportunities": 0,
                "baseline_correct_execution_count": 0,
            },
            "direction": {**HEADER, "current": label, "likely_next": "Diagnose before prescribing"},
        },
    }


def indexed(bundle: dict[str, Any]):
    call = index_call(
        key=bundle["metadata"]["call_id"],
        occurred_at=datetime.fromisoformat(bundle["metadata"]["at"]),
        payload_sha256="a" * 64,
        metadata=bundle["metadata"],
        participants=bundle["transcript"]["participants"],
        focus=bundle["coaching"]["current_focus"],
        tenant_id=TENANT,
    )
    assert call is not None
    return call


def test_dataset_skills_map_onto_the_fixed_taxonomy_in_order() -> None:
    assert skill_for("skill-1") == "human_connection_trust"
    assert skill_for("skill-7") == "closing_decision_management"
    assert skill_for("skill-8") == "communication_tonality"
    assert skill_for("qualification") == "qualification"
    for unknown in ("skill-0", "skill-9", "skill-x", None, 7):
        assert skill_for(unknown) is None


def test_call_view_carries_the_authored_coaching_bound_to_its_fictional_call() -> None:
    bundle = sandbox_bundle()
    call = indexed(bundle)
    assert call.call_label == "Fixture · Ira K. · call 1" and call.rep_name == "Nikhil Nivsekar"
    view = call_view(call, bundle, person_id=VIEWER, tenant_id=TENANT)
    assert view.state == "ready" and view.sandbox is True
    assert view.submission_id == call_uuid(TENANT, "syn-fixture-J01-C-01")
    assert view.focus and view.focus.skill_id == "closing_decision_management"
    assert view.mission and view.mission.origin_submission_id == view.submission_id
    assert view.lesson and view.lesson.framework == ("Action", "Owner", "Date", "Confirmation")
    assert view.root_cause.gap_type == "judgment" and view.root_cause.confidence == "low"
    assert [moment.observation for moment in view.evidence] == [
        "Said by Nikhil Nivsekar, the seller.",
        "Said by Ira K., the buyer.",
    ]
    # Text bundles have estimated timing: no audio is ever claimed.
    assert not any(moment.playable for moment in view.evidence)
    assert FICTIONAL in view.limitations


def test_incomplete_authored_coaching_is_unavailable_never_guessed() -> None:
    bundle = sandbox_bundle()
    bundle["coaching"]["action"]["mission"] = {"authored": "action"}
    view = call_view(indexed(bundle), bundle, person_id=VIEWER, tenant_id=TENANT)
    assert view.state == "unavailable" and view.focus is None and view.evidence == ()
    unknown = sandbox_bundle(skill="skill-42")
    view = call_view(indexed(unknown), unknown, person_id=VIEWER, tenant_id=TENANT)
    assert view.state == "unavailable"


def test_rep_view_follows_the_newest_call_with_moments_from_cited_calls() -> None:
    first = sandbox_bundle("syn-fixture-J01-C-01", at="2026-07-21T10:00:00+05:30")
    other = sandbox_bundle(
        "syn-fixture-J02-C-01",
        at="2026-07-22T10:00:00+05:30",
        skill="skill-2",
        label="Diagnose before prescribing",
    )
    newest = sandbox_bundle(
        "syn-fixture-J03-C-01",
        at="2026-07-24T10:00:00+05:30",
        sequence=2,
        cited=("syn-fixture-J01-C-01",),
    )
    calls = tuple(indexed(item) for item in (newest, other, first))
    person = rep_uuid(TENANT, "syn-fixture-R1")
    view = rep_view(
        calls, newest, {"syn-fixture-J01-C-01": first}, person_id=person, tenant_id=TENANT
    )
    assert view.state == "ready" and view.person_id == person and view.sandbox
    assert view.person_name == "Nikhil Nivsekar"
    assert view.analysed_calls == 3 and len(view.calls) == 3
    assert view.focus and view.focus.status == "active"
    # Two from the newest call, one from the cited earlier call.
    assert [m.submission_id for m in view.evidence] == [
        calls[0].submission_id,
        calls[0].submission_id,
        calls[2].submission_id,
    ]
    assert view.mastery.state == "emerging" and view.mastery.trend == "not_enough_evidence"
    assert [point.state for point in view.progress] == ["suggested", "not_covered", "suggested"]
    assert view.development_path.likely_next == "Diagnose before prescribing"


def test_team_names_fictional_reps_with_their_newest_focus() -> None:
    calls = (
        indexed(sandbox_bundle("syn-fixture-J03-C-01", at="2026-07-24T10:00:00+05:30")),
        indexed(
            sandbox_bundle(
                "syn-fixture-J02-C-01",
                rep="syn-fixture-R2",
                rep_name="Asha Rao",
                skill="skill-2",
                label="Diagnose before prescribing",
            )
        ),
        indexed(sandbox_bundle("syn-fixture-J01-C-01", at="2026-07-21T10:00:00+05:30")),
    )
    view = team_view(calls, person_id=VIEWER, tenant_id=TENANT)
    assert view.scope == "sandbox" and view.named_rep_details and view.sandbox
    assert (view.analysed_calls, view.rep_count) == (3, 2)
    assert [(s.skill_id, s.suggestion_calls) for s in view.suggestions] == [
        ("closing_decision_management", 2),
        ("discovery_deep_understanding", 1),
    ]
    assert [(rep.name, rep.calls) for rep in view.reps] == [
        ("Asha Rao", 1),
        ("Nikhil Nivsekar", 2),
    ]
    assert view.reps[1].latest_call_at == datetime(2026, 7, 24, 4, 30, tzinfo=UTC)


def test_real_team_totals_cannot_carry_names() -> None:
    rep = TeamRep(person_id=uuid4(), name="Real Person", calls=1)
    common: dict[str, Any] = dict(
        person_id=VIEWER,
        tenant_id=TENANT,
        analysed_calls=1,
        pending_calls=0,
        unavailable_calls=0,
        history_limited=False,
        suggestions=(),
        limitations=(),
    )
    for unsafe in (
        {"reps": (rep,)},
        {"named_rep_details": True},
        {"named_rep_details": True, "reps": (rep,), "scope": "sandbox"},
    ):
        with pytest.raises(ValidationError):
            TeamCoachingView(**common, **unsafe)
    assert TeamCoachingView(**common).named_rep_details is False
