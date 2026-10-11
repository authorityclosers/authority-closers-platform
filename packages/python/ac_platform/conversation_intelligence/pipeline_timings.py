"""Read-only stage timing counts for an operator's bound development database.

This is inert: no settings, provider, storage, worker or application composition.
Only timestamp/state columns are selected; call text and credentials never enter
the result. Dispatch-to-receipt includes receipt persistence, not just inference.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from datetime import UTC, datetime
from math import ceil
from typing import Any

from psycopg import AsyncConnection
from psycopg.pq import TransactionStatus
from psycopg.rows import DictRow

SCHEMA = "ac.sales-xray.pipeline-timing-summary/1"

# Limit the recent runs before aggregating. No JSON content column is selected.
# Metadata joins include tenant/person/source generation rather than a bare ID.
RUNS_SQL = """
SELECT CASE WHEN j.kind = 'conversation.inspect_local.v1' THEN 'C0_C1'
            ELSE t.stage END AS stage,
       r.state, j.attempt_count AS claims,
       r.created_at AS enqueue, j.dispatch_started_at AS dispatch,
       j.receipt_recorded_at AS receipt, r.completed_at AS completed,
       cp.created_at AS published,
       signal.published AS c1_published, signal.matches AS c1_matches
FROM conversation_runs r
JOIN conversation_recordings recording
  ON recording.id = r.recording_id AND recording.tenant_id = r.tenant_id
 AND recording.person_id = r.person_id AND recording.generation = r.generation
JOIN jobs j ON j.id = r.job_id AND j.tenant_id = r.tenant_id
LEFT JOIN conversation_inference_tasks t
  ON t.run_id = r.id AND t.job_id = j.id AND t.tenant_id = r.tenant_id
 AND t.person_id = r.person_id AND t.recording_id = r.recording_id
 AND t.generation = r.generation AND t.erased_at IS NULL
LEFT JOIN conversation_checkpoints cp
  ON cp.id = t.checkpoint_id AND cp.tenant_id = t.tenant_id
 AND cp.person_id = t.person_id AND cp.recording_id = t.recording_id
 AND cp.stage = t.stage AND cp.erased_at IS NULL
LEFT JOIN LATERAL (
  SELECT count(*) AS matches,
         CASE WHEN count(*) = 1 THEN min(c1.created_at) END AS published
  FROM conversation_checkpoints c1
  WHERE c1.recording_id = recording.id AND c1.tenant_id = recording.tenant_id
    AND c1.person_id = recording.person_id AND c1.stage = 'C1' AND c1.erased_at IS NULL
    AND c1.created_at <= r.created_at
    AND (c1.manifest->'parents')::jsonb = (t.intent->'checkpoint'->'parents')::jsonb
    AND c1.manifest->'binding'->>'source_sha256' = recording.source_sha256
    AND c1.manifest->'binding'->>'source_revision' = recording.source_revision::text
    AND c1.payload->>'source_sha256' = recording.source_sha256
    AND c1.payload->>'media_duration_ms' = t.intent->>'duration_ms'
) signal ON t.stage = 'C2'
WHERE r.created_at >= %(since)s AND r.created_at <= %(observed)s
  AND recording.state = 'ready'
  AND (j.kind = 'conversation.inspect_local.v1'
       OR (j.kind = 'conversation.infer_provider.v1' AND t.stage IN ('C2','C4','C5')))
ORDER BY r.created_at DESC, r.id DESC
LIMIT %(limit)s
"""

DELIVERIES_SQL = """
SELECT p.state, accepted.created_at AS accepted,
       uploaded.created_at AS uploaded, e.created_at AS delivered,
       COALESCE(draft.created_at, saved.created_at) AS report_saved,
       (draft.id IS NOT NULL) AS delivery_bound
FROM conversation_processing_plans p
JOIN conversation_recordings recording
  ON recording.id = p.recording_id AND recording.tenant_id = p.tenant_id
 AND recording.person_id = p.person_id AND recording.generation = p.generation
JOIN conversation_commands accepted
  ON accepted.id = p.acceptance_command_id AND accepted.tenant_id = p.tenant_id
 AND accepted.person_id = p.person_id AND accepted.result_id = p.id
 AND accepted.action = 'processing_plan_accepted'
LEFT JOIN conversation_report_minute_events e ON e.plan_id = p.id AND e.kind = 'delivered'
LEFT JOIN conversation_report_drafts draft
 ON draft.id = e.report_draft_id AND draft.tenant_id = p.tenant_id
 AND draft.person_id = p.person_id AND draft.recording_id = p.recording_id
 AND draft.source_sha256 = recording.source_sha256
 AND draft.source_revision = recording.source_revision AND draft.erased_at IS NULL
LEFT JOIN LATERAL (
  SELECT d.created_at FROM conversation_plan_stage_authorizations a
  JOIN conversation_inference_tasks t ON t.quote_id = a.quote_id AND t.stage = 'C5'
    AND t.tenant_id = a.tenant_id AND t.person_id = a.person_id
    AND t.recording_id = p.recording_id AND t.generation = p.generation
    AND t.state = 'completed' AND t.erased_at IS NULL
  JOIN conversation_report_drafts d ON d.run_id = t.run_id
    AND d.tenant_id = t.tenant_id AND d.person_id = t.person_id
    AND d.recording_id = t.recording_id AND d.source_sha256 = recording.source_sha256
    AND d.source_revision = recording.source_revision AND d.erased_at IS NULL
  WHERE a.plan_id = p.id AND a.tenant_id = p.tenant_id AND a.person_id = p.person_id
  ORDER BY d.created_at DESC, d.id DESC LIMIT 1
) saved ON true
LEFT JOIN LATERAL (
  SELECT c.created_at FROM conversation_commands c
  WHERE c.result_id = recording.id AND c.tenant_id = recording.tenant_id
    AND c.person_id = recording.person_id AND c.action = 'source_stored'
  ORDER BY c.created_at, c.id LIMIT 1
) uploaded ON true
WHERE accepted.created_at >= %(since)s AND accepted.created_at <= %(observed)s
  AND p.erased_at IS NULL AND recording.state = 'ready'
ORDER BY accepted.created_at DESC, p.id DESC
LIMIT %(limit)s
"""

CHECKPOINT_COUNTS_SQL = """
SELECT cp.stage, count(*) AS count
FROM conversation_checkpoints cp
JOIN conversation_recordings r
  ON r.id = cp.recording_id AND r.tenant_id = cp.tenant_id AND r.person_id = cp.person_id
WHERE cp.created_at >= %(since)s AND cp.created_at <= %(observed)s
  AND cp.erased_at IS NULL AND r.state = 'ready'
GROUP BY cp.stage
"""


def _time(value: Any) -> datetime | None:
    if value is None:
        return None
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("pipeline_timing_clock_invalid")
    return value.astimezone(UTC)


def distribution(
    rows: Iterable[Mapping[str, Any]], start: str, end: str
) -> dict[str, int | float | None]:
    """Nearest-rank percentiles; missing/reversed clocks are counted, not zeroed."""
    values: list[float] = []
    missing = reversed_clocks = 0
    for row in rows:
        left, right = _time(row.get(start)), _time(row.get(end))
        if left is None or right is None:
            missing += 1
        elif right < left:
            reversed_clocks += 1
        else:
            values.append((right - left).total_seconds())
    values.sort()
    return {
        "n": len(values),
        "missing": missing,
        "reversed": reversed_clocks,
        "p50_seconds": values[ceil(len(values) * 0.5) - 1] if values else None,
        "p95_seconds": values[ceil(len(values) * 0.95) - 1] if values else None,
        "max_seconds": values[-1] if values else None,
    }


def summarize(
    runs: Sequence[Mapping[str, Any]], deliveries: Sequence[Mapping[str, Any]], *, limit: int
) -> dict[str, Any]:
    if type(limit) is not int or not 1 <= limit <= 500:
        raise ValueError("pipeline_timing_limit_invalid")
    if any(row.get("stage") not in {"C0_C1", "C2", "C4", "C5"} for row in runs):
        raise ValueError("pipeline_timing_stage_invalid")
    if any(
        row.get("state") not in {"queued", "running", "completed", "cancelled", "failed"}
        or type(row.get("claims")) is not int
        or row["claims"] < 0
        for row in runs
    ) or any(
        row.get("state") not in {"active", "completed", "held", "cancelled"} for row in deliveries
    ):
        raise ValueError("pipeline_timing_state_invalid")
    selected_runs, selected_plans = runs[:limit], deliveries[:limit]
    stages = {}
    for stage in ("C0_C1", "C2", "C4", "C5"):
        rows = [row for row in selected_runs if row["stage"] == stage]
        # Failed/uncertain attempts have separate counts; their receipt clocks
        # remain useful, but never enter completed-result latency percentiles.
        completed = [row for row in rows if row["state"] == "completed"]
        stages[stage] = {
            "runs": len(rows),
            "states": dict(Counter(row["state"] for row in rows)),
            "reclaimed_jobs": sum(row["claims"] > 1 for row in rows),
            "enqueue_to_completed": distribution(completed, "enqueue", "completed"),
            "enqueue_to_dispatch": distribution(rows, "enqueue", "dispatch"),
            "dispatch_to_receipt": distribution(rows, "dispatch", "receipt"),
            "receipt_to_checkpoint": distribution(completed, "receipt", "published"),
        }
    c2_rows = [row for row in selected_runs if row["stage"] == "C2"]
    # An unbound or erased draft cannot supply a delivery observation.
    saved = [row for row in selected_plans if row["report_saved"] is not None]
    delivered = [row for row in saved if row.get("delivery_bound") is True]
    return {
        "run_sample": {"n": len(selected_runs), "truncated": len(runs) > limit},
        "plan_sample": {"n": len(selected_plans), "truncated": len(deliveries) > limit},
        "stages": stages,
        "c1_c2_handoff": {
            "ambiguous_c1_artifacts": sum((row.get("c1_matches") or 0) > 1 for row in c2_rows),
            "c1_publication_to_c2_enqueue": distribution(c2_rows, "c1_published", "enqueue"),
            "c1_publication_to_c2_dispatch": distribution(c2_rows, "c1_published", "dispatch"),
        },
        "plans": {
            "states": dict(Counter(row["state"] for row in selected_plans)),
            "bound_saved_reports": len(saved),
            "bound_delivery_reports": len(delivered),
            "acceptance_to_report_saved": distribution(saved, "accepted", "report_saved"),
            "acceptance_to_delivery": distribution(delivered, "accepted", "delivered"),
            "source_stored_to_delivery": distribution(delivered, "uploaded", "delivered"),
            "report_saved_to_delivery": distribution(delivered, "report_saved", "delivered"),
        },
        "limits": [
            "Each stage is a separate distribution; do not sum its percentiles.",
            "C0_C1 enqueue-to-completed includes local queueing and inspection.",
            "Dispatch-to-receipt includes persistence; provider completion is unobserved.",
            "A job claim count is not a provider send or retry count.",
            "C1-to-C2 includes acceptance delay/retained work; ambiguous C1 artifacts are omitted.",
            "Source-stored starts after upload transfer; browser visibility is unobserved.",
            "Retained work/replays are not a fresh full-pipeline 20-minute measurement.",
        ],
        "twenty_minute_under_60_seconds": "unverified",
    }


async def export_summary(
    connection: AsyncConnection[DictRow], *, since: datetime, limit: int = 200
) -> dict[str, Any]:
    """Use one PostgreSQL-enforced read-only snapshot on an operator connection.

    The operator binds this connection to development; this function neither
    loads a credential nor claims to attest which environment a URL names.
    Refuse an already-open transaction rather than inherit its permissions.
    """
    if connection.info.transaction_status != TransactionStatus.IDLE:
        raise ValueError("pipeline_timing_idle_connection_required")
    if _time(since) is None or type(limit) is not int or not 1 <= limit <= 500:
        raise ValueError("pipeline_timing_window_invalid")
    async with connection.transaction():
        await connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        await connection.execute("SET LOCAL statement_timeout = '15s'")
        await connection.execute("SET LOCAL lock_timeout = '2s'")
        cursor = await connection.execute(
            "SELECT transaction_timestamp() AS observed, "
            "current_setting('transaction_read_only') AS read_only"
        )
        snapshot = await cursor.fetchone()
        assert snapshot is not None
        if snapshot["read_only"] != "on" or since > snapshot["observed"]:
            raise ValueError("pipeline_timing_snapshot_invalid")
        params = {"since": since, "observed": snapshot["observed"], "limit": limit + 1}
        cursor = await connection.execute(RUNS_SQL, params)
        runs = await cursor.fetchall()
        cursor = await connection.execute(DELIVERIES_SQL, params)
        deliveries = await cursor.fetchall()
        cursor = await connection.execute(CHECKPOINT_COUNTS_SQL, params)
        counts = await cursor.fetchall()
        return {
            "schema": SCHEMA,
            "since": since.isoformat(),
            "snapshot_at": snapshot["observed"].isoformat(),
            "transaction_read_only": True,
            "checkpoint_counts": {row["stage"]: row["count"] for row in counts},
            **summarize(runs, deliveries, limit=limit),
        }
