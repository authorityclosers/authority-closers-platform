"""Audited internal draft import and owner-only report reads.

This connects private, already-produced analysis to AC records. Importing evidence
does not execute a provider, attest model quality, or promote a scoring version.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select

from ac_platform.conversation_intelligence.application import (
    ConversationApplication,
    ConversationConflict,
    ConversationError,
    ConversationNotFound,
    utc,
)
from ac_platform.conversation_intelligence.async_io import join_thread
from ac_platform.conversation_intelligence.checkpoints import canonical, content_hash
from ac_platform.conversation_intelligence.models import (
    ConversationCheckpoint,
    ConversationPermission,
    ConversationRecording,
    ConversationReportDraft,
    ConversationRun,
)
from ac_platform.conversation_intelligence.provider_admin import ConversationProviderAdmin
from ac_platform.conversation_intelligence.providers import ProviderResult, scribe_transcript
from ac_platform.conversation_intelligence.reports import (
    ReportDraft,
    load_report_profile,
    parse_report_draft,
)
from ac_platform.conversation_intelligence.storage import (
    ObjectKey,
    ObjectKind,
    RecordingObjectStorage,
    StorageError,
)
from ac_platform.kernel.authz import ActorContext


class PrivateProofReference(BaseModel):
    """Operator-supplied references, not canonical provider/reviewer attestations.

    Only transcription_response_sha256 is checked against supplied bytes here.
    The other hashes identify private external receipts; this importer cannot
    establish their existence, consent, provider execution or human adjudication.
    Hosted activation must use the durable broker's own canonical receipts.
    """

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    schema_id: Literal["ac.sales-xray.private-proof-reference/1"]
    approval_receipt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    transcription_response_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    generation_receipt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_review_receipt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    new_provider_calls: Literal[0]


class PrivateDraftIntent(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    raw_transcription_json: str = Field(min_length=1, max_length=3_000_000, repr=False)
    report: dict[str, Any] = Field(repr=False)
    receipt: PrivateProofReference

    @field_validator("report")
    @classmethod
    def bounded_report(cls, value: dict[str, Any]) -> dict[str, Any]:
        pending: list[tuple[Any, int]] = [(value, 0)]
        count = 0
        while pending:
            child, depth = pending.pop()
            count += 1
            if depth > 12 or count > 20_000:
                raise ValueError("The report exceeds its structural limit.")
            if isinstance(child, dict):
                pending.extend((item, depth + 1) for item in child.values())
            elif isinstance(child, list):
                pending.extend((item, depth + 1) for item in child)
        try:
            encoded = canonical(value)
        except (TypeError, ValueError):
            raise ValueError("The report must contain valid JSON values.") from None
        if len(encoded) > 512 * 1024:
            raise ValueError("The report exceeds its byte limit.")
        return value


class ConversationReports:
    def __init__(self, application: ConversationApplication) -> None:
        self.application = application
        self.database = application.database

    @staticmethod
    def _validated(
        draft: ConversationReportDraft, recording: ConversationRecording
    ) -> tuple[ReportDraft, dict[str, Any]]:
        if (
            draft.recording_id != recording.id
            or draft.tenant_id != recording.tenant_id
            or draft.person_id != recording.person_id
            or draft.source_revision != recording.source_revision
            or draft.source_sha256 != recording.source_sha256
            or draft.erased_at is not None
            or draft.payload is None
            or draft.transcript is None
            or draft.evidence_receipt is None
            or content_hash(draft.payload) != draft.report_sha256
            or content_hash(draft.transcript) != draft.transcript_sha256
            or content_hash(draft.evidence_receipt) != draft.evidence_receipt_sha256
        ):
            raise ConversationConflict("The stored report evidence is unavailable.")
        try:
            receipt = PrivateProofReference.model_validate(draft.evidence_receipt)
            native = draft.transcript["native_json"]
            transcript = draft.transcript["normalized"]
            if (
                not isinstance(native, str)
                or not isinstance(transcript, dict)
                or hashlib.sha256(native.encode("utf-8")).hexdigest()
                != receipt.transcription_response_sha256
                or transcript.get("revision") != receipt.transcription_response_sha256
                or transcript.get("source_sha256") != recording.source_sha256
                or draft.profile_sha256 != content_hash(load_report_profile())
            ):
                raise ValueError("unbound draft")
            report = ReportDraft.model_validate(draft.payload)
            checked = parse_report_draft(
                draft.payload, transcript, source_label=report.source_label
            )
            if content_hash(checked.model_dump(mode="json")) != draft.report_sha256:
                raise ValueError("unbound report")
        except (ValueError, TypeError, KeyError):
            raise ConversationConflict("The stored report needs review.") from None
        return report, transcript

    async def history(self, actor: ActorContext) -> dict[str, Any]:
        now = await self.application.admit(actor)
        recordings = (
            await self.database.scalars(
                select(ConversationRecording)
                .join(
                    ConversationPermission,
                    ConversationPermission.id == ConversationRecording.permission_id,
                )
                .where(
                    ConversationRecording.tenant_id == actor.tenant_id,
                    ConversationRecording.person_id == actor.person_id,
                    ConversationRecording.state.in_(("awaiting_upload", "ready")),
                    ConversationPermission.tenant_id == actor.tenant_id,
                    ConversationPermission.person_id == actor.person_id,
                    ConversationPermission.source_sha256 == ConversationRecording.source_sha256,
                    ConversationPermission.provider == "local",
                    ConversationPermission.revoked_at.is_(None),
                    ConversationPermission.expires_at > now,
                    ConversationPermission.retention_until > now,
                )
                .order_by(ConversationRecording.created_at.desc(), ConversationRecording.id.desc())
                .limit(20)
            )
        ).all()
        result = []
        for recording in recordings:
            latest = await self.database.scalar(
                select(ConversationRun)
                .where(
                    ConversationRun.recording_id == recording.id,
                    ConversationRun.tenant_id == actor.tenant_id,
                    ConversationRun.person_id == actor.person_id,
                )
                .order_by(ConversationRun.created_at.desc(), ConversationRun.id.desc())
                .limit(1)
            )
            has_report = False
            run_view = None
            if latest is not None:
                current = await self.application._run_view(actor, latest.id)
                run_view = {
                    "id": str(latest.id),
                    "state": current["state"],
                    "recipe_revision": latest.recipe_revision,
                    "provider_calls": current["provider_calls"],
                }
                has_report = (
                    await self.database.scalar(
                        select(ConversationReportDraft.id)
                        .where(
                            ConversationReportDraft.run_id == latest.id,
                            ConversationReportDraft.tenant_id == actor.tenant_id,
                            ConversationReportDraft.person_id == actor.person_id,
                            ConversationReportDraft.erased_at.is_(None),
                        )
                        .limit(1)
                    )
                    is not None
                )
                run_view["has_report"] = has_report
            result.append(
                {
                    **self.application._view(recording),
                    "latest_run": run_view,
                    "has_report": has_report,
                }
            )
        return {"recordings": result}

    async def transcript(self, actor: ActorContext, recording_id: UUID) -> dict[str, Any]:
        await self.application.get(actor, recording_id)
        recording = await self.application._recording(actor, recording_id)
        draft = await self.database.scalar(
            select(ConversationReportDraft)
            .where(
                ConversationReportDraft.recording_id == recording_id,
                ConversationReportDraft.tenant_id == actor.tenant_id,
                ConversationReportDraft.person_id == actor.person_id,
                ConversationReportDraft.erased_at.is_(None),
            )
            .order_by(ConversationReportDraft.created_at.desc(), ConversationReportDraft.id.desc())
            .limit(1)
        )
        if draft is None:
            raise ConversationNotFound("A saved transcript is not available yet.")
        _, transcript = self._validated(draft, recording)
        return {
            name: transcript[name]
            for name in ("source_sha256", "revision", "timebase_id", "duration_ms", "segments")
        }

    async def _response(
        self, actor: ActorContext, run: dict[str, Any], draft: ConversationReportDraft
    ) -> dict[str, Any]:
        recording = await self.application._recording(actor, UUID(run["recording_id"]))
        if draft.run_id != UUID(run["id"]):
            raise ConversationConflict("The report belongs to another analysis.")
        report, _ = self._validated(draft, recording)
        return {
            **run,
            "report": report.model_dump(mode="json"),
            "message": "Your private AI draft is ready. Dipak has not reviewed it yet.",
        }

    async def get(self, actor: ActorContext, run_id: UUID) -> dict[str, Any]:
        run = await self.application.get_run(actor, run_id)
        draft = await self.database.scalar(
            select(ConversationReportDraft)
            .where(
                ConversationReportDraft.run_id == run_id,
                ConversationReportDraft.tenant_id == actor.tenant_id,
                ConversationReportDraft.person_id == actor.person_id,
                ConversationReportDraft.recording_id == UUID(run["recording_id"]),
                ConversationReportDraft.erased_at.is_(None),
            )
            .order_by(ConversationReportDraft.created_at.desc(), ConversationReportDraft.id.desc())
            .limit(1)
        )
        if draft is None:
            return {
                **run,
                "report": None,
                "message": "Audio analysis is ready; a sales report has not been added yet."
                if run["state"] == "completed"
                else "Your call is being processed."
                if run["state"] in {"queued", "running"}
                else "Analysis needs attention. Your recording remains private.",
            }
        return await self._response(actor, run, draft)

    async def import_internal_draft(
        self,
        actor: ActorContext,
        run_id: UUID,
        intent: PrivateDraftIntent,
        *,
        storage: RecordingObjectStorage,
        key: str,
    ) -> dict[str, Any]:
        await ConversationProviderAdmin(self.application).admit(actor)
        run = await self.application.get_run(actor, run_id)
        run_row = await self.database.get(ConversationRun, run_id)
        recording = await self.application._recording(actor, UUID(run["recording_id"]))
        if (
            run_row is None
            or run_row.state != "completed"
            or run_row.generation != recording.generation
            or recording.state != "ready"
        ):
            raise ConversationConflict(
                "Finish this recording's local analysis before importing a draft."
            )
        signal = await self.database.scalar(
            select(ConversationCheckpoint)
            .where(
                ConversationCheckpoint.recording_id == recording.id,
                ConversationCheckpoint.tenant_id == actor.tenant_id,
                ConversationCheckpoint.person_id == actor.person_id,
                ConversationCheckpoint.stage == "C1",
                ConversationCheckpoint.erased_at.is_(None),
            )
            .order_by(ConversationCheckpoint.created_at.desc())
            .limit(1)
        )
        if signal is None or signal.payload is None or signal.manifest is None:
            raise ConversationConflict("A verified local audio checkpoint is required.")
        duration = signal.payload.get("media_duration_ms")
        if (
            type(duration) is not int
            or duration <= 0
            or signal.payload.get("source_sha256") != recording.source_sha256
            or content_hash(signal.payload) != signal.payload_sha256
            or signal.manifest.get("binding")
            != {
                "tenant_id": str(recording.tenant_id),
                "recording_id": str(recording.id),
                "source_sha256": recording.source_sha256,
                "source_revision": str(recording.source_revision),
            }
        ):
            raise ConversationConflict("The audio checkpoint is inconsistent.")
        raw = intent.raw_transcription_json.encode("utf-8")
        digest = hashlib.sha256(raw).hexdigest()
        if digest != intent.receipt.transcription_response_sha256:
            raise ConversationError("The native transcription does not match its receipt.")
        try:
            native = json.loads(raw)
            if not isinstance(native, dict):
                raise ValueError("invalid native envelope")
            normalized = scribe_transcript(
                ProviderResult(
                    provider="elevenlabs",
                    model="scribe_v2",
                    request_id=None,
                    response_sha256=digest,
                    raw_json=raw,
                    data=native,
                    input_sha256=recording.source_sha256,
                ),
                duration_ms=duration,
                source_sha256=recording.source_sha256,
            )
            normalized["duration_ms"] = duration
            report = parse_report_draft(intent.report, normalized, source_label="Your sales call")
        except (ValueError, TypeError, KeyError):
            raise ConversationError(
                "The draft or its exact transcript evidence is invalid."
            ) from None
        payload = report.model_dump(mode="json")
        receipt = intent.receipt.model_dump(mode="json")
        transcript = {"native_json": intent.raw_transcription_json, "normalized": normalized}
        command = {
            "run_id": str(run_id),
            "report_sha256": content_hash(payload),
            "transcript_sha256": content_hash(transcript),
            "receipt_sha256": content_hash(receipt),
        }
        replay = await self.application._replay(actor, key, "import_private_draft", command)
        if replay is not None:
            if replay.result_id is None:
                raise ConversationConflict("The imported report receipt is unavailable.")
            previous = await self.database.get(ConversationReportDraft, replay.result_id)
            if previous is None:
                raise ConversationConflict("The imported report receipt is unavailable.")
            return await self._response(actor, run, previous)
        source_key = ObjectKey(
            recording.tenant_id, recording.id, recording.id, ObjectKind.SOURCE_AUDIO
        )
        try:
            size = await join_thread(
                lambda: sum(
                    len(block)
                    for block in storage.iter_bytes(
                        source_key, expected_sha256=recording.source_sha256
                    )
                )
            )
        except StorageError:
            raise ConversationConflict("The retained recording is unavailable.") from None
        if size != recording.source_bytes:
            raise ConversationConflict("The retained recording is inconsistent.")
        existing = await self.database.scalar(
            select(ConversationReportDraft).where(
                ConversationReportDraft.run_id == run_id,
                ConversationReportDraft.report_sha256 == command["report_sha256"],
            )
        )
        if existing is not None:
            if (
                existing.transcript_sha256 != command["transcript_sha256"]
                or existing.evidence_receipt_sha256 != command["receipt_sha256"]
                or existing.erased_at is not None
            ):
                raise ConversationConflict("This report version has conflicting evidence.")
            draft = existing
        else:
            draft = ConversationReportDraft(
                id=uuid4(),
                tenant_id=actor.tenant_id,
                person_id=actor.person_id,
                recording_id=recording.id,
                run_id=run_id,
                source_revision=recording.source_revision,
                source_sha256=recording.source_sha256,
                report_sha256=command["report_sha256"],
                transcript_sha256=command["transcript_sha256"],
                profile_sha256=content_hash(load_report_profile()),
                evidence_receipt_sha256=command["receipt_sha256"],
                payload=payload,
                transcript=transcript,
                evidence_receipt=receipt,
                created_at=utc(self.application.clock()),
            )
            self.database.add(draft)
            await self.database.flush()
        await self.application._receipt(
            actor,
            key,
            "import_private_draft",
            command,
            draft.id,
            utc(self.application.clock()),
            resource_type="conversation_report_draft",
        )
        return await self._response(actor, run, draft)
