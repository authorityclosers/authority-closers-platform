"""Company insight from the analysis itself (admin revamp Phase 4, owner 19 Oct:
"Company shows no real analysis: every skill reads 100% and there are 0 objections").

Two sources, both already stored, both read-only here:
- the call data engine's current objects: what buyers said (objections, questions,
  pains, goals), what was promised, how decisions and interest stood;
- the AI pointer review's per-skill scores: a real quality signal per skill (the
  reports' own skill states mark every skill "observed", which says nothing).

Figures are internal reads of AI output, never an official score.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import exists, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from ac_platform.conversation_intelligence.models import ConversationRecording
from ac_platform.conversation_intelligence.pointer_review_models import ConversationPointerReview

# What buyers said, by engine type; listed by how many calls said it.
SAID: dict[str, tuple[str, ...]] = {
    "objections": ("friction.objection",),
    "questions": ("friction.question",),
    "pains": ("need.primary_pain", "need.pain"),
    "goals": ("need.goal",),
}
COMMITMENTS = (
    "commitment.next_step",
    "commitment.follow_up",
    "commitment.seller_promise",
    "commitment.prospect_promise",
)
# Short readings whose spread matters more than their wording.
READINGS = {
    "decision": "decision.status",
    "interest": "signal.interest",
    "urgency": "signal.urgency",
    "outcome": "outcome.call_outcome",
}
TOP = 8


def _normal(text: str | None) -> str:
    return " ".join((text or "").split()).strip(" .").lower()


def _top(rows: list[tuple[UUID, str | None]], limit: int = TOP) -> list[dict[str, Any]]:
    """The most common wordings by how many calls said them (one call counts once)."""
    calls: dict[str, set[UUID]] = defaultdict(set)
    shown: dict[str, str] = {}
    for recording_id, display in rows:
        key = _normal(display)
        if not key:
            continue
        calls[key].add(recording_id)
        shown.setdefault(key, " ".join((display or "").split()))
    ranked = sorted(calls.items(), key=lambda item: (-len(item[1]), item[0]))
    return [{"text": shown[key], "calls": len(ids)} for key, ids in ranked[:limit]]


def skill_scores(payloads: list[Any]) -> list[dict[str, Any]]:
    """Each skill's average AI pointer score and how often it needed work, weakest first."""
    scores: dict[str, list[int]] = defaultdict(list)
    weak: Counter[str] = Counter()
    for payload in payloads:
        pointers = payload.get("pointers") if isinstance(payload, dict) else None
        for pointer in pointers if isinstance(pointers, list) else []:
            if not isinstance(pointer, dict):
                continue
            label, score = pointer.get("label"), pointer.get("score")
            if not isinstance(label, str) or isinstance(score, bool):
                continue
            if not isinstance(score, (int, float)):
                continue
            scores[label].append(int(score))
            if pointer.get("status") not in ("good", "strong"):
                weak[label] += 1
    return sorted(
        (
            {
                "label": label,
                "calls": len(values),
                "average": round(sum(values) / len(values)),
                "needs_work_share": round(weak[label] / len(values), 3),
            }
            for label, values in scores.items()
        ),
        key=lambda item: (item["average"], item["label"]),
    )


async def analysis_insights(
    database: AsyncSession, organisation: UUID, *, days: int, now: datetime | None = None
) -> dict[str, Any]:
    """One organisation's analysis over the window: what buyers said and skill scores."""
    from ac_platform.call_data.models import CallObject

    now = now or datetime.now(UTC)
    since = now - timedelta(days=days)
    recordings = (
        select(ConversationRecording.id)
        .where(
            ConversationRecording.tenant_id == organisation,
            ConversationRecording.deleted_at.is_(None),
            ConversationRecording.created_at >= since,
        )
        .scalar_subquery()
    )
    successor = aliased(CallObject)
    rows = (
        await database.execute(
            select(CallObject.recording_id, CallObject.type_key, CallObject.display).where(
                CallObject.recording_id.in_(recordings),
                CallObject.retracted.is_(False),
                CallObject.erased_at.is_(None),
                ~exists().where(successor.supersedes_id == CallObject.id),
            )
        )
    ).all()
    by_type: dict[str, list[tuple[UUID, str | None]]] = defaultdict(list)
    analysed: set[UUID] = set()
    for recording_id, type_key, display in rows:
        analysed.add(recording_id)
        by_type[type_key].append((recording_id, display))

    said = {
        name: _top([row for key in keys for row in by_type.get(key, [])])
        for name, keys in SAID.items()
    }
    commitments = {
        key.split(".", 1)[1]: len({recording for recording, _ in by_type.get(key, [])})
        for key in COMMITMENTS
    }
    readings = {
        name: [
            {"text": text, "calls": count}
            for text, count in Counter(
                " ".join((display or "").split()) for _, display in by_type.get(key, []) if display
            ).most_common(6)
        ]
        for name, key in READINGS.items()
    }

    reviews = (
        await database.execute(
            select(ConversationPointerReview.recording_id, ConversationPointerReview.payload)
            .where(
                ConversationPointerReview.recording_id.in_(recordings),
                ConversationPointerReview.erased_at.is_(None),
            )
            .order_by(ConversationPointerReview.created_at.desc())
        )
    ).all()
    newest: dict[UUID, Any] = {}
    for recording_id, payload in reviews:
        newest.setdefault(recording_id, payload)  # the newest review of each call
    skills = skill_scores(list(newest.values()))
    return {
        "schema": "ac.analysis-insights/1",
        "window": {"days": days, "since": since.isoformat()},
        "calls_analysed": len(analysed),
        "calls_scored": len(newest),
        "said": said,
        "commitments": commitments,
        "readings": readings,
        "skills": skills,
    }
