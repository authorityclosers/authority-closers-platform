"""Bounded previews from selected, validated checkpoints; never provider streams."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ac_platform.conversation_intelligence.alignment import project_transcript_for_playback
from ac_platform.conversation_intelligence.application import ConversationConflict
from ac_platform.conversation_intelligence.inference import binding_for, verified_checkpoint
from ac_platform.conversation_intelligence.models import (
    ConversationCheckpoint,
    ConversationProcessingPlan,
    ConversationRecording,
)
from ac_platform.conversation_intelligence.reports import FactPacket
from ac_platform.conversation_intelligence.submission_progress import StageExecution

PREVIEW_SEGMENTS = 24
PREVIEW_MOMENTS = 12


async def read_partial_results(
    database: AsyncSession,
    recording: ConversationRecording,
    plan: ConversationProcessingPlan | None,
    executions: list[StageExecution],
) -> dict[str, Any]:
    """The caller already checked retained customer/organisation read ownership."""
    result: dict[str, Any] = {
        "schema": "ac.sales-xray.partial-results/1",
        "state": "waiting",
        "provisional": True,
        "transcript": None,
        "key_moments": [],
        "completed_fact_chunks": 0,
        "total_fact_chunks": None,
    }
    if (
        plan is None
        or plan.state == "quoted"
        or not isinstance(plan.progress, dict)
        or (plan.tenant_id, plan.person_id, plan.recording_id, plan.generation)
        != (recording.tenant_id, recording.person_id, recording.id, recording.generation)
    ):
        return result
    run_ids = plan.progress.get("stage_run_ids")
    if not isinstance(run_ids, list) or len(run_ids) > 128:
        return result
    selected = [
        item.task
        for item in executions
        if str(item.task.run_id) in run_ids
        and (
            item.task.tenant_id,
            item.task.person_id,
            item.task.recording_id,
            item.task.generation,
        )
        == (recording.tenant_id, recording.person_id, recording.id, recording.generation)
        and item.task.state == "completed"
        and item.task.erased_at is None
        and item.task.checkpoint_id is not None
    ]
    transcript_task = next((task for task in selected if task.stage == "C2"), None)
    if transcript_task is None:
        return result
    identifiers = {task.checkpoint_id for task in selected if task.stage in {"C2", "C4"}}
    checkpoints = {
        row.id: row
        for row in (
            await database.scalars(
                select(ConversationCheckpoint).where(
                    ConversationCheckpoint.id.in_(identifiers),
                    ConversationCheckpoint.recording_id == recording.id,
                    ConversationCheckpoint.tenant_id == recording.tenant_id,
                    ConversationCheckpoint.person_id == recording.person_id,
                    ConversationCheckpoint.erased_at.is_(None),
                )
            )
        ).all()
    }
    try:
        if transcript_task.checkpoint_id is None:
            raise ValueError
        checkpoint = checkpoints[transcript_task.checkpoint_id]
        if checkpoint.stage != "C2":
            raise ValueError
        verified_checkpoint(checkpoint, binding_for(recording))
        transcript = checkpoint.payload
        if (
            not isinstance(transcript, dict)
            or transcript.get("source_sha256") != recording.source_sha256
        ):
            raise ValueError
        duration = transcript.get("duration_ms")
        if type(duration) is not int or duration <= 0:
            raise ValueError
        transcript = project_transcript_for_playback(transcript, duration_ms=duration)
        result["transcript"] = {
            name: transcript[name] for name in ("revision", "timebase_id", "duration_ms")
        }
        result["transcript"].update(
            segments=transcript["segments"][:PREVIEW_SEGMENTS],
            total_segments=len(transcript["segments"]),
        )
        result["state"] = "partial"
        packets = []
        for task in selected:
            if task.stage != "C4":
                continue
            if task.checkpoint_id is None:
                raise ValueError
            request = None if not isinstance(task.intent, dict) else task.intent.get("request")
            if not isinstance(request, dict) or request.get("transcript_checkpoint_id") != str(
                checkpoint.id
            ):
                continue
            fact_row = checkpoints[task.checkpoint_id]
            if fact_row.stage != "C4":
                raise ValueError
            verified_checkpoint(fact_row, binding_for(recording))
            packet = FactPacket.model_validate(fact_row.payload)
            if (
                packet.source_sha256 != recording.source_sha256
                or packet.transcript_revision != transcript["revision"]
                or packet.timebase_id != transcript["timebase_id"]
            ):
                raise ValueError
            packets.append(packet)
        packets.sort(key=lambda packet: packet.chunk_index)
        result["completed_fact_chunks"] = len(packets)
        result["total_fact_chunks"] = packets[0].chunk_count if packets else None
        result["key_moments"] = [
            observation.model_dump(mode="json", by_alias=True)
            for packet in packets
            for observation in packet.observations
        ][:PREVIEW_MOMENTS]
    except (KeyError, TypeError, ValueError, ConversationConflict):
        # A partial read cannot crash progress or expose an unverified artifact.
        result.update(state="unavailable", transcript=None, key_moments=[], completed_fact_chunks=0)
    return result
