"""Replay retained, comparable skill evidence without inventing behavior outcomes.

The first slice deliberately makes no mastery/regression decisions from report
labels. Mission completion and reviewed feedback require durable coaching state,
not an analytics event, lesson open, date change or one good call.
"""

from collections import defaultdict
from uuid import UUID

from ac_platform.coaching.contracts import (
    CallHistory,
    CoachingView,
    Focus,
    Moment,
    Path,
    Pattern,
    Practice,
    ProgressPoint,
    SkillObservation,
)
from ac_platform.coaching.lessons import lesson_for


def _moments(rows: list[SkillObservation]) -> tuple[Moment, ...]:
    """Prefer distinct calls, then distinct moments; never fill a quota with repeats."""
    result: list[Moment] = []
    seen: set[tuple[UUID, str, int, int]] = set()
    for position in range(8):
        for row in reversed(rows):
            if position >= len(row.evidence):
                continue
            moment = row.evidence[position]
            key = (moment.submission_id, moment.segment_id, moment.start_ms, moment.end_ms)
            if key in seen:
                continue
            seen.add(key)
            result.append(moment)
            if len(result) == 4:
                return tuple(result)
    return tuple(result)


def build_learner(
    history: tuple[CallHistory, ...],
    *,
    person_id: UUID,
    tenant_id: UUID,
    pending_calls: int = 0,
    unavailable_calls: int = 0,
    history_limited: bool = False,
) -> CoachingView:
    """Keep the first supported mission until explicit evidence can supersede it.

    A source is counted once even if reuploaded/reanalysed. Version boundaries
    start a new comparison group; an unlinked report revision is not progress.
    The read model replays history rather than mutating state on GET.
    """
    ordered = sorted(history, key=lambda call: (call.created_at, str(call.submission_id)))
    unique: dict[str, CallHistory] = {}
    for call in ordered:
        unique.setdefault(call.source_sha256, call)
    calls = list(unique.values())
    limitations = [
        "This is Sales Xray's reading of your calls. It can change when you add context.",
        "Your reports show where a skill came up. They don't prove why, "
        "or that you have mastered it.",
        "Your focus is worked out from your saved calls each time you open Coaching.",
    ]
    if history_limited:
        limitations.append("Only your 40 most recent calls are included.")
    groups: dict[tuple[str, str], list[SkillObservation]] = defaultdict(list)
    selected: tuple[str, str] | None = None
    origin: SkillObservation | None = None
    for call in calls:
        for skill in call.skills:
            key = (
                call.comparison_key if skill.basis == "skill_evidence" else str(call.submission_id),
                skill.skill_id,
            )
            groups[key].append(skill)
            if selected is None and skill.improvement and skill.mission:
                selected, origin = key, skill
    common = dict(
        person_id=person_id,
        tenant_id=tenant_id,
        analysed_calls=len(calls),
        pending_calls=pending_calls,
        unavailable_calls=unavailable_calls,
        history_limited=history_limited,
        limitations=tuple(limitations),
    )
    if selected is None or origin is None:
        return CoachingView(
            **common,
            state="not_enough_evidence",
            focus=None,
            pattern=Pattern(summary="Your calls don't show one skill to work on yet."),
            evidence=(),
            practice=None,
            mission=None,
            lesson=None,
            development_path=Path(
                current=None, explanation="Your path starts after a few more calls."
            ),
            reflection_question=None,
        )
    relevant = groups[selected]
    attention = [row for row in relevant if row.improvement is not None]
    evidence = _moments(attention)
    mission = origin.mission
    assert mission is not None
    count, total = len(attention), len(relevant)
    recurring = len({m.submission_id for m in evidence}) >= 2
    label = origin.label
    suggestion = origin.basis == "report_suggestion"
    if suggestion:
        limitations.append(
            "This focus comes from one report's suggestion, not a skill check. "
            "It isn't a pattern and doesn't measure progress."
        )
        common["limitations"] = tuple(limitations)
    focus = Focus(
        skill_id=origin.skill_id,
        label=label,
        explanation=origin.improvement or origin.observation,
        why_it_matters=origin.why_it_matters or origin.observation,
        selected_reason=(
            "Your call's report suggested this."
            if suggestion
            else f"Your reports flagged it in {count} of your last {total} calls "
            "that checked this skill."
            if recurring
            else "One call suggested this. We're still learning your pattern."
        ),
        selected_at=mission.active_since,
        status="active" if recurring else "provisional",
        verdict=mission.behavior,
    )
    # One point per comparable call; other evaluator versions are not compared.
    # Report suggestions without an assessed skill stay a single call.
    progress = tuple(
        ProgressPoint(
            submission_id=call.submission_id,
            created_at=call.created_at,
            state=(
                "not_covered"
                if row is None
                else "suggested"
                if row.improvement is not None
                else "no_suggestion"
            ),
            after_mission=call.created_at > mission.active_since,
        )
        for call in calls
        if (
            call.comparison_key == selected[0]
            if not suggestion
            else str(call.submission_id) == selected[0]
        )
        for row in (next((s for s in call.skills if s.skill_id == selected[1]), None),)
    )
    # A dynamic shortlist, not a rigid curriculum or an inferred core strength.
    candidates = [
        rows[-1].label
        for (version, skill_id), rows in groups.items()
        if version == selected[0]
        and skill_id != selected[1]
        and sum(row.improvement is not None for row in rows) >= 2
    ]
    return CoachingView(
        **common,
        state="ready",
        focus=focus,
        pattern=Pattern(
            relevant_call_count=total,
            attention_call_count=count,
            summary=(
                f"It came up on {len({m.submission_id for m in evidence})} different calls, "
                "not just one. Replay the moments below and compare what happened each time."
                if recurring
                else "So far this comes from one call. It isn't a pattern yet."
            ),
        ),
        evidence=evidence,
        progress=progress[-40:],
        mission=mission,
        practice=origin.practice
        or Practice(
            exercise="Replay one moment. Say a better response out loud, in your own words.",
            success_condition=mission.done_when,
        ),
        lesson=lesson_for(origin.skill_id, evidence[0], mission),
        strength=next((call.strength for call in reversed(calls) if call.strength), None),
        development_path=Path(
            current=label,
            likely_next=candidates[0] if candidates else None,
            later=candidates[1] if len(candidates) > 1 else None,
            explanation=(
                "Your next focus depends on your next calls. Your current mission stays until then."
            ),
        ),
        reflection_question="What made you respond that way in this moment?",
    )
