"""Admin call detail (call-data-detail/1): one read for the dense call screen.

Stages and a graph of edges (fast and deep branches), every engine attempt, every
object ever made (superseded and retracted included, with its decisions), and
the current facts, segment labels and voice. Operations admins only. No raw
model answers exist to return: the engine keeps validated objects, the prompt
digest and token counts.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any
from uuid import UUID

from sqlalchemy import select, text

from ac_platform.call_data import call_map, facts
from ac_platform.call_data.models import CallDataRun, CallObject, CallObjectDecision

SCHEMA = "call-data-detail/1"

# (from, to, branch): the shape of the journey; each edge takes its 'to' stage's status/cost.
# The main analysis follows the checkpoint lineage: C3 needs C1 and C2, then C4 → C5 → C6.
EDGES = (
    ("received", "audio_check", "main"),
    ("received", "transcription", "main"),
    ("audio_check", "alignment", "main"),
    ("transcription", "alignment", "main"),
    ("transcription", "fast", "fast"),
    ("fast", "objects", "fast"),
    ("transcription", "better_transcript", "deep"),
    ("better_transcript", "deep", "deep"),
    ("objects", "deep", "deep"),
    ("deep", "objects_updated", "deep"),
    ("alignment", "facts", "report"),
    ("facts", "coaching", "report"),
    ("coaching", "published", "report"),
    ("published", "pointer_review", "report"),
    ("published", "prospect", "report"),
    ("coaching", "review", "report"),
    ("objects_updated", "review", "deep"),
)


def _iso(value: Any) -> str | None:
    return value.isoformat() if value is not None else None


def _runs(connection: Any, recording_id: UUID) -> list[dict[str, Any]]:
    rows = connection.execute(
        select(CallDataRun.__table__)
        .where(CallDataRun.recording_id == recording_id)
        .order_by(CallDataRun.created_at)
    ).all()
    outcome = {row.supersedes_id: row for row in rows if row.supersedes_id is not None}
    attempts: dict[str, int] = defaultdict(int)
    result = []
    for row in rows:
        if row.supersedes_id is not None:
            continue  # an outcome row; it is shown with its start
        end = outcome.get(row.id) if row.state == "running" else row
        attempts[row.pipeline] += 1
        result.append(
            {
                "run_id": str(end.id if end is not None else row.id),
                "pipeline": row.pipeline,
                "version": row.pipeline_version,
                "taxonomy_version": row.taxonomy_version,
                "trigger": row.trigger,
                "state": end.state if end is not None else "uncertain",
                "reason": end.reason_code if end is not None else "no outcome recorded",
                "provider": (end or row).provider,
                "model": (end or row).model_id,
                "prompt_sha256": row.prompt_sha256,
                "tokens_in": end.input_tokens if end is not None else None,
                "tokens_out": end.output_tokens if end is not None else None,
                "cost_inr": float(end.cost_inr) if end is not None and end.cost_inr else None,
                "started_at": _iso(row.created_at),
                "finished_at": _iso(end.created_at) if end is not None else None,
                "duration_ms": end.duration_ms if end is not None else None,
                "attempt": attempts[row.pipeline],
            }
        )
    return sorted(result, key=lambda run: run["started_at"] or "", reverse=True)


def _objects(connection: Any, recording_id: UUID) -> list[dict[str, Any]]:
    rows = connection.execute(
        select(CallObject.__table__)
        .where(CallObject.recording_id == recording_id)
        .order_by(CallObject.created_at)
    ).all()
    successors = {row.supersedes_id for row in rows if row.supersedes_id is not None}
    decisions: dict[UUID, list[dict[str, Any]]] = defaultdict(list)
    if rows:
        for decision in connection.execute(
            select(CallObjectDecision.__table__)
            .where(CallObjectDecision.object_id.in_([row.id for row in rows]))
            .order_by(CallObjectDecision.created_at)
        ).all():
            decisions[decision.object_id].append(
                {
                    "decision": decision.decision,
                    "actor": decision.actor,
                    "at": _iso(decision.created_at),
                    "question": decision.question,
                    "lead_field": decision.lead_field,
                    "lead_written": decision.lead_written,
                }
            )
    return [
        {
            "object_id": str(row.id),
            "type": row.type_key,
            "category": row.category,
            "display": row.display,  # None once erased
            "confidence": float(row.confidence),
            "basis": row.basis,
            "pipeline": row.pipeline,
            "version": row.pipeline_version,
            "run_id": str(row.run_id) if row.run_id else None,
            "supersedes_id": str(row.supersedes_id) if row.supersedes_id else None,
            "current": row.id not in successors and not row.retracted and row.erased_at is None,
            "retracted": row.retracted,
            "erased": row.erased_at is not None,
            "created_at": _iso(row.created_at),
            "decisions": decisions.get(row.id, []),
        }
        for row in sorted(rows, key=lambda r: (r.type_key, r.created_at))
        if row.type_key != "conversation.segment"  # segments come in their own list
    ]


def detail(connection: Any, recording_id: UUID) -> dict[str, Any] | None:
    the_map = call_map.call_map(connection, recording_id)
    if the_map is None:
        return None
    stages = []
    for stage in the_map["stages"]:
        counts = stage.get("counts") or {}
        stages.append(
            {
                **stage,
                "attempts": counts.get("attempts"),
                "tokens_in": counts.get("tokens_in"),
                "tokens_out": counts.get("tokens_out"),
            }
        )
    by_key = {stage["key"]: stage for stage in stages}
    edges = [
        {
            "from": source,
            "to": target,
            "branch": branch,
            "status": by_key[target]["status"],
            "cost_inr": by_key[target]["cost_inr"],
            "duration_ms": by_key[target]["duration_ms"],
        }
        for source, target, branch in EDGES
        if source in by_key and target in by_key
    ]
    found = facts.call_objects(connection, recording_id)
    who = connection.execute(
        text(
            """
            SELECT c.tenant_id, u.person_id, p.display_name, p.email,
                   (SELECT pl.manifest ->> 'report_language' FROM conversation_processing_plans pl
                    WHERE pl.recording_id = c.id ORDER BY pl.created_at DESC LIMIT 1) AS language
            FROM conversation_recordings c
            LEFT JOIN LATERAL (
              SELECT s.usage_id FROM conversation_guest_submissions s
              WHERE s.recording_id = c.id ORDER BY s.created_at DESC LIMIT 1
            ) s ON true
            LEFT JOIN conversation_acquisition_usage u ON u.id = s.usage_id
            LEFT JOIN persons p ON p.id = u.person_id
            WHERE c.id = :recording
            """
        ),
        {"recording": recording_id},
    ).first()
    branches = {
        "main": ("received", "audio_check", "transcription", "alignment"),
        "fast": ("fast", "objects"),
        "deep": ("better_transcript", "deep", "objects_updated"),
        "report": ("facts", "coaching", "published", "pointer_review", "prospect", "review"),
    }

    def total(keys: tuple[str, ...]) -> dict[str, Any]:
        chosen = [by_key[k] for k in keys if k in by_key]
        return {
            "cost_inr": round(sum(s["cost_inr"] or 0 for s in chosen), 4),
            "tokens_in": sum(s["tokens_in"] or 0 for s in chosen),
            "tokens_out": sum(s["tokens_out"] or 0 for s in chosen),
        }

    totals = {name: total(keys) for name, keys in branches.items()}
    totals["call"] = total(tuple(by_key))
    known = who is not None and who.person_id is not None
    return {
        "schema": SCHEMA,
        "call": {
            **{
                key: the_map[key]
                for key in (
                    "recording_id",
                    "submission_id",
                    "workspace",
                    "state",
                    "media_ms",
                    "cost_inr",
                )
            },
            "tenant_id": str(who.tenant_id) if who is not None else None,
            "rep": {
                "person_id": str(who.person_id) if known else None,
                "label": (who.display_name or who.email or "Unknown") if known else "Guest",
                "email": who.email if known else None,
            },
            "language": who.language if who is not None else None,
        },
        "totals": totals,
        "stages": stages,
        "edges": edges,
        "runs": _runs(connection, recording_id),
        "objects": _objects(connection, recording_id),
        "facts": found["facts"],
        "segments": found["segments"],
        "voice": found["voice"],
        "categories": found["categories"],
        "taxonomy_version": found["taxonomy_version"],
    }
