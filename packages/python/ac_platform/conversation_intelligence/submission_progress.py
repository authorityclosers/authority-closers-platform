"""Content-free stage timing from canonical execution and checkpoint records.

This projection never advances work or manufactures a start time from enqueue,
polling or a predecessor's completion. Older/local starts can be unknown.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ac_platform.conversation_intelligence.inference import binding_for
from ac_platform.conversation_intelligence.models import (
    ConversationCheckpoint,
    ConversationInferenceTask,
    ConversationProcessingPlan,
    ConversationRecording,
    ConversationRun,
)
from ac_platform.outbox.models import Job

STAGES = tuple(f"C{index}" for index in range(7))


@dataclass(frozen=True)
class StageExecution:
    task: ConversationInferenceTask
    job: Job
    run: ConversationRun


@dataclass(frozen=True)
class StageCheckpoint:
    id: UUID
    stage: str
    digest: str
    parents: tuple[tuple[str, str], ...]
    finished_at: datetime


async def read_stage_checkpoints(
    database: AsyncSession, recording: ConversationRecording
) -> list[StageCheckpoint]:
    # Read metadata only: no transcript, report, provider payload or audio.
    rows = (
        await database.execute(
            select(
                ConversationCheckpoint.id,
                ConversationCheckpoint.stage,
                ConversationCheckpoint.manifest_sha256,
                ConversationCheckpoint.manifest,
                ConversationCheckpoint.created_at,
            )
            .where(
                ConversationCheckpoint.recording_id == recording.id,
                ConversationCheckpoint.tenant_id == recording.tenant_id,
                ConversationCheckpoint.person_id == recording.person_id,
                ConversationCheckpoint.erased_at.is_(None),
            )
            .order_by(ConversationCheckpoint.created_at.desc(), ConversationCheckpoint.id.desc())
            .limit(256)
        )
    ).all()
    binding = asdict(binding_for(recording))
    result = []
    for identifier, stage, digest, manifest, finished in reversed(rows):
        if (
            not isinstance(manifest, dict)
            or manifest.get("binding") != binding
            or manifest.get("stage") != stage
            or manifest.get("manifest_sha256") != digest
        ):
            continue
        parents = manifest.get("parents")
        if not isinstance(parents, list) or any(
            not isinstance(parent, list)
            or len(parent) != 2
            or not all(isinstance(value, str) for value in parent)
            for parent in parents
        ):
            continue
        result.append(
            StageCheckpoint(identifier, stage, digest, tuple(tuple(p) for p in parents), finished)
        )
    return result


def _iso(value: datetime | None) -> str | None:
    return None if value is None else value.astimezone(UTC).isoformat()


def project_stage_progress(
    *,
    plan: ConversationProcessingPlan | None,
    local_run: ConversationRun | None,
    local_job: Job | None,
    executions: list[StageExecution],
    checkpoints: list[StageCheckpoint],
    has_report: bool,
    run_state: str,
    report_finished_at: datetime | None,
    local_retry: bool = False,
) -> dict[str, Any]:
    by_id = {checkpoint.id: checkpoint for checkpoint in checkpoints}
    selected = executions
    if local_retry or (plan is not None and plan.state == "quoted"):
        selected = []
    elif plan is not None and isinstance(plan.progress.get("stage_run_ids"), list):
        ids = {value for value in plan.progress["stage_run_ids"] if isinstance(value, str)}
        selected = [item for item in executions if str(item.task.run_id) in ids]
    # Plans written before this additive field retain their source-scoped rows.
    rows: dict[str, dict[str, Any]] = {
        stage: {"stage": stage, "state": "waiting", "started_at": None, "finished_at": None}
        for stage in STAGES
    }
    for stage in ("C0", "C1"):
        checkpoint = next((c for c in reversed(checkpoints) if c.stage == stage), None)
        if checkpoint is not None:
            rows[stage].update(state="completed", finished_at=_iso(checkpoint.finished_at))
    if local_job is not None and local_job.dispatch_started_at is not None:
        finish = next((c.finished_at for c in reversed(checkpoints) if c.stage == "C1"), None)
        if finish is None or local_job.dispatch_started_at <= finish:
            rows["C1"]["started_at"] = _iso(local_job.dispatch_started_at)
    if local_run is not None and rows["C1"]["state"] != "completed":
        local_stage = "C1" if rows["C0"]["state"] == "completed" else "C0"
        rows[local_stage]["state"] = local_run.state
        if local_run.state in {"failed", "cancelled"}:
            rows[local_stage]["finished_at"] = _iso(local_run.completed_at)

    for stage in ("C2", "C4", "C5"):
        items = [item for item in selected if item.task.stage == stage]
        if not items:
            continue
        states = [item.task.state for item in items]
        state = next((s for s in states if s in {"failed", "uncertain", "cancelled"}), None)
        state = state or (
            "running" if "running" in states else "queued" if "queued" in states else "completed"
        )
        starts = [item.job.dispatch_started_at for item in items if item.job.dispatch_started_at]
        finishes = [item.run.completed_at for item in items if item.run.completed_at]
        rows[stage].update(
            state=state,
            started_at=_iso(min(starts) if starts else None),
            finished_at=_iso(
                max(finishes) if finishes and state not in {"queued", "running"} else None
            ),
        )

    # Alignment and presentation must belong to the currently selected provider
    # checkpoint, so a retry cannot display its predecessor's downstream output.
    for stage, parent_stage in (("C3", "C2"), ("C6", "C5")):
        parents = {
            by_id[item.task.checkpoint_id].digest
            for item in selected
            if item.task.stage == parent_stage and item.task.checkpoint_id in by_id
        }
        checkpoint = next(
            (
                c
                for c in reversed(checkpoints)
                if c.stage == stage
                and any((parent_stage, digest) in c.parents for digest in parents)
            ),
            None,
        )
        if checkpoint is not None and (stage != "C6" or has_report):
            rows[stage].update(state="completed", finished_at=_iso(checkpoint.finished_at))
    if has_report:
        rows["C6"].update(state="completed", finished_at=_iso(report_finished_at))

    current = None if plan is None else plan.progress.get("current_stage")
    if current not in STAGES:
        current = next(
            (stage for stage in reversed(STAGES) if rows[stage]["state"] != "waiting"), None
        )
    return {
        "current_stage": "C6" if has_report else current,
        "plan_state": None if plan is None else plan.state,
        "terminal_state": run_state if run_state in {"done", "failed"} else None,
        "stage_progress": list(rows.values()),
    }
