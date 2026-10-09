"""Disclose attribution from exact retained C5 input, without changing reports."""

import json
import logging
from typing import Any
from uuid import UUID

from sqlalchemy import select

from ac_platform.conversation_intelligence.acquisition_reports import AcquisitionReports
from ac_platform.conversation_intelligence.alignment import project_transcript_for_playback
from ac_platform.conversation_intelligence.application import (
    ConversationError,
    ConversationNotFound,
)
from ac_platform.conversation_intelligence.checkpoints import content_hash
from ac_platform.conversation_intelligence.inference import ConversationInference
from ac_platform.conversation_intelligence.inference_tasks import (
    _text_prompt_view,
    input_metadata_for_saved_intent,
)
from ac_platform.conversation_intelligence.models import (
    ConversationInferenceTask,
    ConversationRecording,
)
from ac_platform.conversation_intelligence.report_access import ReportAccess
from ac_platform.conversation_intelligence.reporting_pipeline import ReportingPipeline, StageRequest
from ac_platform.conversation_intelligence.reports import FactPacket
from ac_platform.conversation_intelligence.retained_c5_recovery import _rebuild_prepared_c5_input
from ac_platform.conversation_intelligence.speaker_map import project_speaker_roles
from ac_platform.conversation_intelligence.speaker_roles import validate_speaker_roles

_LOGGER = logging.getLogger(__name__)
_STATUS = {
    "unverified_provider_labels": "predicted",
    "text_predicted_roles": "predicted",
    "model_named_roles": "model_named",
    "user_confirmed_roles": "confirmed",
    "channel_mapped_roles": "channel",
}


def project_report_basis(snapshot: dict[str, Any], current: dict[str, Any]) -> dict[str, Any]:
    current_roles = project_speaker_roles(current)
    matches = snapshot["transcript_revision"] == current_roles["transcript_revision"] and {
        row["speaker_id"]: (row["role"], row["is_account_holder"]) for row in snapshot["speakers"]
    } == {
        row["speaker_id"]: (row["role"], row["is_account_holder"])
        for row in current_roles["speakers"]
    }
    origin = snapshot["origin"]
    if matches and current_roles["origin"] in {"user_confirmed_roles", "channel_mapped_roles"}:
        origin = current_roles["origin"]
    return {
        "status": _STATUS[origin],
        "map_revision": snapshot["map_revision"],
        "you_speaker_id": next(
            (row["speaker_id"] for row in snapshot["speakers"] if row["is_account_holder"]), None
        ),
        "matches_current": matches,
    }


async def read_report_basis(
    reports: AcquisitionReports,
    recording: ConversationRecording,
    submission_id: UUID,
    current: dict[str, Any],
) -> dict[str, Any] | None:
    try:
        # Select exactly the report served by the existing boundary, including
        # retained recovery. Ownership/retention was checked by the caller.
        envelope = await reports.render_report(
            recording, submission_id=submission_id, access=ReportAccess.ACCOUNT
        )
    except ConversationNotFound:
        return None
    task = await reports.database.scalar(
        select(ConversationInferenceTask).where(
            ConversationInferenceTask.run_id == UUID(envelope["run_id"]),
            ConversationInferenceTask.recording_id == recording.id,
            ConversationInferenceTask.tenant_id == recording.tenant_id,
            ConversationInferenceTask.person_id == recording.person_id,
            ConversationInferenceTask.generation == recording.generation,
            ConversationInferenceTask.stage == "C5",
            ConversationInferenceTask.erased_at.is_(None),
        )
    )
    try:
        if task is None or task.intent is None or content_hash(task.intent) != task.intent_sha256:
            raise ValueError
        request = StageRequest.model_validate(task.intent["request"])
        if request.speaker_roles is None:
            return None
        pipeline = ReportingPipeline(ConversationInference(reports.application))
        c2, _ = await pipeline.checkpoint(recording, request.transcript_checkpoint_id, "C2")
        packets = []
        for identifier in request.fact_checkpoint_ids:
            c4, checkpoint = await pipeline.checkpoint(recording, identifier, "C4")
            packets.append(FactPacket.model_validate(c4.payload))
        _, c3 = await pipeline.parent(recording, checkpoint, "C3")
        c1, _ = await pipeline.parent(recording, c3, "C1")
        if c2.payload is None or c1.payload is None or request.profile is None:
            raise ValueError
        transcript = project_transcript_for_playback(
            c2.payload, duration_ms=c1.payload["media_duration_ms"]
        )
        prepared = _rebuild_prepared_c5_input(
            transcript,
            tuple(packets),
            profile=request.profile,
            input_metadata=task.intent["input"],
            request=task.intent["request"],
        )
        if (
            prepared.input_sha256 != task.input_sha256
            or input_metadata_for_saved_intent(prepared, task.intent["input"])
            != task.intent["input"]
        ):
            raise ValueError
        if prepared.max_completion_tokens is None:
            raise ValueError
        body = _text_prompt_view(
            prepared.as_provider_body(),
            provider=prepared.provider,
            model=prepared.model,
            maximum=prepared.max_completion_tokens,
            task="coaching",
        )
        context = json.loads(body["messages"][1]["content"].split("\n", 1)[1])["source_context"]
        snapshot = validate_speaker_roles(context["speaker_roles"], transcript)
        if (
            context["speaker_identity"] != snapshot["origin"]
            or snapshot["transcript_revision"] != envelope["transcript_revision"]
        ):
            raise ValueError
        return project_report_basis(snapshot, current)
    except (KeyError, TypeError, ValueError, ConversationError):
        # Optional attribution cannot hold a report or leak its contents.
        _LOGGER.warning("speaker_report_basis_unavailable")
        return None
