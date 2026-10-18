"""Deep pipeline merge rules: what a whole-call read does to the facts already there.

Rules (owner, 19 Oct: "updates and supersedes; history is append-only"):
- A fact a person accepted, edited or rejected is never touched: the person's
  word wins, and the deep read of the same thing is not saved over it.
- Any other current fact of the same identity (fast or an older deep read) is
  superseded by the deep value; its pending question moves to the new value or
  ends, by the same fill-or-ask rule the fast pipeline uses.
- A machine fact the deep read did not find, with confidence under 0.7, is
  retracted (a retraction row supersedes it; it leaves every screen).
- Segment labels and measured audio supersede their own earlier versions only.
Pure planning here; ``save`` writes the plan in the caller's transaction.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import insert, select

from ac_platform.call_data import engine, policy, taxonomy
from ac_platform.call_data.extraction import Draft
from ac_platform.call_data.models import CallObject, CallObjectDecision

DEEP_VERSION = "deep/1"
RETRACT_BELOW = 0.7
PERSON = ("accepted", "edited", "rejected")


def identity(
    type_key: str, display: str | None, evidence: Sequence[Mapping[str, Any]]
) -> tuple[str, str]:
    """What makes two objects 'the same thing' across runs."""
    kind_type = taxonomy.get(type_key)
    if kind_type is not None and kind_type.kind == "segment":
        return (type_key, str(evidence[0].get("segment_id")) if evidence else "")
    if kind_type is None or not kind_type.many:
        return (type_key, "")
    return (type_key, " ".join((display or "").casefold().split()))


@dataclass(frozen=True, slots=True)
class Current:
    id: UUID
    type_key: str
    display: str
    value: dict[str, Any]
    evidence: list[dict[str, Any]]
    confidence: float
    basis: str
    mentions: int
    pipeline: str
    decision: str | None  # newest decision, if any


@dataclass(frozen=True, slots=True)
class Merge:
    drafts: list[Draft]  # to save
    supersedes: list[UUID | None]  # per draft
    plans: list[policy.Plan]  # per draft
    retract: list[Current]
    person_kept: int


def plan_merge(
    drafts: Sequence[Draft],
    current: Sequence[Current],
    *,
    lead: Mapping[str, str | None] | None,
    auto_filled: Mapping[str, str],
    rejected: frozenset[tuple[str, str]],
) -> Merge:
    by_identity = {identity(c.type_key, c.display, c.evidence): c for c in current}
    kept: list[Draft] = []
    links: list[UUID | None] = []
    person_kept = 0
    seen: set[tuple[str, str]] = set()
    for draft in drafts:
        key = identity(draft.type_key, draft.display, draft.evidence)
        seen.add(key)
        held = by_identity.get(key)
        if held is not None and held.decision in PERSON:
            person_kept += 1
            continue
        kept.append(draft)
        links.append(held.id if held is not None else None)
    plans = policy.plan(kept, lead=lead, auto_filled=auto_filled, rejected=rejected)
    retract = [
        c
        for c in current
        if identity(c.type_key, c.display, c.evidence) not in seen
        and c.decision not in PERSON
        and c.basis != "person"
        and c.confidence < RETRACT_BELOW
        and (kind := taxonomy.get(c.type_key)) is not None
        and not kind.measured
        and kind.kind != "segment"
    ]
    return Merge(kept, links, plans, retract, person_kept)


def load_current(connection: Any, recording_id: UUID) -> list[Current]:
    rows = connection.execute(
        select(CallObject.__table__).where(
            CallObject.recording_id == recording_id, CallObject.erased_at.is_(None)
        )
    ).all()
    successors = {row.supersedes_id for row in rows if row.supersedes_id is not None}
    live = [row for row in rows if row.id not in successors and not row.retracted]
    newest: dict[UUID, str] = {}
    if live:
        for decision in connection.execute(
            select(CallObjectDecision.object_id, CallObjectDecision.decision)
            .where(CallObjectDecision.object_id.in_([row.id for row in live]))
            .order_by(CallObjectDecision.created_at)
        ):
            newest[decision.object_id] = decision.decision
    return [
        Current(
            id=row.id,
            type_key=row.type_key,
            display=row.display or "",
            value=dict(row.value or {}),
            evidence=list(row.evidence or []),
            confidence=float(row.confidence),
            basis=row.basis,
            mentions=row.mentions,
            pipeline=row.pipeline,
            decision=newest.get(row.id),
        )
        for row in live
    ]


def save(
    connection: Any,
    call: engine.Call,
    run_id: UUID,
    merge: Merge,
    *,
    lead: engine.LeadState | None,
    now: datetime,
) -> dict[str, int]:
    counts = {
        "objects": 0,
        "superseded": 0,
        "retracted": len(merge.retract),
        "person_kept": merge.person_kept,
        "auto_filled": 0,
        "asked": 0,
        "lead_written": 0,
    }
    for draft, link, plan in zip(merge.drafts, merge.supersedes, merge.plans, strict=True):
        object_id = uuid4()
        connection.execute(
            insert(CallObject).values(
                id=object_id,
                tenant_id=call.tenant_id,
                recording_id=call.recording_id,
                submission_id=call.submission_id,
                person_id=call.person_id,
                lead_id=call.lead_id,
                run_id=run_id,
                type_key=draft.type_key,
                category=draft.category,
                taxonomy_version=taxonomy.TAXONOMY_VERSION,
                value=draft.value,
                display=draft.display,
                evidence=draft.evidence,
                confidence=Decimal(str(draft.confidence)),
                basis=draft.basis,
                mentions=draft.mentions,
                pipeline="deep",
                pipeline_version=DEEP_VERSION,
                transcript_revision=call.transcript_revision,
                retracted=False,
                supersedes_id=link,
                created_at=now,
            )
        )
        counts["objects"] += 1
        counts["superseded"] += int(link is not None)
        if plan.action == "keep":
            continue
        written = False
        if plan.action == "auto_fill" and plan.lead_field and lead is not None and plan.lead_value:
            written = engine.write_lead(
                connection,
                call.tenant_id,
                lead,
                plan.lead_field,
                plan.lead_value,
                submission_id=call.submission_id,
                actor_person_id=None,
                now=now,
            )
        connection.execute(
            insert(CallObjectDecision).values(
                id=uuid4(),
                tenant_id=call.tenant_id,
                object_id=object_id,
                recording_id=call.recording_id,
                lead_id=call.lead_id,
                decision="auto_filled" if plan.action == "auto_fill" else "asked",
                actor="engine",
                question=plan.question,
                lead_field=plan.lead_field,
                lead_written=written,
                created_at=now,
            )
        )
        counts["auto_filled" if plan.action == "auto_fill" else "asked"] += 1
        counts["lead_written"] += int(written)
    for old in merge.retract:
        kind_type = taxonomy.TYPES[old.type_key]
        connection.execute(
            insert(CallObject).values(
                id=uuid4(),
                tenant_id=call.tenant_id,
                recording_id=call.recording_id,
                submission_id=call.submission_id,
                person_id=call.person_id,
                lead_id=call.lead_id,
                run_id=run_id,
                type_key=old.type_key,
                category=kind_type.category,
                taxonomy_version=taxonomy.TAXONOMY_VERSION,
                value=old.value,
                display=old.display,
                evidence=old.evidence,
                confidence=Decimal("0"),
                basis=old.basis if old.basis != "person" else "inferred",
                mentions=old.mentions,
                pipeline="deep",
                pipeline_version=DEEP_VERSION,
                transcript_revision=call.transcript_revision,
                retracted=True,
                supersedes_id=old.id,
                created_at=now,
            )
        )
    return counts


def measured_draft(type_key: str, value: dict[str, Any], display_text: str) -> Draft:
    """A server-measured object (audio, talk ratio): certain, quoted by nothing."""
    kind_type = taxonomy.TYPES[type_key]
    return Draft(
        type_key=type_key,
        category=kind_type.category,
        value=value,
        display=display_text,
        confidence=1.0,
        basis="observed",
        mentions=0,
        evidence=[],
    )
