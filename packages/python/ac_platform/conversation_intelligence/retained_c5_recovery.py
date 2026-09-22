"""Source-owned recovery for a retained, provider-returned C5 response.

This boundary reads the exact task intent, quote, receipt and provider-response
blob already retained for one failed execution.  It never dispatches a
provider, mutates the failed task/job/ledger, or creates a canonical C5/C6
checkpoint.  A successful result is an explicitly marked recovered report
version that remains a draft and requires any later human review through the
existing review path.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal, cast
from uuid import UUID, uuid4

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import func, select

from ac_platform.conversation_intelligence.alignment import project_transcript_for_playback
from ac_platform.conversation_intelligence.application import (
    ConversationApplication,
    ConversationConflict,
    ConversationDenied,
    ConversationError,
    ConversationNotFound,
    utc,
)
from ac_platform.conversation_intelligence.checkpoints import (
    canonical,
    content_hash,
)
from ac_platform.conversation_intelligence.inference import binding_for, verified_checkpoint
from ac_platform.conversation_intelligence.inference_tasks import (
    InferenceTaskError,
    PreparedTaskInput,
    prepare_coaching_input,
    validate_coaching_result,
)
from ac_platform.conversation_intelligence.models import (
    ConversationCheckpoint,
    ConversationInferenceTask,
    ConversationPermission,
    ConversationQuote,
    ConversationRecording,
    ConversationRun,
)
from ac_platform.conversation_intelligence.provider_admin import ConversationProviderAdmin
from ac_platform.conversation_intelligence.providers import ProviderResult
from ac_platform.conversation_intelligence.recovery_models import (
    ConversationRetainedC5Version,
)
from ac_platform.conversation_intelligence.reports import (
    COACHING_PROMPT_LEGACY,
    COACHING_PROMPT_REFINED,
    REPORT_VALIDATOR_REVISION,
    FactPacket,
    load_report_profile,
)
from ac_platform.conversation_intelligence.storage import (
    ObjectKey,
    ObjectKind,
    PrivateLocalRecordingStorage,
    StorageError,
)
from ac_platform.kernel.authz import ActorContext
from ac_platform.outbox.models import Job
from ac_platform.outbox.repository import canonical_receipt_digest

_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_PATH = re.compile(r"(?:^|/)(?:[^/~]|~[01])+(?:/(?:[^/~]|~[01])+)*\Z")
_REVIEW_ORIGIN = "Codex automated proposal"
_RECOVERY_SCHEMA = "ac.sales-xray.retained-c5-recovery-proof/1"
C5PromptRevision = Literal["coaching-v1", "coaching-v2"]


def _coaching_prompt_revision(request: dict[str, Any]) -> C5PromptRevision:
    """Read the versioned C5 wording from a saved request, defaulting legacy."""

    value = request.get("coaching_prompt_revision", COACHING_PROMPT_LEGACY)
    if value not in {COACHING_PROMPT_LEGACY, COACHING_PROMPT_REFINED}:
        raise ValueError("The stored C5 prompt revision is invalid.")
    return cast(C5PromptRevision, value)


class RetainedC5Correction(BaseModel):
    """One explicit text correction against the decoded retained response."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    path: str = Field(
        min_length=1,
        max_length=300,
        validation_alias=AliasChoices("path", "json_pointer"),
    )
    old_sha256: str = Field(
        pattern=r"^[0-9a-f]{64}$",
        validation_alias=AliasChoices("old_sha256", "old_value_sha256"),
    )
    # Text is the common case.  Integer timestamps and a bounded evidence
    # array are the only structured replacements accepted by this boundary.
    new_text: str | int | list[dict[str, Any]] = Field(
        validation_alias=AliasChoices("new_text", "new_value")
    )
    source_segment_ids: tuple[str, ...] = Field(
        min_length=1,
        max_length=16,
        validation_alias=AliasChoices("source_segment_ids", "source_ids"),
    )
    rationale: str = Field(min_length=1, max_length=2000)

    @field_validator("source_segment_ids", mode="before")
    @classmethod
    def accept_json_array(cls, value: Any) -> Any:
        # Strict mode intentionally remains enabled for each element, while
        # ordinary JSON arrays are converted to the immutable wire shape.
        return tuple(value) if isinstance(value, list) else value

    @field_validator("new_text")
    @classmethod
    def bounded_replacement(cls, value: Any) -> Any:
        if isinstance(value, str):
            if not 1 <= len(value) <= 6000:
                raise ValueError("correction text is outside its bound")
            return value
        if type(value) is int:
            if not 0 <= value <= 7_200_000:
                raise ValueError("correction timestamp is outside its bound")
            return value
        if isinstance(value, list):
            if not 1 <= len(value) <= 8:
                raise ValueError("correction evidence is outside its bound")
            for item in value:
                if not isinstance(item, dict) or set(item) != {
                    "segment_id",
                    "quote",
                    "start_ms",
                    "end_ms",
                }:
                    raise ValueError("correction evidence shape is invalid")
                if (
                    type(item["segment_id"]) is not str
                    or not 1 <= len(item["segment_id"]) <= 128
                    or type(item["quote"]) is not str
                    or not 1 <= len(item["quote"]) <= 2_000
                    or type(item["start_ms"]) is not int
                    or item["start_ms"] < 0
                    or type(item["end_ms"]) is not int
                    or item["end_ms"] <= item["start_ms"]
                ):
                    raise ValueError("correction evidence values are invalid")
            return value
        raise ValueError("correction replacement type is invalid")

    @property
    def source_ids(self) -> tuple[str, ...]:
        return self.source_segment_ids

    @model_validator(mode="after")
    def bounded_path(self) -> RetainedC5Correction:
        if not _PATH.fullmatch(self.path) or not self.path.startswith("/"):
            raise ValueError("correction path must be an absolute JSON pointer")
        if len(set(self.source_segment_ids)) != len(self.source_segment_ids):
            raise ValueError("correction source ids must be unique")
        if any(
            not isinstance(value, str) or not 1 <= len(value) <= 128
            for value in self.source_segment_ids
        ):
            raise ValueError("correction source ids are invalid")
        return self


class RetainedC5CorrectionIntent(BaseModel):
    """Wire contract for an operator-reviewed correction proposal."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    original_raw_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    # Keep a generous ceiling for a reviewed source-owned batch without making
    # this a generic bulk-edit endpoint.
    corrections: tuple[RetainedC5Correction, ...] = Field(min_length=1, max_length=128)
    correction_payload_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("corrections", mode="before")
    @classmethod
    def accept_json_array(cls, value: Any) -> Any:
        return tuple(value) if isinstance(value, list) else value

    @property
    def payload(self) -> list[dict[str, Any]]:
        return [item.model_dump(mode="json") for item in self.corrections]

    @model_validator(mode="after")
    def digest_matches(self) -> RetainedC5CorrectionIntent:
        if content_hash(self.payload) != self.correction_payload_sha256:
            raise ValueError("correction payload hash does not match corrections")
        return self


class RetainedC5RevalidationIntent(BaseModel):
    """Small automatic-revalidation request used by Admin and the UI button."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    original_raw_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


@dataclass(frozen=True, slots=True)
class _BoundRecovery:
    recording: ConversationRecording
    run: ConversationRun
    task: ConversationInferenceTask
    job: Job
    quote: ConversationQuote
    permission: ConversationPermission
    c2: ConversationCheckpoint
    c3: ConversationCheckpoint
    c4: tuple[ConversationCheckpoint, ...]
    intent: dict[str, Any]
    receipt: dict[str, Any]
    raw: bytes
    prepared: PreparedTaskInput
    transcript: dict[str, Any]
    profile: dict[str, Any]


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _receipt_usage(value: object) -> dict[str, int]:
    if not isinstance(value, dict):
        return {}
    return {
        key: item
        for key, item in value.items()
        if isinstance(key, str) and type(item) is int and 0 <= item <= 1_000_000_000
    }


def _json_object(value: bytes) -> dict[str, Any]:
    if not 1 <= len(value) <= 4 * 1024 * 1024:
        raise ConversationConflict("The retained provider response is unavailable.")
    try:
        parsed = json.loads(value)
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise ConversationConflict("The retained provider response is invalid.") from None
    if not isinstance(parsed, dict):
        raise ConversationConflict("The retained provider response is invalid.")
    return parsed


def _pointer_tokens(path: str) -> list[str]:
    return [item.replace("~1", "/").replace("~0", "~") for item in path[1:].split("/")]


def _read_pointer(root: Any, tokens: list[str]) -> Any:
    current = root
    for token in tokens:
        if isinstance(current, list):
            if not token.isdigit() or int(token) >= len(current):
                raise ConversationConflict("The correction path is unavailable.")
            current = current[int(token)]
        elif isinstance(current, dict) and token in current:
            current = current[token]
        else:
            raise ConversationConflict("The correction path is unavailable.")
    return current


def _write_pointer(root: Any, tokens: list[str], value: Any) -> None:
    if not tokens:
        raise ConversationConflict("The correction path cannot replace the report root.")
    parent = _read_pointer(root, tokens[:-1])
    token = tokens[-1]
    if isinstance(parent, list):
        if not token.isdigit() or int(token) >= len(parent):
            raise ConversationConflict("The correction path is unavailable.")
        parent[int(token)] = value
    elif isinstance(parent, dict) and token in parent:
        parent[token] = value
    else:
        raise ConversationConflict("The correction path is unavailable.")


def _apply_corrections(
    model_object: dict[str, Any],
    corrections: tuple[RetainedC5Correction, ...],
    segment_ids: set[str],
) -> dict[str, Any]:
    result = copy.deepcopy(model_object)
    for correction in corrections:
        if not set(correction.source_ids).issubset(segment_ids):
            raise ConversationConflict("A correction source is outside the retained transcript.")
        tokens = _pointer_tokens(correction.path)
        current = _read_pointer(result, tokens)
        current_hash = (
            _sha(current.encode("utf-8")) if isinstance(current, str) else content_hash(current)
        )
        if current_hash != correction.old_sha256:
            raise ConversationConflict("A correction no longer matches the retained response.")
        replacement = correction.new_text
        if isinstance(current, str):
            if not isinstance(replacement, str):
                raise ConversationConflict("A text correction has an invalid type.")
        elif type(current) is int:
            if type(replacement) is not int or tokens[-1] not in {"start_ms", "end_ms"}:
                raise ConversationConflict("A timestamp correction has an invalid type.")
        elif isinstance(current, list):
            if tokens[-1] != "evidence" or not isinstance(replacement, list):
                raise ConversationConflict("An evidence correction has an invalid type.")
        else:
            raise ConversationConflict("The correction target has an invalid type.")
        _write_pointer(result, tokens, replacement)
    return result


def _model_envelope_with_report(
    data: dict[str, Any], *, provider: str, report: dict[str, Any]
) -> dict[str, Any]:
    """Put a corrected report back into the native envelope in memory only."""

    result = copy.deepcopy(data)
    if provider == "groq":
        try:
            content = result["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            raise ConversationConflict("The retained provider response is invalid.") from None
        if not isinstance(content, str):
            raise ConversationConflict("The retained provider response is invalid.")
        result["choices"][0]["message"]["content"] = canonical(report).decode("utf-8")
        return result
    if provider == "gemini":
        try:
            parts = result["candidates"][0]["content"]["parts"]
        except (KeyError, IndexError, TypeError):
            raise ConversationConflict("The retained provider response is invalid.") from None
        if not isinstance(parts, list) or not parts or not isinstance(parts[0], dict):
            raise ConversationConflict("The retained provider response is invalid.")
        parts[0]["text"] = canonical(report).decode("utf-8")
        return result
    raise ConversationConflict("The retained provider route is unavailable.")


def _report_from_model_envelope(data: dict[str, Any], *, provider: str) -> dict[str, Any]:
    """Decode the report object inside a retained native provider envelope."""

    if provider == "groq":
        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            raise ConversationConflict("The retained provider response is invalid.") from None
    elif provider == "gemini":
        try:
            content = data["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError, TypeError):
            raise ConversationConflict("The retained provider response is invalid.") from None
    else:
        raise ConversationConflict("The retained provider route is unavailable.")
    if not isinstance(content, str):
        raise ConversationConflict("The retained provider response is invalid.")
    return _json_object(content.encode("utf-8"))


class RetainedC5RecoveryService:
    """Admin command and owner/admin read boundary for retained C5 recovery."""

    def __init__(
        self,
        application: ConversationApplication,
        *,
        operations_tenant_id: UUID | None = None,
        recording_tenant_ids: tuple[UUID, ...] = (),
    ) -> None:
        self.application = application
        self.database = application.database
        self.operations_tenant_id = operations_tenant_id
        self.recording_tenant_ids = frozenset(recording_tenant_ids)

    async def _admin_admit(self, actor: ActorContext) -> None:
        if self.operations_tenant_id is not None and actor.tenant_id != self.operations_tenant_id:
            raise ConversationDenied("Use the AC operations workspace for retained recovery.")
        await ConversationProviderAdmin(self.application).admit(actor)

    async def _recording_for_owner(
        self, actor: ActorContext, run_id: UUID
    ) -> ConversationRecording:
        run = await self.database.scalar(
            select(ConversationRun).where(
                ConversationRun.id == run_id,
                ConversationRun.tenant_id == actor.tenant_id,
                ConversationRun.person_id == actor.person_id,
            )
        )
        if run is None:
            raise ConversationNotFound("Run not found.")
        await self.application.get(actor, run.recording_id)
        recording = await self.database.scalar(
            select(ConversationRecording).where(
                ConversationRecording.id == run.recording_id,
                ConversationRecording.tenant_id == actor.tenant_id,
                ConversationRecording.person_id == actor.person_id,
            )
        )
        if recording is None:
            raise ConversationNotFound("Recording not found.")
        return recording

    async def _load_bound(
        self,
        actor: ActorContext,
        run_id: UUID,
        *,
        storage: PrivateLocalRecordingStorage,
        admin: bool,
        original_raw_sha256: str,
        historical_input: bytes | None,
    ) -> _BoundRecovery:
        if not _SHA256.fullmatch(original_raw_sha256):
            raise ConversationError("The original response hash is invalid.")
        run_query = select(ConversationRun).where(ConversationRun.id == run_id)
        if admin:
            run_query = run_query.where(ConversationRun.tenant_id.in_(self.recording_tenant_ids))
        else:
            run_query = run_query.where(
                ConversationRun.tenant_id == actor.tenant_id,
                ConversationRun.person_id == actor.person_id,
            )
        run = await self.database.scalar(run_query.with_for_update())
        if run is None:
            raise ConversationNotFound("Run not found.")
        recording = await self.database.scalar(
            select(ConversationRecording)
            .where(
                ConversationRecording.id == run.recording_id,
                ConversationRecording.tenant_id == run.tenant_id,
                ConversationRecording.person_id == run.person_id,
            )
            .with_for_update(read=True)
        )
        if recording is None:
            raise ConversationNotFound("Recording not found.")
        # Use the database clock for the committed append-only version.  This
        # avoids reusing a transaction-scoped timestamp when a recovery command
        # has been waiting on a locked run.
        database_now = await self.database.scalar(select(func.clock_timestamp()))
        now = utc(database_now if database_now is not None else self.application.clock())
        permission = await self.database.scalar(
            select(ConversationPermission).where(
                ConversationPermission.id == recording.permission_id,
                ConversationPermission.tenant_id == recording.tenant_id,
                ConversationPermission.person_id == recording.person_id,
            )
        )
        if (
            recording.state != "ready"
            or permission is None
            or permission.revoked_at is not None
            or utc(permission.expires_at) <= now
            or utc(permission.retention_until) <= now
            or recording.generation != run.generation
        ):
            raise ConversationConflict("The retained recording binding is unavailable.")
        task = await self.database.scalar(
            select(ConversationInferenceTask)
            .where(
                ConversationInferenceTask.run_id == run.id,
                ConversationInferenceTask.recording_id == recording.id,
                ConversationInferenceTask.tenant_id == recording.tenant_id,
                ConversationInferenceTask.person_id == recording.person_id,
                ConversationInferenceTask.stage == "C5",
                ConversationInferenceTask.generation == recording.generation,
            )
            .with_for_update()
        )
        if (
            task is None
            or task.erased_at is not None
            or task.checkpoint_id is not None
            or task.state not in {"failed", "uncertain"}
        ):
            raise ConversationConflict("The retained C5 execution is unavailable for recovery.")
        job = await self.database.get(Job, task.job_id)
        quote = await self.database.get(ConversationQuote, task.quote_id)
        receipt = None if job is None else job.provider_receipt
        if (
            job is None
            or quote is None
            or quote.id != task.quote_id
            or quote.recording_id != recording.id
            or quote.tenant_id != recording.tenant_id
            or quote.person_id != recording.person_id
            or quote.revoked_at is not None
            or job.provider_receipt_digest is None
            or not isinstance(receipt, dict)
            or canonical_receipt_digest(receipt) != job.provider_receipt_digest
            or receipt.get("schema") != "ac.sales-xray.provider-receipt/1"
            or receipt.get("raw_blob_id") is None
            or receipt.get("response_sha256") != original_raw_sha256
            or receipt.get("input_sha256") != task.input_sha256
            or receipt.get("human_approved") is not False
            or job.status not in {"dead_letter", "succeeded", "retry_wait", "held"}
        ):
            raise ConversationConflict("The retained provider receipt is unavailable.")
        try:
            raw_blob_id = UUID(str(receipt["raw_blob_id"]))
        except (ValueError, TypeError, KeyError):
            raise ConversationConflict("The retained provider blob binding is invalid.") from None
        try:
            raw = b"".join(
                storage.iter_bytes(
                    ObjectKey(
                        recording.tenant_id,
                        recording.id,
                        raw_blob_id,
                        ObjectKind.PROVIDER_RESPONSE,
                    ),
                    expected_sha256=original_raw_sha256,
                )
            )
        except StorageError:
            raise ConversationConflict("The retained provider response is unavailable.") from None
        if _sha(raw) != original_raw_sha256:
            raise ConversationConflict("The retained provider response hash differs.")
        if not isinstance(task.intent, dict) or content_hash(task.intent) != task.intent_sha256:
            raise ConversationConflict("The stored C5 input proof is unavailable.")
        intent = task.intent
        request = intent.get("request")
        input_metadata = intent.get("input")
        if (
            intent.get("schema") != "ac.sales-xray.text-intent/1"
            or not isinstance(request, dict)
            or not isinstance(input_metadata, dict)
            or request.get("stage") != "C5"
            or request.get("transcript_checkpoint_id") is None
            or not isinstance(request.get("fact_checkpoint_ids"), list)
        ):
            raise ConversationConflict("The stored C5 input proof is unavailable.")
        c2_id = UUID(str(request["transcript_checkpoint_id"]))
        c2 = await self._checkpoint(recording, c2_id, "C2")
        transcript = c2.payload
        if not isinstance(transcript, dict):
            raise ConversationConflict("The retained transcript checkpoint is unavailable.")
        c4_ids = tuple(UUID(str(value)) for value in request["fact_checkpoint_ids"])
        if not c4_ids or len(c4_ids) != len(set(c4_ids)):
            raise ConversationConflict("The retained fact checkpoints are unavailable.")
        c4: list[ConversationCheckpoint] = []
        c3_manifest: str | None = None
        for identifier in c4_ids:
            row = await self._checkpoint(recording, identifier, "C4")
            if not isinstance(row.manifest, dict):
                raise ConversationConflict("The retained fact checkpoint is unavailable.")
            parents = row.manifest.get("parents")
            if not isinstance(parents, list | tuple):
                raise ConversationConflict("The retained fact lineage is unavailable.")
            parent_map = {
                str(item[0]): str(item[1])
                for item in parents
                if isinstance(item, list | tuple) and len(item) == 2
            }
            if parent_map.get("C2") != c2.manifest_sha256:
                raise ConversationConflict("The retained fact lineage differs.")
            current_c3 = parent_map.get("C3")
            if current_c3 is None or (c3_manifest is not None and current_c3 != c3_manifest):
                raise ConversationConflict("The retained alignment lineage differs.")
            c3_manifest = current_c3
            c4.append(row)
        assert c3_manifest is not None
        c3 = await self.database.scalar(
            select(ConversationCheckpoint).where(
                ConversationCheckpoint.recording_id == recording.id,
                ConversationCheckpoint.tenant_id == recording.tenant_id,
                ConversationCheckpoint.person_id == recording.person_id,
                ConversationCheckpoint.stage == "C3",
                ConversationCheckpoint.manifest_sha256 == c3_manifest,
                ConversationCheckpoint.erased_at.is_(None),
            )
        )
        if c3 is None:
            raise ConversationConflict("The retained alignment checkpoint is unavailable.")
        # A live C3 parent carries C1's measured duration. Historic retained
        # recovery records may omit that row, but they must remain on their
        # original in-bound transcript path; a native overflow requires the
        # verified C1 measurement and cannot fall back to C2 duration.
        c1_duration = None
        c3_manifest_payload = c3.manifest if isinstance(c3.manifest, dict) else {}
        c3_parents = c3_manifest_payload.get("parents")
        c1_manifest = dict(c3_parents).get("C1") if isinstance(c3_parents, list | tuple) else None
        if isinstance(c1_manifest, str):
            c1 = await self.database.scalar(
                select(ConversationCheckpoint).where(
                    ConversationCheckpoint.recording_id == recording.id,
                    ConversationCheckpoint.tenant_id == recording.tenant_id,
                    ConversationCheckpoint.person_id == recording.person_id,
                    ConversationCheckpoint.stage == "C1",
                    ConversationCheckpoint.manifest_sha256 == c1_manifest,
                    ConversationCheckpoint.erased_at.is_(None),
                )
            )
            if c1 is not None and isinstance(c1.payload, dict):
                verified_checkpoint(c1, binding_for(recording))
                c1_duration = c1.payload.get("media_duration_ms")
        declared_duration = transcript.get("duration_ms")
        if type(declared_duration) is not int:
            raise ConversationConflict("The retained transcript duration is unavailable.")
        has_native_overflow = any(
            isinstance(segment, dict)
            and type(segment.get("end_ms")) is int
            and segment["end_ms"] > declared_duration
            for segment in transcript.get("segments", [])
        )
        if c1_duration is None:
            if has_native_overflow:
                raise ConversationConflict(
                    "A verified C1 duration is required for native tail repair."
                )
        else:
            if type(c1_duration) is not int:
                raise ConversationConflict("The retained C1 duration is unavailable.")
            transcript = project_transcript_for_playback(transcript, duration_ms=c1_duration)
        try:
            verified_checkpoint(c2, binding_for(recording))
            verified_checkpoint(c3, binding_for(recording))
            for row in c4:
                verified_checkpoint(row, binding_for(recording))
            profile = request.get("profile")
            if not isinstance(profile, dict):
                profile = load_report_profile()
            if historical_input is None:
                # Admin HTTP can use this only when the current prompt builder
                # reproduces the exact stored input hash.  A prompt or profile
                # drift fails closed and requires the CLI's private historical
                # byte source instead of silently validating a new request.
                fact_packets = tuple(FactPacket.model_validate(row.payload) for row in c4)
                provider = input_metadata.get("provider")
                model = input_metadata.get("model")
                maximum = input_metadata.get("max_completion_tokens")
                output_profile = request.get("output_profile", "detailed")
                coaching_prompt_revision = _coaching_prompt_revision(request)
                if (
                    not isinstance(provider, str)
                    or not isinstance(model, str)
                    or type(maximum) is not int
                    or output_profile not in {"standard", "detailed"}
                ):
                    raise ValueError
                prepared = prepare_coaching_input(
                    transcript,
                    fact_packets,
                    provider=provider,
                    model=model,
                    max_completion_tokens=maximum,
                    profile=profile,
                    output_profile=output_profile,
                    coaching_prompt_revision=coaching_prompt_revision,
                )
            else:
                prepared = PreparedTaskInput.from_dict(input_metadata, payload=historical_input)
            if prepared.input_sha256 != task.input_sha256:
                raise ValueError
        except (InferenceTaskError, KeyError, TypeError, ValueError):
            raise ConversationConflict(
                "The stored C5 input cannot be reconstructed exactly."
            ) from None
        return _BoundRecovery(
            recording=recording,
            run=run,
            task=task,
            job=job,
            quote=quote,
            permission=permission,
            c2=c2,
            c3=c3,
            c4=tuple(c4),
            intent=intent,
            receipt=receipt,
            raw=raw,
            prepared=prepared,
            transcript=transcript,
            profile=profile,
        )

    async def _checkpoint(
        self, recording: ConversationRecording, identifier: UUID, stage: str
    ) -> ConversationCheckpoint:
        row = await self.database.scalar(
            select(ConversationCheckpoint).where(
                ConversationCheckpoint.id == identifier,
                ConversationCheckpoint.recording_id == recording.id,
                ConversationCheckpoint.tenant_id == recording.tenant_id,
                ConversationCheckpoint.person_id == recording.person_id,
                ConversationCheckpoint.stage == stage,
                ConversationCheckpoint.erased_at.is_(None),
            )
        )
        if row is None:
            raise ConversationConflict("A retained source checkpoint is unavailable.")
        return row

    @staticmethod
    def _provider_result(bound: _BoundRecovery, data: dict[str, Any]) -> ProviderResult:
        receipt = bound.receipt
        return ProviderResult(
            provider=receipt.get("provider", ""),
            model=receipt.get("model", ""),
            request_id=receipt.get("provider_request_id"),
            response_sha256=receipt["response_sha256"],
            raw_json=bound.raw,
            data=data,
            usage=_receipt_usage(receipt.get("usage")),
            input_sha256=bound.task.input_sha256,
        )

    @staticmethod
    def _proof(
        bound: _BoundRecovery,
        *,
        version_id: UUID,
        validation_state: str,
        failure_code: str | None,
        correction: RetainedC5CorrectionIntent | None,
        retention_until: datetime | None = None,
    ) -> dict[str, Any]:
        return {
            "schema_id": _RECOVERY_SCHEMA,
            "validator_revision": REPORT_VALIDATOR_REVISION,
            "recovery_version_id": str(version_id),
            "validation_mode": "retained_c5_response_revalidation",
            "provider_calls": 0,
            "validation_state": validation_state,
            "failure_code": failure_code,
            "review_origin": _REVIEW_ORIGIN,
            "human_approved": False,
            "dipak_adjudicated": False,
            "official_score": False,
            "binding": {
                "tenant_id": str(bound.recording.tenant_id),
                "person_id": str(bound.recording.person_id),
                "recording_id": str(bound.recording.id),
                "source_sha256": bound.recording.source_sha256,
                "source_revision": bound.recording.source_revision,
                "generation": bound.recording.generation,
                "permission_id": str(bound.permission.id),
                "retention_until": utc(
                    bound.permission.retention_until if retention_until is None else retention_until
                ).isoformat(),
                "c2_checkpoint_id": str(bound.c2.id),
                "c2_manifest_sha256": bound.c2.manifest_sha256,
                "c3_checkpoint_id": str(bound.c3.id),
                "c3_manifest_sha256": bound.c3.manifest_sha256,
                "c4_checkpoint_ids": [str(item.id) for item in bound.c4],
                "c4_manifest_sha256s": [item.manifest_sha256 for item in bound.c4],
            },
            "original_execution": {
                "task_id": str(bound.task.run_id),
                "job_id": str(bound.task.job_id),
                "quote_id": str(bound.task.quote_id),
                "task_state": bound.task.state,
                "job_status": bound.job.status,
                "attempt_count": bound.job.attempt_count,
                "provider_receipt_digest": bound.job.provider_receipt_digest,
                "c5_checkpoint_id": None,
                "original_raw_sha256": bound.receipt["response_sha256"],
                "raw_blob_id": bound.receipt["raw_blob_id"],
                "c5_input_sha256": bound.task.input_sha256,
            },
            "correction_payload_sha256": (
                None if correction is None else correction.correction_payload_sha256
            ),
        }

    @staticmethod
    def _view(
        version: ConversationRetainedC5Version,
        recording: ConversationRecording,
        *,
        message: str,
    ) -> dict[str, Any]:
        return {
            "id": str(version.id),
            "run_id": str(version.run_id),
            "recording_id": str(recording.id),
            "tenant_id": str(recording.tenant_id),
            "version": version.version,
            "source": {
                "sha256": recording.source_sha256,
                "revision": recording.source_revision,
                "retention_until": utc(version.retention_until).isoformat(),
            },
            "report": version.payload,
            "recovery": {
                "validation_state": version.validation_state,
                "failure_code": version.failure_code,
                "provider_calls": 0,
                "canonical_c5_checkpoint_id": None,
                "canonical_c6_checkpoint_id": None,
                "human_approved": False,
                "dipak_adjudicated": False,
                "official_score": False,
                "review_origin": version.review_origin,
                "original_raw_sha256": version.original_raw_sha256,
                "raw_blob_id": str(version.raw_blob_id),
            },
            "message": message,
        }

    async def revalidate(
        self,
        actor: ActorContext,
        run_id: UUID,
        *,
        original_raw_sha256: str,
        key: str,
        storage: PrivateLocalRecordingStorage,
        correction: RetainedC5CorrectionIntent | None = None,
        historical_input: bytes | None = None,
    ) -> dict[str, Any]:
        """Revalidate an existing response, optionally applying explicit text corrections."""

        await self._admin_admit(actor)
        if correction is not None and correction.original_raw_sha256 != original_raw_sha256:
            raise ConversationConflict("The correction is bound to another original response.")
        bound = await self._load_bound(
            actor,
            run_id,
            storage=storage,
            admin=True,
            original_raw_sha256=original_raw_sha256,
            historical_input=historical_input,
        )
        operation = (
            "conversation_retained_c5_correct"
            if correction
            else "conversation_retained_c5_revalidate"
        )
        command_intent = {
            "run_id": str(run_id),
            "original_raw_sha256": original_raw_sha256,
            "correction_payload_sha256": (
                None if correction is None else correction.correction_payload_sha256
            ),
        }
        replay = await self.application._replay(actor, key, operation, command_intent)
        if replay is not None:
            if replay.result_id is None:
                raise ConversationConflict("The retained recovery receipt is unavailable.")
            previous = await self.database.get(ConversationRetainedC5Version, replay.result_id)
            if previous is None:
                raise ConversationConflict("The retained recovery receipt is unavailable.")
            return self._view(
                previous,
                bound.recording,
                message="The retained recovery version was already created.",
            )
        # The request identity stays stable so an old command key replays its
        # original receipt, even after an upgrade. A fresh command revalidates
        # under the current admission contract instead of caching an earlier
        # validator's negative result forever. _load_bound holds the run lock,
        # serializing version allocation and same-revision deduplication.
        fingerprint = content_hash(
            {**command_intent, "validator_revision": REPORT_VALIDATOR_REVISION}
        )
        existing = await self.database.scalar(
            select(ConversationRetainedC5Version).where(
                ConversationRetainedC5Version.run_id == run_id,
                ConversationRetainedC5Version.fingerprint == fingerprint,
            )
        )
        if existing is not None:
            await self.application._receipt(
                actor,
                key,
                operation,
                command_intent,
                existing.id,
                utc(self.application.clock()),
                resource_type="conversation_retained_c5_version",
            )
            return self._view(
                existing,
                bound.recording,
                message="The retained recovery version was already created.",
            )
        data = _json_object(bound.raw)
        try:
            if correction is not None:
                model_object = _report_from_model_envelope(data, provider=bound.receipt["provider"])
                segment_ids = {
                    str(segment.get("id"))
                    for segment in bound.transcript.get("segments", [])
                    if isinstance(segment, dict) and isinstance(segment.get("id"), str)
                }
                model_object = _apply_corrections(model_object, correction.corrections, segment_ids)
            if correction is None:
                provider_result = self._provider_result(bound, data)
            else:
                # The corrected envelope exists only in memory.  Give the
                # strict validator a self-consistent byte/hash pair while the
                # proof and stored receipt continue to name the original
                # retained response hash above.
                corrected_data = _model_envelope_with_report(
                    data,
                    provider=bound.receipt["provider"],
                    report=model_object,
                )
                corrected_raw = canonical(corrected_data)
                provider_result = ProviderResult(
                    provider=bound.receipt.get("provider", ""),
                    model=bound.receipt.get("model", ""),
                    request_id=bound.receipt.get("provider_request_id"),
                    response_sha256=_sha(corrected_raw),
                    raw_json=corrected_raw,
                    data=corrected_data,
                    usage=_receipt_usage(bound.receipt.get("usage")),
                    input_sha256=bound.task.input_sha256,
                )
            normalized = validate_coaching_result(
                provider_result,
                bound.prepared,
                bound.transcript,
                profile=bound.profile,
            ).data()
            validation_state = "corrected" if correction is not None else "revalidated"
            failure_code = None
        except (ConversationConflict, InferenceTaskError, ValueError, KeyError, TypeError):
            if correction is not None:
                raise ConversationConflict(
                    "The correction does not produce a valid report."
                ) from None
            normalized = None
            validation_state = "needs_correction"
            failure_code = "retained_c5_strict_validation_failed"
        database_now = await self.database.scalar(select(func.clock_timestamp()))
        now = utc(database_now if database_now is not None else self.application.clock())
        final_permission = await self.database.scalar(
            select(ConversationPermission)
            .where(
                ConversationPermission.id == bound.permission.id,
                ConversationPermission.tenant_id == bound.recording.tenant_id,
                ConversationPermission.person_id == bound.recording.person_id,
            )
            .with_for_update(read=True)
            .execution_options(populate_existing=True)
        )
        if (
            final_permission is None
            or final_permission.revoked_at is not None
            or utc(final_permission.expires_at) <= now
            or utc(final_permission.retention_until) <= now
            or bound.recording.state != "ready"
            or bound.recording.generation != bound.run.generation
        ):
            raise ConversationConflict("The retained recording binding changed before finalize.")
        next_version = await self.database.scalar(
            select(func.coalesce(func.max(ConversationRetainedC5Version.version), 0) + 1).where(
                ConversationRetainedC5Version.run_id == run_id
            )
        )
        version_number = int(next_version or 1)
        version_id = uuid4()
        report_sha256 = "0" * 64 if normalized is None else content_hash(normalized)
        proof = self._proof(
            bound,
            version_id=version_id,
            validation_state=validation_state,
            failure_code=failure_code,
            correction=correction,
            retention_until=final_permission.retention_until,
        )
        row = ConversationRetainedC5Version(
            id=version_id,
            tenant_id=bound.recording.tenant_id,
            person_id=bound.recording.person_id,
            recording_id=bound.recording.id,
            run_id=bound.run.id,
            task_id=bound.task.run_id,
            job_id=bound.task.job_id,
            quote_id=bound.task.quote_id,
            permission_id=bound.permission.id,
            source_revision=bound.recording.source_revision,
            source_sha256=bound.recording.source_sha256,
            generation=bound.recording.generation,
            retention_until=final_permission.retention_until,
            c2_checkpoint_id=bound.c2.id,
            c2_manifest_sha256=bound.c2.manifest_sha256,
            c3_checkpoint_id=bound.c3.id,
            c3_manifest_sha256=bound.c3.manifest_sha256,
            c4_checkpoint_ids=[str(item.id) for item in bound.c4],
            c4_manifest_sha256s=[item.manifest_sha256 for item in bound.c4],
            c5_input_sha256=bound.task.input_sha256,
            c5_input=bound.intent.get("input"),
            original_quote=bound.quote.quote,
            original_attempt={
                "attempt_count": bound.job.attempt_count,
                "status": bound.job.status,
                "provider_idempotency_key": bound.job.provider_idempotency_key,
                "dispatch_started_at": None
                if bound.job.dispatch_started_at is None
                else utc(bound.job.dispatch_started_at).isoformat(),
                "delivery_ambiguous_at": None
                if bound.job.delivery_ambiguous_at is None
                else utc(bound.job.delivery_ambiguous_at).isoformat(),
            },
            original_receipt=bound.receipt,
            original_raw_sha256=original_raw_sha256,
            raw_blob_id=UUID(str(bound.receipt["raw_blob_id"])),
            version=version_number,
            fingerprint=fingerprint,
            validation_state=validation_state,
            failure_code=failure_code,
            correction=None if correction is None else correction.model_dump(mode="json"),
            correction_payload_sha256=(
                None if correction is None else correction.correction_payload_sha256
            ),
            review_origin=_REVIEW_ORIGIN,
            human_approved=False,
            dipak_adjudicated=False,
            official_score=False,
            proof=proof,
            payload=normalized,
            report_sha256=report_sha256,
            created_at=now,
        )
        self.database.add(row)
        await self.database.flush()
        await self.application._receipt(
            actor,
            key,
            operation,
            command_intent,
            row.id,
            now,
            resource_type="conversation_retained_c5_version",
        )
        if normalized is None:
            return self._view(
                row,
                bound.recording,
                message="The retained C5 response needs an explicit correction proposal.",
            )
        return self._view(
            row,
            bound.recording,
            message="The retained C5 response was revalidated from retained bytes.",
        )

    async def owner_report(self, actor: ActorContext, run_id: UUID) -> dict[str, Any] | None:
        recording = await self._recording_for_owner(actor, run_id)
        row = await self.database.scalar(
            select(ConversationRetainedC5Version)
            .where(
                ConversationRetainedC5Version.run_id == run_id,
                ConversationRetainedC5Version.recording_id == recording.id,
                ConversationRetainedC5Version.tenant_id == actor.tenant_id,
                ConversationRetainedC5Version.person_id == actor.person_id,
                ConversationRetainedC5Version.erased_at.is_(None),
                ConversationRetainedC5Version.payload.is_not(None),
            )
            .order_by(ConversationRetainedC5Version.version.desc())
            .limit(1)
        )
        if row is None:
            return None
        return self._view(
            row,
            recording,
            message="Your retained report was recovered from the original C5 response.",
        )

    async def admin_report(self, actor: ActorContext, run_id: UUID) -> dict[str, Any] | None:
        await self._admin_admit(actor)
        query = select(ConversationRetainedC5Version).where(
            ConversationRetainedC5Version.run_id == run_id,
            ConversationRetainedC5Version.tenant_id.in_(self.recording_tenant_ids),
            ConversationRetainedC5Version.erased_at.is_(None),
            ConversationRetainedC5Version.payload.is_not(None),
        )
        row = await self.database.scalar(
            query.order_by(ConversationRetainedC5Version.version.desc()).limit(1)
        )
        if row is None:
            return None
        recording = await self.database.scalar(
            select(ConversationRecording)
            .where(
                ConversationRecording.id == row.recording_id,
                ConversationRecording.tenant_id == row.tenant_id,
                ConversationRecording.person_id == row.person_id,
            )
            .with_for_update(read=True)
            .execution_options(populate_existing=True)
        )
        if recording is None:
            raise ConversationNotFound("Report not found.")
        # Erasure locks the recording before clearing retained recovery content.
        # Re-read the version after taking that lock so a report selected before
        # an erasure commit cannot be returned from the stale identity map.
        row = await self.database.scalar(
            select(ConversationRetainedC5Version)
            .where(
                ConversationRetainedC5Version.id == row.id,
                ConversationRetainedC5Version.run_id == run_id,
                ConversationRetainedC5Version.recording_id == recording.id,
                ConversationRetainedC5Version.tenant_id == recording.tenant_id,
                ConversationRetainedC5Version.person_id == recording.person_id,
                ConversationRetainedC5Version.erased_at.is_(None),
                ConversationRetainedC5Version.payload.is_not(None),
            )
            .with_for_update(read=True)
            .execution_options(populate_existing=True)
        )
        if row is None:
            return None
        database_now = await self.database.scalar(select(func.clock_timestamp()))
        now = utc(database_now if database_now is not None else self.application.clock())
        permission = await self.database.scalar(
            select(ConversationPermission)
            .where(
                ConversationPermission.id == row.permission_id,
                ConversationPermission.tenant_id == recording.tenant_id,
                ConversationPermission.person_id == recording.person_id,
            )
            .with_for_update(read=True)
            .execution_options(populate_existing=True)
        )
        if (
            recording.state != "ready"
            or permission is None
            or permission.revoked_at is not None
            or utc(permission.expires_at) <= now
            or utc(permission.retention_until) <= now
            or row.generation != recording.generation
        ):
            raise ConversationConflict("The recovered report's retained binding is unavailable.")
        return self._view(
            row,
            recording,
            message="Recovered report loaded for authorized Admin review.",
        )

    async def latest_for_recording(
        self, recording: ConversationRecording
    ) -> ConversationRetainedC5Version | None:
        return cast(
            ConversationRetainedC5Version | None,
            await self.database.scalar(
                select(ConversationRetainedC5Version)
                .where(
                    ConversationRetainedC5Version.recording_id == recording.id,
                    ConversationRetainedC5Version.tenant_id == recording.tenant_id,
                    ConversationRetainedC5Version.person_id == recording.person_id,
                    ConversationRetainedC5Version.erased_at.is_(None),
                    ConversationRetainedC5Version.payload.is_not(None),
                    ConversationRetainedC5Version.generation == recording.generation,
                )
                .order_by(
                    ConversationRetainedC5Version.created_at.desc(),
                    ConversationRetainedC5Version.id.desc(),
                )
                .limit(1)
            ),
        )


# Names used by callers and tests that describe the same boundary.
ConversationC5RecoveryService = RetainedC5RecoveryService
RetainedC5Recovery = RetainedC5RecoveryService


__all__ = [
    "ConversationC5RecoveryService",
    "RetainedC5Correction",
    "RetainedC5CorrectionIntent",
    "RetainedC5Recovery",
    "RetainedC5RevalidationIntent",
    "RetainedC5RecoveryService",
]
