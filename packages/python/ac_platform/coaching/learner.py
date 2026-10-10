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
        "Coaching is provisional and can be revised when you add context.",
        "Skill observations do not identify the reason for a gap or prove mastery.",
        "Focus is reconstructed from retained history; permanent state and feedback are pending.",
    ]
    if history_limited:
        limitations.append("Only the most recent 40 retained calls are included.")
    groups: dict[tuple[str, str], list[SkillObservation]] = defaultdict(list)
    selected: tuple[str, str] | None = None
    origin: SkillObservation | None = None
    for call in calls:
        for skill in call.skills:
            key = (call.comparison_key, skill.skill_id)
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
            pattern=Pattern(
                summary="No supported skill-linked next-call mission is available yet."
            ),
            evidence=(),
            practice=None,
            mission=None,
            lesson=None,
            development_path=Path(
                current=None, explanation="Your path starts with more call evidence."
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
    focus = Focus(
        skill_id=origin.skill_id,
        label=label,
        explanation=origin.improvement or origin.observation,
        why_it_matters=origin.why_it_matters or origin.observation,
        selected_reason=(
            f"{count} of {total} comparable calls with evidence for this skill include a coaching "
            "suggestion. This does not establish that the same behavior recurred."
            if recurring
            else "One supported call suggestion; we are still learning your pattern."
        ),
        selected_at=mission.active_since,
        status="active" if recurring else "provisional",
        verdict=mission.behavior,
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
                f"This skill has coaching suggestions in {count} of {total} comparable calls. "
                "Replay the evidence to compare the situations."
                if recurring
                else "One call supports this suggestion. A recurring pattern is not established."
            ),
        ),
        evidence=evidence,
        mission=mission,
        practice=origin.practice
        or Practice(
            exercise="Replay one moment. Say one alternative response in your own words.",
            success_condition=mission.done_when,
        ),
        lesson=lesson_for(origin.skill_id, evidence[0], mission),
        development_path=Path(
            current=label,
            likely_next=candidates[0] if candidates else None,
            later=candidates[1] if len(candidates) > 1 else None,
            explanation=(
                "The next focus depends on future relevant evidence. "
                "Your current mission stays active."
            ),
        ),
        reflection_question="What influenced your response in this moment?",
    )
