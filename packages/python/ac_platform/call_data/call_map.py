"""Admin call map: every stage of one call, with status, timing, cost, provider and version.

received → audio check → transcription → fast pipeline → objects → better
transcript → deep pipeline → objects updated → Report → AI pointer review →
Prospect. Read-only and content-free: ids, times, states, model names, token
counts and list-price estimates only; never transcript text, quotes or values.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import text

from ac_platform.conversation_intelligence.admin_pricing import estimate_provider_usage

SCHEMA = "call-data-map/1"


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _ms(start: datetime | None, end: datetime | None) -> int | None:
    if start is None or end is None:
        return None
    return max(0, round((end - start).total_seconds() * 1000))


def stage(
    key: str,
    label: str,
    status: str,
    *,
    started: datetime | None = None,
    finished: datetime | None = None,
    cost_inr: Decimal | float | None = None,
    provider: str | None = None,
    model: str | None = None,
    version: str | None = None,
    detail: str | None = None,
    counts: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "key": key,
        "label": label,
        "status": status,  # done | running | failed | skipped | waiting | not_built
        "started_at": _iso(started),
        "finished_at": _iso(finished),
        "duration_ms": _ms(started, finished),
        "cost_inr": None if cost_inr is None else float(cost_inr),
        "provider": provider,
        "model": model,
        "version": version,
        "detail": detail,
        "counts": counts or {},
    }


def _receipt(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _task_cost(receipt: dict[str, Any], duration_ms: int | None) -> Decimal | None:
    estimate = estimate_provider_usage(
        receipt.get("provider"),
        receipt.get("model"),
        _receipt(receipt.get("usage")),
        duration_ms=duration_ms,
    )
    paise = estimate.get("paise")
    return None if paise is None else Decimal(paise) / 100


_TASKS = """
SELECT t.stage, t.state, t.created_at, j.status AS job_status, j.dispatch_started_at,
       j.receipt_recorded_at, j.provider_receipt, cp.created_at AS saved_at
FROM conversation_inference_tasks t
LEFT JOIN jobs j ON j.id = t.job_id
LEFT JOIN conversation_checkpoints cp ON cp.id = t.checkpoint_id
WHERE t.recording_id = :recording AND t.erased_at IS NULL
ORDER BY t.created_at
"""


def call_map(connection: Any, recording_id: UUID) -> dict[str, Any] | None:
    call = (
        connection.execute(
            text(
                """
            SELECT c.id, c.tenant_id, c.state, c.created_at, c.deleted_at, t.name AS workspace,
                   s.submission_id, s.capture_source, s.created_at AS submitted_at
            FROM conversation_recordings c
            JOIN tenants t ON t.id = c.tenant_id
            LEFT JOIN LATERAL (
              SELECT submission_id, capture_source, created_at
              FROM conversation_guest_submissions g
              WHERE g.recording_id = c.id ORDER BY g.created_at DESC LIMIT 1
            ) s ON true
            WHERE c.id = :recording
            """
            ),
            {"recording": recording_id},
        )
        .mappings()
        .first()
    )
    if call is None:
        return None
    checkpoints: dict[str, Any] = {}
    for row in connection.execute(
        text(
            "SELECT stage, created_at, payload ->> 'media_duration_ms' AS media_ms"
            " FROM conversation_checkpoints WHERE recording_id = :recording"
            " AND erased_at IS NULL ORDER BY created_at"
        ),
        {"recording": recording_id},
    ).mappings():
        checkpoints.setdefault(row["stage"], row)  # the first save of each stage
    media_ms = None
    c1 = checkpoints.get("C1")
    if c1 is not None and str(c1["media_ms"] or "").isdigit():
        media_ms = int(c1["media_ms"])
    tasks: dict[str, list[Any]] = {}
    for row in connection.execute(text(_TASKS), {"recording": recording_id}).mappings():
        tasks.setdefault(row["stage"], []).append(row)
    stages = [
        stage(
            "received",
            "Received",
            "done",
            started=call["submitted_at"] or call["created_at"],
            finished=call["created_at"],
            detail=f"From {call['capture_source'] or 'upload'} · {call['workspace']}",
        ),
        _checkpoint_stage("audio_check", "Audio check", checkpoints, ("C0", "C1"), call),
        _task_stage("transcription", "Transcription (batch)", tasks.get("C2"), media_ms),
    ]
    stages.extend(_engine_stages(connection, recording_id))
    stages.append(_report_stage(tasks, checkpoints, media_ms))
    stages.append(_pointer_stage(connection, recording_id))
    stages.append(_prospect_stage(connection, call["submission_id"]))
    total = sum(Decimal(str(s["cost_inr"])) for s in stages if s["cost_inr"] is not None)
    return {
        "schema": SCHEMA,
        "recording_id": str(recording_id),
        "submission_id": str(call["submission_id"]) if call["submission_id"] else None,
        "workspace": call["workspace"],
        "state": call["state"],
        "media_ms": media_ms,
        "stages": stages,
        "cost_inr": float(total),
    }


def _checkpoint_stage(
    key: str, label: str, checkpoints: dict[str, Any], names: tuple[str, ...], call: Any
) -> dict[str, Any]:
    rows = [checkpoints[name] for name in names if name in checkpoints]
    if len(rows) == len(names):
        return stage(
            key,
            label,
            "done",
            started=call["created_at"],
            finished=rows[-1]["created_at"],
            provider="local",
            model="audioatlas",
        )
    return stage(key, label, "waiting" if call["state"] == "ready" else "skipped")


def _task_stage(
    key: str, label: str, rows: list[Any] | None, media_ms: int | None
) -> dict[str, Any]:
    if not rows:
        return stage(key, label, "waiting")
    row = rows[-1]
    receipt = _receipt(row["provider_receipt"])
    state = row["state"]
    status = (
        "done"
        if state == "completed"
        else "failed"
        if state in ("failed", "uncertain", "cancelled")
        else "running"
    )
    return stage(
        key,
        label,
        status,
        started=row["created_at"],
        finished=row["saved_at"] or row["receipt_recorded_at"],
        cost_inr=_task_cost(receipt, media_ms) if status == "done" else None,
        provider=receipt.get("provider"),
        model=receipt.get("model"),
        detail=None if len(rows) == 1 else f"{len(rows)} attempts",
    )


def _run_stage(key: str, label: str, pipeline: str, runs: list[Any]) -> dict[str, Any]:
    """One pipeline's newest attempt: running, or its outcome with time, cost and model."""
    mine = [row for row in runs if row["pipeline"] == pipeline]
    finished = {row["supersedes_id"] for row in mine if row["supersedes_id"] is not None}
    starts = {row["id"]: row for row in mine if row["state"] == "running"}
    outcomes = [row for row in mine if row["state"] != "running"]
    open_runs = [row for row in mine if row["state"] == "running" and row["id"] not in finished]
    if open_runs and (not outcomes or open_runs[-1]["created_at"] > outcomes[-1]["created_at"]):
        start = open_runs[-1]
        return stage(
            key,
            label,
            "running",
            started=start["created_at"],
            provider=start["provider"],
            model=start["model_id"],
            version=start["pipeline_version"],
        )
    if not outcomes:
        return stage(key, label, "waiting")
    last = outcomes[-1]
    begun = starts.get(last["supersedes_id"])
    counts = last["counts"] if isinstance(last["counts"], dict) else {}
    return stage(
        key,
        label,
        {"succeeded": "done", "failed": "failed", "skipped": "skipped"}[last["state"]],
        started=begun["created_at"] if begun else last["created_at"],
        finished=last["created_at"],
        cost_inr=last["cost_inr"],
        provider=last["provider"],
        model=last["model_id"],
        version=f"{last['pipeline_version']} · {last['taxonomy_version']}",
        detail=last["reason_code"],
        counts={
            "attempts": len(starts),
            "tokens_in": last["input_tokens"],
            "tokens_out": last["output_tokens"],
            "segments_labelled": counts.get("segments_labelled"),
            "audio": counts.get("audio"),
        },
    )


def _engine_stages(connection: Any, recording_id: UUID) -> list[dict[str, Any]]:
    runs = (
        connection.execute(
            text(
                """
            SELECT id, pipeline, pipeline_version, taxonomy_version, state, reason_code,
                   provider, model_id, input_tokens, output_tokens, cost_inr, duration_ms,
                   counts, supersedes_id, created_at
            FROM call_data_runs WHERE recording_id = :recording ORDER BY created_at
            """
            ),
            {"recording": recording_id},
        )
        .mappings()
        .all()
    )
    objects = (
        connection.execute(
            text(
                """
            SELECT o.category, o.pipeline, o.retracted, o.supersedes_id IS NOT NULL AS replaces,
                   d.decision
            FROM call_objects o
            LEFT JOIN LATERAL (
              SELECT decision FROM call_object_decisions x
              WHERE x.object_id = o.id ORDER BY x.created_at DESC LIMIT 1
            ) d ON true
            WHERE o.recording_id = :recording AND o.erased_at IS NULL
            """
            ),
            {"recording": recording_id},
        )
        .mappings()
        .all()
    )

    def tally(pipeline: str) -> dict[str, Any]:
        mine = [o for o in objects if o["pipeline"] == pipeline and not o["retracted"]]
        decisions = Counter(o["decision"] or "kept" for o in mine)
        return {
            "objects": len(mine),
            "by_category": dict(Counter(o["category"] for o in mine)),
            "auto_filled": decisions.get("auto_filled", 0),
            "asked": decisions.get("asked", 0),
            "accepted": decisions.get("accepted", 0),
            "edited": decisions.get("edited", 0),
            "rejected": decisions.get("rejected", 0),
        }

    fast = _run_stage("fast", "Fast pipeline", "fast", runs)
    deep_run = _run_stage("deep", "Deep pipeline", "deep", runs)
    fast_counts = tally("fast")
    deep_counts = tally("deep")
    deep_objects = [o for o in objects if o["pipeline"] == "deep"]
    return [
        fast,
        stage(
            "objects",
            "Call objects",
            "done"
            if fast_counts["objects"]
            else ("waiting" if fast["status"] == "waiting" else "skipped"),
            counts=fast_counts,
        ),
        stage(
            "better_transcript",
            "Better transcript",
            "skipped",
            detail="The batch transcript is already the best one; the deep read reuses it.",
        ),
        deep_run,
        stage(
            "objects_updated",
            "Objects updated",
            "done"
            if deep_counts["objects"]
            else ("waiting" if deep_run["status"] in ("waiting", "running") else "skipped"),
            counts={
                **deep_counts,
                "superseded": sum(1 for o in deep_objects if o["replaces"] and not o["retracted"]),
                "retracted": sum(1 for o in deep_objects if o["retracted"]),
            },
        ),
    ]


def _report_stage(
    tasks: dict[str, list[Any]], checkpoints: dict[str, Any], media_ms: int | None
) -> dict[str, Any]:
    c4, c5 = tasks.get("C4") or [], tasks.get("C5") or []
    c6 = checkpoints.get("C6")
    if not c4 and not c5:
        return stage("report", "Report · Coaching", "waiting")
    cost = Decimal(0)
    model = provider = None
    for row in [*c4, *c5]:
        receipt = _receipt(row["provider_receipt"])
        estimate = _task_cost(receipt, media_ms) if row["state"] == "completed" else None
        cost += estimate or 0
        provider, model = receipt.get("provider") or provider, receipt.get("model") or model
    started = (c4 or c5)[0]["created_at"]
    failed = any(row["state"] in ("failed", "uncertain") for row in [*c4[-1:], *c5[-1:]])
    status = "done" if c6 is not None else "failed" if failed else "running"
    return stage(
        "report",
        "Report · Coaching",
        status,
        started=started,
        finished=c6["created_at"] if c6 is not None else None,
        cost_inr=cost if cost else None,
        provider=provider,
        model=model,
        counts={"fact_chunks": len(c4), "coaching_attempts": len(c5)},
    )


def _pointer_stage(connection: Any, recording_id: UUID) -> dict[str, Any]:
    row = (
        connection.execute(
            text(
                """
            SELECT model_id, version, payload ->> 'prompt_revision' AS prompt, input_tokens,
                   output_tokens, created_at
            FROM conversation_pointer_reviews
            WHERE recording_id = :recording AND erased_at IS NULL
            ORDER BY created_at DESC LIMIT 1
            """
            ),
            {"recording": recording_id},
        )
        .mappings()
        .first()
    )
    if row is None:
        return stage("pointer_review", "AI pointer review", "waiting")
    from ac_platform.call_data.settings import cost_inr

    return stage(
        "pointer_review",
        "AI pointer review",
        "done",
        finished=row["created_at"],
        cost_inr=cost_inr(row["model_id"], row["input_tokens"], row["output_tokens"]),
        provider="gemini",
        model=row["model_id"],
        version=row["prompt"] or row["version"],
    )


def _prospect_stage(connection: Any, submission_id: UUID | None) -> dict[str, Any]:
    if submission_id is None:
        return stage("prospect", "Prospect", "waiting")
    row = (
        connection.execute(
            text(
                """
            SELECT link_kind, created_at FROM conversation_prospect_memberships
            WHERE submission_id = :submission AND ended_at IS NULL
            ORDER BY created_at DESC LIMIT 1
            """
            ),
            {"submission": submission_id},
        )
        .mappings()
        .first()
    )
    if row is None:
        return stage("prospect", "Prospect", "waiting", detail="Not saved to a prospect yet")
    return stage(
        "prospect",
        "Prospect",
        "done",
        finished=row["created_at"],
        detail="Linked by a person" if row["link_kind"] == "person" else "Detected from the call",
    )
