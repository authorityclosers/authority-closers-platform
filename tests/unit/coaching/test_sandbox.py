"""AC Sandbox Coaching maps authored fictional coaching; it never guesses a field."""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from ac_platform.coaching.sandbox import (
    FICTIONAL,
    ReportBind,
    SandboxIndex,
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
    assert view.rep_person_id == rep_uuid(TENANT, "syn-fixture-R1")
    assert view.rep_name == "Nikhil Nivsekar"
    assert view.submission_id == call_uuid(TENANT, "syn-fixture-J01-C-01")
    assert view.focus and view.focus.skill_id == "closing_decision_management"
    assert view.mission and view.mission.origin_submission_id == view.submission_id
    assert view.lesson and view.lesson.framework == ("Action", "Owner", "Date", "Confirmation")
    assert view.lesson.own_call and view.lesson.own_call.observation.startswith("“Sure, we")
    assert view.root_cause.gap_type == "judgment" and view.root_cause.confidence == "low"
    assert [moment.observation for moment in view.evidence] == [
        "Said by Nikhil Nivsekar, the seller.",
        "Said by Ira K., the buyer.",
    ]
    # Text bundles have estimated timing: no audio is ever claimed.
    assert not any(moment.playable for moment in view.evidence)
    assert FICTIONAL in view.limitations


def test_the_dev_loaders_call_and_member_ids_open_the_same_authored_coaching() -> None:
    # Strike C's dev loader writes real calls and members under its own ids
    # (scripts/dev/load-sales-xray-sandbox.py `identifier`); its fixture values.
    tenant = UUID("90ec1979-0d85-4829-ba8d-cabde2a9a9d3")
    canonical_call = UUID("fc52d93e-36bd-50cb-b575-92bbb599d99e")
    canonical_rep = UUID("eb76f836-0b6b-59aa-b5e6-d80e9490a834")
    bundle = sandbox_bundle("syn-fixture-call-1")
    call = index_call(
        key="syn-fixture-call-1",
        occurred_at=datetime.fromisoformat(bundle["metadata"]["at"]),
        payload_sha256="a" * 64,
        metadata=bundle["metadata"],
        participants=bundle["transcript"]["participants"],
        focus=bundle["coaching"]["current_focus"],
        tenant_id=tenant,
    )
    assert call is not None
    assert call.submission_id == UUID("1913fb70-19f3-5576-888c-bef54be66192")
    index = SandboxIndex((call,))
    legacy = call_view(index.call(call.submission_id), bundle, person_id=VIEWER, tenant_id=tenant)
    found = index.call(canonical_call)
    assert found is not None and found.loaded
    loaded = call_view(found, bundle, person_id=VIEWER, tenant_id=tenant)
    # The same authored focus, mission and quotes, with timing and text-only status kept.
    assert loaded.focus == legacy.focus and loaded.lesson and legacy.lesson
    assert loaded.mission and legacy.mission
    assert loaded.mission.behavior == legacy.mission.behavior
    assert [(m.quote, m.start_ms, m.end_ms, m.playable) for m in loaded.evidence] == [
        (m.quote, m.start_ms, m.end_ms, m.playable) for m in legacy.evidence
    ]
    # The call ids in the view are the loader's, so /coaching?call=<loader id> opens it.
    # (The Report's own Coaching view also binds the recording and source hashes,
    # which a sandbox view does not carry; it shows its report-focus fallback.)
    assert loaded.submission_id == canonical_call
    assert loaded.mission.origin_submission_id == canonical_call
    assert {m.submission_id for m in loaded.evidence} == {canonical_call}
    assert loaded.rep_person_id == canonical_rep
    assert legacy.rep_person_id == UUID("59ae4eb5-75bc-5264-ba66-d4d4f66f14d0")
    # The loader's member id opens the rep, with calls linked by the loader's ids.
    assert index.rep_calls(tenant, canonical_rep)[0].submission_id == canonical_call
    assert index.rep_calls(tenant, legacy.rep_person_id)[0].submission_id == call.submission_id
    assert index.call(uuid4()) is None and index.rep_calls(tenant, uuid4()) == ()
    # Another tenant's ids never match.
    assert index.call(call_uuid(uuid4(), "syn-fixture-call-1")) is None


def test_a_loader_id_view_bound_to_its_real_report_cites_the_loaders_segments() -> None:
    # The Report checks moments against its own recording, hashes and segments;
    # the loader made each line one segment (full id, the line's timing and text).
    bundle = sandbox_bundle("syn-fixture-call-1")
    bundle["transcript"]["lines"] = [
        {
            "line_id": "syn-fixture-call-1:L001",
            "person_id": "syn-fixture-BUY",
            "start_ms": 900,
            "end_ms": 3600,
            "text": "माझा प्रश्न scope बद्दल आहे. What would we test first?",
        },
        {
            "line_id": "syn-fixture-call-1:L002",
            "person_id": "syn-fixture-R1",
            "start_ms": 3900,
            "end_ms": 7600,
            "text": "Okay. Sure, we will be in touch sometime. Thanks, bye.",
        },
    ]
    tenant = UUID("90ec1979-0d85-4829-ba8d-cabde2a9a9d3")
    call = index_call(
        key="syn-fixture-call-1",
        occurred_at=datetime.fromisoformat(bundle["metadata"]["at"]),
        payload_sha256="a" * 64,
        metadata=bundle["metadata"],
        participants=bundle["transcript"]["participants"],
        focus=bundle["coaching"]["current_focus"],
        tenant_id=tenant,
    )
    assert call is not None
    loaded = SandboxIndex((call,)).call(call.loaded_id)
    assert loaded is not None
    bind = ReportBind(
        recording_id=UUID(int=77),
        source_sha256="b" * 64,
        transcript_revision="c" * 64,
        report_revision="d" * 64,
    )
    view = call_view(loaded, bundle, person_id=VIEWER, tenant_id=tenant, bind=bind)
    assert view.state == "ready"
    assert (view.recording_id, view.source_sha256, view.transcript_revision) == (
        UUID(int=77),
        "b" * 64,
        "c" * 64,
    )
    assert view.report_revision == "d" * 64
    by_segment = {line["line_id"]: line for line in bundle["transcript"]["lines"]}
    for moment in (*view.evidence, view.lesson.own_call):
        line = by_segment[moment.segment_id]
        assert (moment.start_ms, moment.end_ms) == (line["start_ms"], line["end_ms"])
        assert moment.quote in line["text"] and moment.recording_id == UUID(int=77)
        assert moment.playable is False
    # Without the real report the view keeps its own (legacy) identity.
    unbound = call_view(loaded, bundle, person_id=VIEWER, tenant_id=tenant)
    assert unbound.recording_id != UUID(int=77)


def test_incomplete_authored_coaching_is_unavailable_never_guessed() -> None:
    bundle = sandbox_bundle()
    bundle["coaching"]["action"]["mission"] = {"authored": "action"}
    view = call_view(indexed(bundle), bundle, person_id=VIEWER, tenant_id=TENANT)
    assert view.state == "unavailable" and view.focus is None and view.evidence == ()
    unknown = sandbox_bundle(skill="skill-42")
    view = call_view(indexed(unknown), unknown, person_id=VIEWER, tenant_id=TENANT)
    assert view.state == "unavailable"


def test_the_datasets_template_lines_read_in_plain_sales_words() -> None:
    bundle = sandbox_bundle()
    coaching = bundle["coaching"]
    coaching["diagnosis"]["pattern"] = (
        "The focus behaviour was missed in 2 of the last 2 relevant calls"
        " available as of this call."
    )
    coaching["diagnosis"]["alternatives"] = [
        "Time pressure or missing context could also explain the behaviour."
    ]
    coaching["teaching"]["text_lesson"]["why_it_matters"] = (
        "The buyer needs decision clarity and a relevant response."
    )
    coaching["action"]["practice"]["exercise"] = (
        "Rewrite the cited seller response using the focus behaviour; rehearse once with a pause."
    )
    coaching["progress"]["reason"] = "Per-call observation does not establish longitudinal mastery."
    view = rep_view(
        (indexed(bundle),),
        bundle,
        {},
        person_id=rep_uuid(TENANT, "syn-fixture-R1"),
        tenant_id=TENANT,
    )
    # The rep's page reads across calls: the reason names their newest call,
    # pillar 1 keeps the count and the pattern points at the moments.
    assert view.focus and view.focus.selected_reason == "It needed work on their newest call."
    assert view.focus.explanation == "It needed work in 2 of the last 2 calls on this skill."
    assert view.pattern.summary == (
        "It needed work on 2 different calls. "
        "Replay the moments below and see what they did each time."
    )
    one_call = call_view(indexed(bundle), bundle, person_id=VIEWER, tenant_id=TENANT)
    assert one_call.focus and one_call.focus.selected_reason == "It needed work on this call."
    assert view.root_cause.alternatives == (
        "Time pressure or missing context could also explain it.",
    )
    assert view.lesson and view.lesson.why_it_matters.startswith("The buyer needs a clear way")
    assert view.practice and view.practice.exercise.startswith("Rewrite what was said")
    assert view.mission and view.mission.context == "The next time a buyer gives this opening."
    assert view.mastery.explanation == "One call can’t show progress over time."
    # Without the dataset's own line, the progress note is about "them" too.
    del coaching["progress"]["reason"]
    unexplained = rep_view(
        (indexed(bundle),),
        bundle,
        {},
        person_id=rep_uuid(TENANT, "syn-fixture-R1"),
        tenant_id=TENANT,
    )
    assert "Their reports don't count" in unexplained.mastery.explanation
    # A line the dataset wrote for this call alone stays word for word.
    one = sandbox_bundle()
    one["coaching"]["diagnosis"]["pattern"] = "The rep skipped the signer twice."
    view = call_view(indexed(one), one, person_id=VIEWER, tenant_id=TENANT)
    assert view.focus and view.focus.explanation == "The rep skipped the signer twice."


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
    # The two closing calls share a focus skill; the discovery call's is alone.
    flags = {row.submission_id: row.recurring for row in view.calls}
    assert flags[calls[0].submission_id] is True and flags[calls[2].submission_id] is True
    assert flags[calls[1].submission_id] is False


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
                at="2026-07-22T10:00:00+05:30",
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
    # Most recently active first.
    assert [(rep.name, rep.calls) for rep in view.reps] == [
        ("Nikhil Nivsekar", 2),
        ("Asha Rao", 1),
    ]
    assert view.reps[0].latest_call_at == datetime(2026, 7, 24, 4, 30, tzinfo=UTC)


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


def test_ready_sandbox_views_always_carry_a_moment_and_consistent_counts() -> None:
    # No playable moments: the lesson's own-call example becomes the moment.
    bundle = sandbox_bundle()
    bundle["coaching"]["diagnosis"]["playable_moments"] = []
    view = call_view(indexed(bundle), bundle, person_id=VIEWER, tenant_id=TENANT)
    assert view.state == "ready" and len(view.evidence) == 1
    assert view.lesson and view.lesson.own_call is not None
    # Neither: unavailable, never a guessed moment.
    bundle["coaching"]["teaching"]["text_lesson"]["own_call_example"] = None
    view = call_view(indexed(bundle), bundle, person_id=VIEWER, tenant_id=TENANT)
    assert view.state == "unavailable"
    # Half a count pair, or more occurrences than opportunities, is not shown.
    odd = sandbox_bundle()
    odd["coaching"]["progress"].pop("correct_execution_count")
    odd["coaching"]["diagnosis"]["pattern_counts"]["occurrence_count"] = 5
    rep = rep_view(
        (indexed(odd),), odd, {}, person_id=rep_uuid(TENANT, "syn-fixture-R1"), tenant_id=TENANT
    )
    assert rep.mastery.relevant_count is None and rep.mastery.correct_count is None
    assert rep.pattern.attention_call_count <= rep.pattern.relevant_call_count
    assert rep.pattern.occurrence_count is None
