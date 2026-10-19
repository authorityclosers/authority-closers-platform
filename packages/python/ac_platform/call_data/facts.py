"""Read side of the call data engine: a lead's facts, its questions, and prospect facts.

Synchronous queries (HTTP routes call them through ``run_sync`` inside the
request's transaction). Rules on every read:
- only current objects: none a later object supersedes, none retracted or erased;
- a person's decision wins: accepted shows as confirmed, edited shows the
  person's value, rejected is hidden;
- an object quoting a segment that is now marked sensitive is hidden whole.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import insert, select, text

from ac_platform.call_data import taxonomy
from ac_platform.call_data.models import CallDataRun, CallObject, CallObjectDecision
from ac_platform.call_data.values import CallValueError, display, similar, validate_value

LEAD_SCHEMA = "call-data-lead/1"
PROSPECT_SCHEMA = "prospect-facts/1"
PERSON_DECISIONS = ("accepted", "edited", "rejected")


class FactsError(ValueError):
    def __init__(self, status: int, code: str) -> None:
        self.status, self.code = status, code
        super().__init__(code)


def _norm(value: str | None) -> str:
    return " ".join((value or "").casefold().split())


def _marked(connection: Any, recording_ids: set[UUID]) -> dict[UUID, set[str]]:
    """Segments now marked sensitive, per call (newest action per segment wins)."""
    if not recording_ids:
        return {}
    rows = connection.execute(
        text(
            """
            SELECT DISTINCT ON (recording_id, segment_id) recording_id, segment_id, action
            FROM conversation_sensitive_segment_marks
            WHERE recording_id = ANY(:ids)
            ORDER BY recording_id, segment_id, created_at DESC
            """
        ),
        {"ids": list(recording_ids)},
    ).mappings()
    marked: dict[UUID, set[str]] = defaultdict(set)
    for row in rows:
        if row["action"] == "mark":
            marked[row["recording_id"]].add(str(row["segment_id"]))
    return marked


@dataclass(slots=True)
class Item:
    row: Any
    decision: Any | None  # newest decision row, if any
    call_at: datetime
    roles: dict[str, str]

    @property
    def status(self) -> str:
        return str(self.decision.decision) if self.decision is not None else "kept"

    @property
    def shown_value(self) -> dict[str, Any]:
        if self.decision is not None and self.decision.decision == "edited":
            return dict(self.decision.value or {})
        return dict(self.row.value or {})

    @property
    def shown_display(self) -> str:
        if self.decision is not None and self.decision.decision == "edited":
            return str(self.decision.display or "")
        return str(self.row.display or "")

    @property
    def basis(self) -> str:
        if self.status == "accepted":
            return "confirmed"
        if self.status == "edited":
            return "edited"
        return str(self.row.basis)


def _items(connection: Any, where: Any, *, analysis: bool = False) -> list[Item]:
    objects = connection.execute(
        select(CallObject.__table__).where(where, CallObject.erased_at.is_(None))
    ).all()
    if not objects:
        return []
    ids = [o.id for o in objects]
    successors = set(
        connection.execute(
            select(CallObject.supersedes_id).where(CallObject.supersedes_id.in_(ids))
        ).scalars()
    )
    decisions: dict[UUID, Any] = {}
    for decision in connection.execute(
        select(CallObjectDecision.__table__)
        .where(CallObjectDecision.object_id.in_(ids), CallObjectDecision.erased_at.is_(None))
        .order_by(CallObjectDecision.created_at)
    ).all():
        decisions[decision.object_id] = decision
    runs = {
        row.id: row
        for row in connection.execute(
            select(CallDataRun.id, CallDataRun.counts, CallDataRun.created_at).where(
                CallDataRun.id.in_({o.run_id for o in objects if o.run_id})
            )
        )
    }
    marked = _marked(connection, {o.recording_id for o in objects})
    items = []
    for obj in objects:
        kind_type = taxonomy.get(obj.type_key)
        if obj.id in successors or obj.retracted or kind_type is None:
            continue
        if kind_type.kind in ("segment", "audio") and not analysis:
            continue  # analysis data, not facts a seller reads on a lead
        hidden = marked.get(obj.recording_id, set())
        if hidden and any(e.get("segment_id") in hidden for e in obj.evidence or []):
            continue
        run = runs.get(obj.run_id)
        counts = run.counts if run is not None and isinstance(run.counts, dict) else {}
        raw_roles = counts.get("roles")
        roles = (
            {str(k): str(v) for k, v in raw_roles.items()} if isinstance(raw_roles, dict) else {}
        )
        items.append(Item(obj, decisions.get(obj.id), obj.created_at, roles))
    return items


def _fact(item: Item) -> dict[str, Any]:
    obj = item.row
    kind_type = taxonomy.TYPES[obj.type_key]
    return {
        "object_id": str(obj.id),
        "type": obj.type_key,
        "category": obj.category,
        "label": kind_type.label,
        "kind": kind_type.kind,
        "value": item.shown_value,
        "display": item.shown_display,
        "confidence": float(obj.confidence),
        "basis": item.basis,
        "status": item.status,
        "ai_read": kind_type.ai_read,
        "evidence": [
            {**e, "role": item.roles.get(str(e.get("speaker")), "unknown")}
            for e in obj.evidence or []
        ],
        "call": {
            "recording_id": str(obj.recording_id),
            "submission_id": str(obj.submission_id) if obj.submission_id else None,
            "at": obj.created_at.isoformat(),
        },
        "source": {
            "pipeline": obj.pipeline,
            "version": obj.pipeline_version,
            "taxonomy_version": obj.taxonomy_version,
        },
    }


def _merge(items: list[Item]) -> list[Item]:
    """One fact per type (one) or per distinct item (many, near-same wording merged);
    a person's word first, then the newest."""
    kept: list[Item] = []
    for item in sorted(items, key=lambda i: i.row.created_at):
        if item.status == "rejected":
            continue
        kind_type = taxonomy.TYPES[item.row.type_key]
        held = next(
            (
                k
                for k in kept
                if k.row.type_key == item.row.type_key
                and (not kind_type.many or similar(k.shown_display, item.shown_display))
            ),
            None,
        )
        person = item.status in ("accepted", "edited")
        if held is None:
            kept.append(item)
        elif person or held.status not in ("accepted", "edited"):
            kept[kept.index(held)] = item
    return sorted(kept, key=lambda i: (taxonomy.TYPES[i.row.type_key].priority, i.shown_display))


def _pipelines(connection: Any, where: Any) -> dict[str, Any]:
    rows = connection.execute(
        select(
            CallDataRun.id,
            CallDataRun.pipeline,
            CallDataRun.state,
            CallDataRun.supersedes_id,
            CallDataRun.created_at,
        )
        .where(where)
        .order_by(CallDataRun.created_at)
    ).all()
    done = {row.supersedes_id for row in rows if row.supersedes_id is not None}
    result: dict[str, Any] = {
        "fast": {"state": "none", "at": None},
        "deep": {"state": "not_started", "at": None},
    }
    for row in rows:
        state = row.state
        if state == "running" and row.id in done:
            continue
        result[row.pipeline] = {
            "state": "done" if state == "succeeded" else state,
            "at": row.created_at.isoformat(),
        }
    return result


def lead_facts(
    connection: Any, tenant_id: UUID, lead_id: UUID, lead_columns: dict[str, str | None]
) -> dict[str, Any]:
    where = (CallObject.tenant_id == tenant_id) & (CallObject.lead_id == lead_id)
    items = _items(connection, where)
    asked = sorted(
        (item for item in items if item.status == "asked"),
        key=lambda i: (-i.row.created_at.timestamp(), taxonomy.TYPES[i.row.type_key].priority),
    )
    questions = []
    for item in asked:
        decision = item.decision
        assert decision is not None  # 'asked' is a decision
        questions.append(
            {
                **_fact(item),
                "question": decision.question,
                "lead_field": decision.lead_field,
                "lead_value": lead_columns.get(decision.lead_field or ""),
            }
        )
    recordings = {item.row.recording_id for item in items}
    pipelines = _pipelines(
        connection,
        (CallDataRun.tenant_id == tenant_id) & CallDataRun.recording_id.in_(recordings)
        if recordings
        else (CallDataRun.id.is_(None)),
    )
    filled = [
        {
            "field": decision.lead_field,
            "value": item.shown_display,
            "object_id": str(item.row.id),
            "at": decision.created_at.isoformat(),
        }
        for item in items
        if (decision := item.decision) is not None
        and decision.decision == "auto_filled"
        and decision.lead_written
    ]
    return {
        "schema": LEAD_SCHEMA,
        "lead_id": str(lead_id),
        "taxonomy_version": taxonomy.TAXONOMY_VERSION,
        "pipelines": pipelines,
        "questions": questions,
        "facts": [_fact(item) for item in _merge(items)],
        "filled": filled,
        "categories": dict(taxonomy.CATEGORIES),
    }


def prospect_facts(connection: Any, where: Any, subject: dict[str, str]) -> dict[str, Any]:
    """The agreed read for Prospect's Information (prospect-facts/1)."""
    items = _items(connection, where)
    recordings = {item.row.recording_id for item in items}
    facts = []
    for item in _merge(items):
        fact = _fact(item)
        kind_type = taxonomy.TYPES[item.row.type_key]
        fact["prospect_field"] = kind_type.prospect_field
        facts.append(fact)
    return {
        "schema": PROSPECT_SCHEMA,
        "subject": subject,
        "taxonomy_version": taxonomy.TAXONOMY_VERSION,
        "pipelines": _pipelines(
            connection,
            CallDataRun.recording_id.in_(recordings) if recordings else CallDataRun.id.is_(None),
        ),
        "facts": facts,
    }


@dataclass(frozen=True, slots=True)
class Decided:
    object_id: UUID
    lead_id: UUID | None
    lead_field: str | None
    lead_value: str | None
    replayed: bool
    row: dict[str, Any] | None = None  # the decision to insert (None on a replay)


def plan_decision(
    connection: Any,
    *,
    tenant_id: UUID,
    object_id: UUID,
    person_id: UUID,
    decision: str,
    value: object,
    command_id: UUID,
    now: datetime,
) -> Decided:
    """Check a person's accept, edit or reject and say which lead write it implies."""
    if decision not in PERSON_DECISIONS:
        raise FactsError(422, "decision_unknown")
    seen = connection.execute(
        select(CallObjectDecision.__table__).where(CallObjectDecision.command_id == command_id)
    ).one_or_none()
    if seen is not None:
        if seen.object_id != object_id or seen.person_id != person_id:
            raise FactsError(409, "command_reused")
        return Decided(object_id, seen.lead_id, None, None, True)
    obj = connection.execute(
        select(CallObject.__table__)
        .where(
            CallObject.id == object_id,
            CallObject.tenant_id == tenant_id,
            CallObject.erased_at.is_(None),
        )
        .with_for_update()
    ).one_or_none()
    if obj is None:
        raise FactsError(404, "fact_missing")
    if connection.scalar(select(CallObject.id).where(CallObject.supersedes_id == obj.id)):
        raise FactsError(409, "fact_replaced")
    kind_type = taxonomy.TYPES.get(obj.type_key)
    if kind_type is None:
        raise FactsError(409, "fact_type_retired")
    previous = connection.execute(
        select(CallObjectDecision.__table__)
        .where(CallObjectDecision.object_id == obj.id)
        .order_by(CallObjectDecision.created_at.desc())
        .limit(1)
    ).one_or_none()
    if previous is not None and previous.actor == "person":
        raise FactsError(409, "already_answered")
    stored_value: dict[str, Any] | None = None
    shown: str | None = None
    if decision == "edited":
        try:
            stored_value = validate_value(kind_type, value)
        except CallValueError as error:
            raise FactsError(422, error.code) from None
        shown = display(kind_type, stored_value)
    lead_field = (
        kind_type.lead_field if obj.lead_id is not None and decision != "rejected" else None
    )
    row = {
        "id": uuid4(),
        "tenant_id": tenant_id,
        "object_id": obj.id,
        "recording_id": obj.recording_id,
        "lead_id": obj.lead_id,
        "decision": decision,
        "actor": "person",
        "person_id": person_id,
        "question": previous.question if previous is not None else None,
        "value": stored_value,
        "display": shown,
        "lead_field": lead_field,
        "command_id": command_id,
        "supersedes_id": previous.id if previous is not None else None,
        "created_at": now,
    }
    return Decided(
        obj.id, obj.lead_id, lead_field, (shown or obj.display) if lead_field else None, False, row
    )


def save_decision(connection: Any, decided: Decided, *, lead_written: bool) -> None:
    if decided.row is None:
        return
    connection.execute(insert(CallObjectDecision).values(**decided.row, lead_written=lead_written))


OBJECTS_SCHEMA = "call-data-objects/1"


def call_objects(connection: Any, recording_id: UUID) -> dict[str, Any]:
    """Admin: everything the engine currently holds for one call (operations admins only).

    Facts as the seller sees them (a person's answer wins), every segment label
    in time order, and the measured voice. Objects quoting a segment now marked
    sensitive are hidden, as everywhere else.
    """
    items = _items(connection, CallObject.recording_id == recording_id, analysis=True)
    segments = sorted(
        (i for i in items if i.row.type_key == "conversation.segment"),
        key=lambda i: (i.row.evidence or [{}])[0].get("start_ms", 0),
    )
    voice = next((i for i in items if i.row.type_key == "audio.features"), None)
    facts = [i for i in items if taxonomy.TYPES[i.row.type_key].kind not in ("segment", "audio")]
    return {
        "schema": OBJECTS_SCHEMA,
        "recording_id": str(recording_id),
        "taxonomy_version": taxonomy.TAXONOMY_VERSION,
        "categories": dict(taxonomy.CATEGORIES),
        "facts": [
            {**_fact(item), "superseded_a_fast_fact": item.row.supersedes_id is not None}
            for item in _merge(facts)
        ],
        "segments": [
            {
                "object_id": str(seg.row.id),
                "segment_id": (seg.row.evidence or [{}])[0].get("segment_id"),
                "start_ms": (seg.row.evidence or [{}])[0].get("start_ms"),
                "end_ms": (seg.row.evidence or [{}])[0].get("end_ms"),
                "speaker": seg.roles.get(
                    str((seg.row.evidence or [{}])[0].get("speaker")), "unknown"
                ),
                **seg.row.value,
            }
            for seg in segments
        ],
        "voice": (
            {"object_id": str(voice.row.id), **dict(voice.row.value)} if voice is not None else None
        ),
    }
