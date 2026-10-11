"""AC Sandbox Coaching: authored fictional per-call coaching in the normal views.

A flagged sandbox organisation (#437) holds fictional calls whose coaching was
authored with the dataset. Only the person who imported them reads them, as the
import contract requires (`private_coaching`), and every view says it is
fictional. Nothing here analyses, scores, writes or calls a provider. A field
the dataset did not author makes that call unreadable; it is never guessed.
"""

import re
from collections import OrderedDict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Any, get_args
from uuid import UUID, uuid5

from sqlalchemy import cast, func, select, true
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession

from ac_platform.coaching.call import CallCoachingView
from ac_platform.coaching.contracts import (
    THEIR_MASTERY,
    CallSummary,
    CoachingView,
    Focus,
    GapType,
    Mastery,
    MasteryState,
    Mission,
    Moment,
    Path,
    Pattern,
    Practice,
    ProgressPoint,
    RootCause,
    TextLesson,
    Trend,
)
from ac_platform.coaching.team import LABELS, TeamCoachingView, TeamRep, TeamSuggestion
from ac_platform.conversation_intelligence.synthetic_import_models import (
    ConversationSandboxOrganisation,
    ConversationSyntheticRecord,
)

# The dataset's `skill-N` is the Nth skill of the same fixed eight-skill taxonomy.
SKILL_IDS = (
    "human_connection_trust",
    "discovery_deep_understanding",
    "qualification",
    "problem_impact_desire",
    "solution_relevance_presentation",
    "certainty_objection_intelligence",
    "closing_decision_management",
    "communication_tonality",
)
NAMESPACE = UUID("6f1d0c47-5a7e-4f43-9a55-1d3c0e0b8a21")
FICTIONAL = "Fictional AC Sandbox call. Its coaching was written with it, not from an analysis."
IMPORTER_ONLY = "Only the person who imported these sandbox calls sees their coaching."
SOURCE = "Fictional AC Sandbox lesson, written with the calls"
HISTORY_LIMIT = 40
MAX_MOMENTS = 4
# The dataset repeats a few authoring templates in system words. Show them in
# the plain sales words the rest of Coaching uses, with the same meaning; every
# other authored line passes through unchanged.
_ONE_CALL = (
    "From this one call. Earlier calls show whether it repeats; a won or lost deal doesn’t "
    "prove why."
)
PLAIN = {
    "The labelled behaviour occurs in this call.": "It needed work on this call.",
    "Keep the same focus; this call alone cannot establish mastery.": (
        "Keep the same focus. One call can’t show it’s mastered."
    ),
    "The cited response or commitment is observed here; maintain it on the next relevant "
    "opportunity without inferring mastery.": (
        "It was done well on this call. Keep doing it next time; one call doesn’t prove it yet."
    ),
    "One-call evidence only; use the linked rep history for longitudinal claims.": (
        "From this one call. Earlier calls show whether it repeats."
    ),
    "One-call evidence only. Linked history can be reviewed separately; a win or loss does not "
    "prove causation.": _ONE_CALL,
    "This key uses only this call. Linked earlier calls may be examined separately; the final "
    "outcome is not proof of causation.": _ONE_CALL,
    "One-call evidence only; linked history can be examined separately, and the final outcome "
    "is not proof of causation.": _ONE_CALL,
    "Time pressure or missing context could also explain the behaviour.": (
        "Time pressure or missing context could also explain it."
    ),
    "The buyer needs decision clarity and a relevant response.": (
        "The buyer needs a clear way to decide and an answer that fits what they asked."
    ),
    "Rewrite the cited seller response using the focus behaviour; rehearse once with a pause.": (
        "Rewrite what was said in the moment above, the better way. Then say it out loud once, "
        "with a pause."
    ),
    "Next relevant buyer opening": "The next time a buyer gives this opening.",
    "Next relevant call with this buyer requirement": "The next call where the buyer needs this.",
    "Next relevant call in this selling context": "The next call like this one.",
    "Per-call observation does not establish longitudinal mastery.": (
        "One call can’t show progress over time."
    ),
    "Chronological, relevant opportunities only. No future calls used; no mastery inferred from "
    "a single success.": (
        "Counted in call order, only where the skill applied. One good call doesn’t mean it’s "
        "mastered."
    ),
}
_MISSED = re.compile(
    r"The focus behaviour was missed in (\d+) of the last (\d+) relevant calls"
    r"(?: available as of this call)?\."
)


def call_uuid(tenant_id: UUID, key: str) -> UUID:
    return uuid5(NAMESPACE, f"{tenant_id}:call:{key}")


def rep_uuid(tenant_id: UUID, key: str) -> UUID:
    return uuid5(NAMESPACE, f"{tenant_id}:rep:{key}")


# The dev loader (scripts/dev/load-sales-xray-sandbox.py) also turns these records
# into real calls and members under its own ids, so Calls → Report → Coaching
# arrives with those. Either id opens the same authored coaching.
LOADER_NAMESPACE = UUID("1dfdfac9-bfa2-49ab-b061-d98776454e0f")


def loaded_uuid(tenant_id: UUID, kind: str, key: str) -> UUID:
    return uuid5(LOADER_NAMESPACE, f"{tenant_id}:{kind}:{key}")


def skill_for(value: Any) -> str | None:
    if isinstance(value, str) and value.startswith("skill-") and value[6:].isdigit():
        index = int(value[6:])
        if 1 <= index <= len(SKILL_IDS):
            return SKILL_IDS[index - 1]
    return value if value in SKILL_IDS else None


def _slug(value: Any) -> str:
    return (
        "_".join(value.lower().replace("/", " ").replace("-", " ").split())
        if isinstance(value, str)
        else ""
    )


def _gap(value: Any) -> GapType:
    slug = _slug(value)
    return slug if slug in get_args(GapType) else "uncertain"  # type: ignore[return-value]


def _mastery(value: Any) -> MasteryState:
    slug = _slug(value)
    return slug if slug in get_args(MasteryState) else "not_enough_evidence"  # type: ignore[return-value]


def _trend(value: Any) -> Trend:
    slug = _slug(value)
    return slug if slug in get_args(Trend) else "not_enough_evidence"  # type: ignore[return-value]


def _text(value: Any, limit: int = 4000) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()[:limit]
    return None


def _plain(value: Any, limit: int = 4000) -> str | None:
    """An authored line, in plain words when it is one of the dataset's templates."""
    text = _text(value, limit)
    if text is None:
        return None
    if missed := _MISSED.fullmatch(text):
        return f"It needed work in {missed[1]} of the last {missed[2]} calls on this skill."
    return PLAIN.get(text, text)


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _int(value: Any) -> int | None:
    return value if type(value) is int and value >= 0 else None


def _when(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else None


def _business(key: str) -> str:
    # `syn-advisory` → "Advisory"
    return key.removeprefix("syn-").replace("-", " ").strip().title() or "Sandbox"


@dataclass(frozen=True)
class SandboxCall:
    key: str
    submission_id: UUID
    occurred_at: datetime
    payload_sha256: str
    rep_key: str
    rep_name: str
    call_label: str
    skill_id: str | None
    focus_label: str | None
    # The dev loader's ids for this call and its rep (real call and member rows).
    loaded_id: UUID
    loaded_rep_id: UUID
    # Read through the loader's ids: every id in the view is the loader's.
    loaded: bool = False

    def as_loaded(self) -> "SandboxCall":
        return replace(self, submission_id=self.loaded_id, loaded=True)


@dataclass(frozen=True)
class SandboxIndex:
    calls: tuple[SandboxCall, ...]  # newest first

    def call(self, submission_id: UUID) -> SandboxCall | None:
        for call in self.calls:
            if call.submission_id == submission_id:
                return call
            if call.loaded_id == submission_id:
                return call.as_loaded()
        return None

    def rep_calls(self, tenant_id: UUID, person_id: UUID) -> tuple[SandboxCall, ...]:
        legacy = tuple(c for c in self.calls if rep_uuid(tenant_id, c.rep_key) == person_id)
        return legacy or tuple(c.as_loaded() for c in self.calls if c.loaded_rep_id == person_id)


def _names(participants: Any) -> dict[str, tuple[str, str]]:
    """person_id → (name, role) from the authored participant list."""
    names: dict[str, tuple[str, str]] = {}
    for item in participants if isinstance(participants, list) else ():
        row = _dict(item)
        key, name = row.get("person_id"), _text(row.get("name"), 120)
        if isinstance(key, str) and name:
            names[key] = (name, str(row.get("speaker") or ""))
    return names


def index_call(
    *,
    key: str,
    occurred_at: datetime,
    payload_sha256: str,
    metadata: Any,
    participants: Any,
    focus: Any,
    tenant_id: UUID,
) -> SandboxCall | None:
    meta, current = _dict(metadata), _dict(focus)
    rep_key, business = meta.get("rep_id"), meta.get("business_id")
    if not isinstance(rep_key, str) or not isinstance(business, str):
        return None
    names = _names(participants)
    rep_name = names.get(rep_key, ("", ""))[0] or "Fictional rep"
    buyer = next((name for pid, (name, role) in names.items() if role == "prospect"), None)
    sequence = _int(meta.get("sequence"))
    label = " · ".join(
        part
        for part in (
            _business(business),
            buyer,
            f"call {sequence}" if sequence else None,
        )
        if part
    )
    return SandboxCall(
        key=key,
        submission_id=call_uuid(tenant_id, key),
        occurred_at=occurred_at if occurred_at.tzinfo else occurred_at.replace(tzinfo=UTC),
        payload_sha256=payload_sha256,
        rep_key=rep_key,
        rep_name=rep_name,
        call_label=label[:256],
        skill_id=skill_for(current.get("skill_id")),
        focus_label=_text(current.get("label"), 240),
        loaded_id=loaded_uuid(tenant_id, "submission", key),
        loaded_rep_id=loaded_uuid(tenant_id, "person", rep_key),
    )


# ---------- One authored call → the normal Coaching parts ----------


@dataclass(frozen=True)
class ReportBind:
    """The dev loader's real report for a call opened by its loader id.

    The Report checks every moment against its own recording, source and
    transcript; the loader made each authored line one segment (full line id,
    the line's own timing and text), so a bound moment cites exactly that.
    """

    recording_id: UUID
    source_sha256: str
    transcript_revision: str
    report_revision: str


def _moments(
    call: SandboxCall, payload: dict[str, Any], raw: Any, bind: ReportBind | None = None
) -> list[Moment]:
    lines = {
        line.get("line_id"): line
        for line in _dict(payload.get("transcript")).get("lines") or ()
        if isinstance(line, dict)
    }
    names = _names(_dict(payload.get("transcript")).get("participants"))
    moments: list[Moment] = []
    for item in raw if isinstance(raw, list) else [raw]:
        row = _dict(item)
        quote = _text(row.get("quote"), 2000)
        start, end = _int(row.get("start_ms")), _int(row.get("end_ms"))
        ids = row.get("line_ids")
        line_id = ids[0] if isinstance(ids, list) and ids and isinstance(ids[0], str) else None
        if not quote or start is None or end is None or end <= start or line_id is None:
            continue
        line = _dict(lines.get(line_id))
        speaker = names.get(str(line.get("person_id")))
        role = {"rep": "the seller", "prospect": "the buyer"}.get(speaker[1] if speaker else "")
        segment = line_id.rsplit(":", 1)[-1][:128]
        if bind is not None:
            # Exactly the loader's citation of this line (adapted_report).
            text = _text(line.get("text"), 100_000)
            line_start, line_end = _int(line.get("start_ms")), _int(line.get("end_ms"))
            if not text or line_start is None or line_end is None or line_end <= line_start:
                continue
            segment, start, end = line_id[:128], line_start, line_end
            quote = quote if quote in text else text[:1000]
        moments.append(
            Moment(
                submission_id=call.submission_id,
                recording_id=bind.recording_id
                if bind
                else uuid5(NAMESPACE, f"recording:{call.submission_id}"),
                source_sha256=bind.source_sha256 if bind else call.payload_sha256,
                transcript_revision=bind.transcript_revision
                if bind
                else f"synthetic:{call.payload_sha256}",
                created_at=call.occurred_at,
                call_label=call.call_label,
                segment_id=segment,
                quote=quote,
                start_ms=start,
                end_ms=end,
                observation=(
                    f"Said by {speaker[0]}, {role}." if speaker and role else "From this call."
                ),
                # Text bundles carry estimated timing; no audio is claimed.
                playable=False,
            )
        )
    return moments


@dataclass(frozen=True)
class Authored:
    focus: Focus
    root_cause: RootCause
    evidence: tuple[Moment, ...]
    lesson: TextLesson
    practice: Practice
    mission: Mission
    pattern: str
    payload: dict[str, Any]


def authored(
    call: SandboxCall, payload: dict[str, Any], bind: ReportBind | None = None
) -> Authored | None:
    """The call's authored coaching in the normal shapes, or None if incomplete."""
    coaching = _dict(payload.get("coaching"))
    current, diagnosis = _dict(coaching.get("current_focus")), _dict(coaching.get("diagnosis"))
    teaching, action = _dict(coaching.get("teaching")), _dict(coaching.get("action"))
    lesson, mission_raw = _dict(teaching.get("text_lesson")), _dict(action.get("mission"))
    practice_raw = _dict(action.get("practice"))
    skill = skill_for(current.get("skill_id"))
    label = _text(current.get("label"), 240)
    behavior, done_when = _text(mission_raw.get("behaviour")), _text(mission_raw.get("done_when"))
    if not skill or not label or not behavior or not done_when:
        return None
    gap = _gap(diagnosis.get("gap_type"))
    mission = Mission(
        skill_id=skill,
        behavior=behavior,
        context=_plain(mission_raw.get("context")) or "The next time this kind of moment comes up.",
        done_when=done_when,
        cue=_text(mission_raw.get("cue"), 240) or label,
        active_since=_when(mission_raw.get("active_since")) or call.occurred_at,
        origin_submission_id=call.submission_id,
    )
    evidence = tuple(_moments(call, payload, diagnosis.get("playable_moments"), bind)[:MAX_MOMENTS])
    # The lesson's "Your call" box shows the moment's words, not a speaker tag.
    own = [
        moment.model_copy(update={"observation": f"“{moment.quote}”"[:4000]})
        for moment in _moments(call, payload, lesson.get("own_call_example"), bind)
    ]
    if not evidence and own:
        evidence = (_moments(call, payload, lesson.get("own_call_example"), bind)[0],)
    if not evidence:
        # A focus needs at least one inspectable moment (spec 12.2); without
        # one the call's coaching is unavailable, never a guessed moment.
        return None
    pattern = _plain(diagnosis.get("pattern")) or "This call’s written focus."
    why = _plain(lesson.get("why_it_matters")) or pattern
    better = _text(lesson.get("better_direction")) or behavior
    focus = Focus(
        skill_id=skill,
        label=label,
        explanation=pattern,
        why_it_matters=why,
        selected_reason=_plain(current.get("selected_reason")) or "Written for this call.",
        selected_at=call.occurred_at,
        status="provisional",
        verdict=behavior,
    )
    framework = _text(lesson.get("framework"), 400) or ""
    checklist = lesson.get("checklist")
    return Authored(
        focus=focus,
        root_cause=RootCause(
            hypothesis=_text(diagnosis.get("root_cause_hypothesis")) or RootCause().hypothesis,
            gap_type=gap,
            confidence=(
                _slug(diagnosis.get("confidence"))
                if _slug(diagnosis.get("confidence")) in ("high", "medium", "low")
                else "uncertain"
            ),
            alternatives=tuple(
                text
                for text in (_plain(item, 600) for item in diagnosis.get("alternatives") or ())
                if text
            )[:3],
        ),
        evidence=evidence,
        lesson=TextLesson(
            title=_text(lesson.get("title"), 240) or label,
            quick_idea=_text(lesson.get("quick_idea")) or better,
            framework=tuple(part.strip() for part in framework.split("→") if part.strip())[:6],
            why_it_matters=why,
            good_looks_like=better,
            better_direction=better,
            example_wording=(),
            when_to_use=mission.context,
            when_not=_text(lesson.get("when_not")) or "When the moment does not apply.",
            checklist=tuple(
                text
                for text in (
                    _text(item, 600) for item in (checklist if isinstance(checklist, list) else ())
                )
                if text
            )[:5],
            source=SOURCE,
            own_call=own[0] if own else evidence[0],
            next_call_connection=behavior,
        ),
        practice=Practice(
            exercise=_plain(practice_raw.get("exercise"))
            or "Replay one moment. Say one alternative response in your own words.",
            success_condition=done_when,
            gap_type=gap,
            estimated_minutes=_int(practice_raw.get("estimated_minutes")),
        ),
        mission=mission,
        pattern=pattern,
        payload=coaching,
    )


def call_view(
    call: SandboxCall,
    payload: dict[str, Any],
    *,
    person_id: UUID,
    tenant_id: UUID,
    bind: ReportBind | None = None,
) -> CallCoachingView:
    common: dict[str, Any] = dict(
        person_id=person_id,
        tenant_id=tenant_id,
        submission_id=call.submission_id,
        recording_id=bind.recording_id
        if bind
        else uuid5(NAMESPACE, f"recording:{call.submission_id}"),
        source_sha256=bind.source_sha256 if bind else call.payload_sha256,
        transcript_revision=bind.transcript_revision
        if bind
        else f"synthetic:{call.payload_sha256}",
        report_revision=bind.report_revision if bind else call.payload_sha256,
        call_label=call.call_label,
        sandbox=True,
        rep_person_id=call.loaded_rep_id if call.loaded else rep_uuid(tenant_id, call.rep_key),
        rep_name=call.rep_name[:120],
    )
    parts = authored(call, payload, bind)
    if parts is None:
        return CallCoachingView(
            **common,
            state="unavailable",
            basis="unavailable",
            focus=None,
            evidence=(),
            lesson=None,
            practice=None,
            mission=None,
            limitations=(FICTIONAL, "This sandbox call has no complete authored coaching."),
        )
    return CallCoachingView(
        **common,
        state="ready",
        basis="skill_evidence",
        focus=parts.focus,
        evidence=parts.evidence,
        root_cause=parts.root_cause,
        lesson=parts.lesson,
        practice=parts.practice,
        mission=parts.mission,
        limitations=(FICTIONAL, IMPORTER_ONLY),
    )


def rep_view(
    calls: tuple[SandboxCall, ...],
    latest: dict[str, Any],
    earlier: dict[str, dict[str, Any]],
    *,
    person_id: UUID,
    tenant_id: UUID,
) -> CoachingView:
    """One fictional rep's coaching across calls: their newest authored state.

    `calls` are that rep's calls, newest first; `latest` is the newest call's
    payload and `earlier` the payloads of other calls whose moments it cites.
    """
    newest = calls[0]
    parts = authored(newest, latest)
    # A call's authored focus skill on another of this rep's calls too.
    skills = [call.skill_id for call in calls[:HISTORY_LIMIT]]
    summaries = tuple(
        CallSummary(
            submission_id=call.submission_id,
            call_label=call.call_label,
            created_at=call.occurred_at,
            state="ready",
            focus_label=call.focus_label,
            recurring=skills.count(call.skill_id) >= 2 if call.skill_id else None,
        )
        for call in calls[:HISTORY_LIMIT]
    )
    common: dict[str, Any] = dict(
        person_id=person_id,
        tenant_id=tenant_id,
        analysed_calls=len(calls),
        history_limited=len(calls) > HISTORY_LIMIT,
        calls=summaries,
        sandbox=True,
        person_name=newest.rep_name,
    )
    if parts is None:
        return CoachingView(
            **common,
            state="not_enough_evidence",
            focus=None,
            pattern=Pattern(summary="The newest sandbox call has no complete authored coaching."),
            evidence=(),
            practice=None,
            mission=None,
            lesson=None,
            development_path=Path(current=None, explanation=FICTIONAL),
            reflection_question=None,
            limitations=(FICTIONAL, IMPORTER_ONLY),
        )
    coaching = parts.payload
    diagnosis, progress = _dict(coaching.get("diagnosis")), _dict(coaching.get("progress"))
    counts, direction = _dict(diagnosis.get("pattern_counts")), _dict(coaching.get("direction"))
    by_key = {call.key: call for call in calls}
    # 2–4 moments across the calls the pattern cites, newest first (spec 3.2).
    evidence = list(parts.evidence[:2])
    for key in reversed(counts.get("call_ids") or ()):
        call = by_key.get(key) if isinstance(key, str) else None
        if call is None or call is newest or len(evidence) >= MAX_MOMENTS:
            continue
        other = authored(call, earlier[key]) if key in earlier else None
        if other and other.focus.skill_id == parts.focus.skill_id:
            evidence.extend(other.evidence[:1])
    evidence.extend(parts.evidence[2 : 2 + MAX_MOMENTS - len(evidence)])
    mission = parts.mission
    relevant = _int(progress.get("relevant_opportunities"))
    correct = _int(progress.get("correct_execution_count"))
    if relevant is None or correct is None or correct > relevant:
        # Counts are shown only as a consistent pair.
        relevant = correct = None
    occurrences = _int(counts.get("occurrence_count"))
    opportunities = _int(counts.get("relevant_opportunities"))
    if occurrences is None or opportunities is None or occurrences > opportunities:
        occurrences = opportunities = None
    baseline_relevant = _int(progress.get("baseline_relevant_opportunities"))
    baseline_correct = _int(progress.get("baseline_correct_execution_count"))
    chronological = sorted(calls[:HISTORY_LIMIT], key=lambda call: call.occurred_at)
    return CoachingView(
        **common,
        state="ready",
        focus=parts.focus.model_copy(
            update={
                "selected_at": mission.active_since,
                "status": (
                    "active"
                    if _slug(_dict(coaching.get("current_focus")).get("status")) == "active"
                    else "provisional"
                ),
            }
        ),
        pattern=Pattern(
            relevant_call_count=opportunities or 0,
            attention_call_count=occurrences or 0,
            summary=parts.pattern,
            relevant_opportunities=opportunities,
            occurrence_count=occurrences,
        ),
        root_cause=parts.root_cause,
        evidence=tuple(evidence[:MAX_MOMENTS]),
        practice=parts.practice,
        mission=mission,
        mastery=Mastery(
            state=_mastery(progress.get("mastery_state")),
            trend=_trend(progress.get("trend")),
            relevant_count=relevant,
            correct_count=correct,
            baseline=(
                f"{baseline_correct} of {baseline_relevant} before the mission"
                if baseline_relevant and baseline_correct is not None
                else None
            ),
            confidence=parts.root_cause.confidence,
            # Read by the person who imported this fictional rep: "their".
            explanation=_plain(progress.get("reason")) or THEIR_MASTERY,
        ),
        lesson=parts.lesson,
        progress=tuple(
            ProgressPoint(
                submission_id=call.submission_id,
                created_at=call.occurred_at,
                state="suggested" if call.skill_id == parts.focus.skill_id else "not_covered",
                after_mission=call.occurred_at > mission.active_since,
            )
            for call in chronological
        ),
        development_path=Path(
            current=parts.focus.label,
            likely_next=_text(direction.get("likely_next"), 240),
            explanation=(
                "The next focus depends on later calls. The current mission stays active."
            ),
        ),
        reflection_question="What influenced the response in this moment?",
        limitations=(FICTIONAL, IMPORTER_ONLY),
    )


def team_view(
    calls: tuple[SandboxCall, ...], *, person_id: UUID, tenant_id: UUID
) -> TeamCoachingView:
    """Sandbox Team: fictional reps by name, each with their newest call's focus."""
    counts: dict[str, int] = {}
    newest: dict[str, SandboxCall] = {}
    per_rep: dict[str, int] = {}
    for call in calls:
        if call.skill_id:
            counts[call.skill_id] = counts.get(call.skill_id, 0) + 1
        newest.setdefault(call.rep_key, call)
        per_rep[call.rep_key] = per_rep.get(call.rep_key, 0) + 1
    # Most recently active first; the area filter groups them by "what".
    reps = sorted(newest.values(), key=lambda call: (-call.occurred_at.timestamp(), call.rep_name))
    return TeamCoachingView(
        person_id=person_id,
        tenant_id=tenant_id,
        scope="sandbox",
        named_rep_details=bool(reps),
        reps_basis="fictional" if reps else "none",
        sandbox=True,
        analysed_calls=len(calls),
        rep_count=len(newest),
        pending_calls=0,
        unavailable_calls=0,
        history_limited=False,
        latest_call_at=calls[0].occurred_at if calls else None,
        suggestions=tuple(
            TeamSuggestion(skill_id=skill, label=LABELS[skill], suggestion_calls=count)
            for skill, count in sorted(counts.items(), key=lambda pair: (-pair[1], pair[0]))
        ),
        reps=tuple(
            TeamRep(
                person_id=rep_uuid(tenant_id, call.rep_key),
                name=call.rep_name,
                skill_id=call.skill_id,
                focus_label=call.focus_label,
                calls=per_rep[call.rep_key],
                latest_call_at=call.occurred_at,
            )
            for call in reps
        ),
        limitations=(
            FICTIONAL,
            IMPORTER_ONLY,
            "The counts are each fictional call’s one written focus, not real mistakes.",
        ),
    )


# ---------- Reads ----------

Record = ConversationSyntheticRecord


class SandboxCoaching:
    """Reads one importer's authored sandbox calls. The index is cached in memory
    per importer and reused until the set of imported calls changes."""

    _cache: "OrderedDict[tuple[UUID, UUID], tuple[tuple[int, datetime | None], SandboxIndex]]" = (
        OrderedDict()
    )

    def __init__(self, database: AsyncSession, tenant_id: UUID) -> None:
        self.database, self.tenant_id = database, tenant_id

    async def flagged(self) -> bool:
        return (
            await self.database.scalar(
                select(ConversationSandboxOrganisation.tenant_id).where(
                    ConversationSandboxOrganisation.tenant_id == self.tenant_id
                )
            )
        ) is not None

    def _own(self, person_id: UUID) -> Any:
        return (
            (Record.tenant_id == self.tenant_id)
            & (Record.kind == "call")
            & (Record.revision == 1)
            & (Record.imported_by_person_id == person_id)
        )

    async def index(self, person_id: UUID) -> SandboxIndex:
        stamp_row = (
            await self.database.execute(
                select(func.count(), func.max(Record.imported_at)).where(self._own(person_id))
            )
        ).one()
        stamp = (int(stamp_row[0]), stamp_row[1])
        key = (self.tenant_id, person_id)
        cached = self._cache.get(key)
        if cached and cached[0] == stamp:
            self._cache.move_to_end(key)
            return cached[1]
        # Parse each payload once (json → jsonb per row; OFFSET stops the lateral
        # subquery being inlined, which would re-parse per part), then take three parts.
        parsed = (
            select(cast(Record.payload, JSONB).label("p"))
            .correlate(Record)
            .offset(0)
            .lateral("parsed")
        )
        document = parsed.c.p
        rows = (
            await self.database.execute(
                select(
                    Record.synthetic_key,
                    Record.occurred_at,
                    Record.payload_sha256,
                    document[("metadata",)],
                    document[("transcript", "participants")],
                    document[("coaching", "current_focus")],
                )
                .select_from(Record)
                .join(parsed, true())
                .where(self._own(person_id))
                .order_by(Record.occurred_at.desc(), Record.synthetic_key.desc())
            )
        ).all()
        calls = tuple(
            call
            for call in (
                index_call(
                    key=row[0],
                    occurred_at=row[1],
                    payload_sha256=row[2],
                    metadata=row[3],
                    participants=row[4],
                    focus=row[5],
                    tenant_id=self.tenant_id,
                )
                for row in rows
            )
            if call is not None
        )
        index = SandboxIndex(calls)
        self._cache[key] = (stamp, index)
        while len(self._cache) > 4:
            self._cache.popitem(last=False)
        return index

    async def payload(self, person_id: UUID, key: str) -> dict[str, Any] | None:
        row = await self.database.get(Record, (self.tenant_id, "call", key, 1))
        if row is None or row.imported_by_person_id != person_id:
            return None
        return row.payload if isinstance(row.payload, dict) else None

    async def payloads(self, person_id: UUID, keys: list[str]) -> dict[str, dict[str, Any]]:
        if not keys:
            return {}
        rows = await self.database.scalars(
            select(Record).where(self._own(person_id), Record.synthetic_key.in_(keys))
        )
        return {row.synthetic_key: row.payload for row in rows if isinstance(row.payload, dict)}

    async def read_call(
        self,
        person_id: UUID,
        submission_id: UUID,
        report: Callable[[UUID], Awaitable[ReportBind | None]] | None = None,
    ) -> CallCoachingView | None:
        """`report` reads the loader's real report for a call opened by its loader id."""
        index = await self.index(person_id)
        call = index.call(submission_id)
        payload = await self.payload(person_id, call.key) if call else None
        if call is None or payload is None:
            return None
        bind = await report(call.submission_id) if call.loaded and report else None
        return call_view(call, payload, person_id=person_id, tenant_id=self.tenant_id, bind=bind)

    async def read_rep(self, person_id: UUID, rep_person_id: UUID) -> CoachingView | None:
        calls = (await self.index(person_id)).rep_calls(self.tenant_id, rep_person_id)
        latest = await self.payload(person_id, calls[0].key) if calls else None
        if latest is None:
            return None
        cited = _dict(_dict(_dict(latest.get("coaching")).get("diagnosis")).get("pattern_counts"))
        keys = [
            key
            for key in (cited.get("call_ids") or ())[-6:]
            if isinstance(key, str) and key != calls[0].key
        ]
        earlier = await self.payloads(person_id, keys)
        return rep_view(calls, latest, earlier, person_id=rep_person_id, tenant_id=self.tenant_id)

    async def rep_count(self, person_id: UUID) -> int:
        return len({call.rep_key for call in (await self.index(person_id)).calls})

    async def read_team(self, person_id: UUID) -> TeamCoachingView:
        index = await self.index(person_id)
        return team_view(index.calls, person_id=person_id, tenant_id=self.tenant_id)
