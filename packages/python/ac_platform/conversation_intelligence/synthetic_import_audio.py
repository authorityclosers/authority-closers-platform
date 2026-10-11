"""Exact authored-call media attachments, outside real acquisition and provider work."""

from __future__ import annotations

import math
from collections.abc import Iterable
from typing import Any, Literal
from uuid import UUID, uuid5

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

from ac_platform.conversation_intelligence.application import ConversationConflict, utc
from ac_platform.conversation_intelligence.checkpoints import content_hash
from ac_platform.conversation_intelligence.limits import MAX_AUDIO_BYTES
from ac_platform.conversation_intelligence.storage import (
    ObjectKey,
    ObjectKind,
    PrivateLocalRecordingStorage,
    StorageError,
)
from ac_platform.conversation_intelligence.synthetic_import_contracts import (
    MAX_BUNDLE_BYTES,
    SyntheticCallBundle,
)
from ac_platform.conversation_intelligence.synthetic_import_models import (
    ConversationSyntheticRecord,
)
from ac_platform.conversation_intelligence.synthetic_imports import (
    SANDBOX_NAMESPACE,
    SyntheticImports,
)
from ac_platform.kernel.authz import ActorContext


def timing_number(value: JsonValue) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError("Media timing must contain finite numbers.")
    return float(value)


class SyntheticAudioManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    schema_version: Literal["synthetic-call-audio/1"] = Field(alias="schema")
    synthetic: Literal[True]
    call_id: str = Field(pattern=r"\Asyn-[A-Za-z0-9][A-Za-z0-9._:-]{0,150}\z")
    call_bundle_sha256: str = Field(pattern=r"\A[0-9a-f]{64}\z")
    audio_sha256: str = Field(pattern=r"\A[0-9a-f]{64}\z")
    audio_bytes: int = Field(ge=1, le=MAX_AUDIO_BYTES)
    content_type: Literal["audio/mpeg"]
    duration_ms: int = Field(ge=1, le=3_600_000)
    timing_file_sha256: str = Field(pattern=r"\A[0-9a-f]{64}\z")
    timing: dict[str, JsonValue]
    verification: dict[str, JsonValue]

    @model_validator(mode="before")
    @classmethod
    def marker(cls, value: Any) -> Any:
        if not isinstance(value, dict) or value.get("synthetic") is not True:
            raise ValueError("Media needs the explicit synthetic marker.")
        return value

    @model_validator(mode="after")
    def verified_provenance(self) -> SyntheticAudioManifest:
        expected = {
            "call_id": self.call_id,
            "status": "verified",
            "canonical_text_matches_audio": True,
            "media_decode_complete": True,
            "codec": "mp3",
            "duration_ms": self.duration_ms,
            "audio_sha256": self.audio_sha256,
            "timing_sha256": self.timing_file_sha256,
        }
        if any(self.verification.get(key) != value for key, value in expected.items()):
            raise ValueError("Import only the exact canonical verified MP3 receipt.")
        if (
            self.verification.get("canonical_text_matches_audio") is not True
            or self.verification.get("media_decode_complete") is not True
            or self.verification.get("timing_source") not in ("spool_exact", "silence_aligned")
            or self.timing.get("id") != self.verification.get("request_id")
            or not isinstance(self.verification.get("request_id"), str)
            or len(self.model_dump_json(by_alias=True).encode()) > MAX_BUNDLE_BYTES
        ):
            raise ValueError("Media needs bounded exact timing/provenance.")
        request_id = str(self.verification["request_id"])
        if request_id != self.call_id and not request_id.startswith(self.call_id + "-"):
            raise ValueError("Media needs an exact call-bound authored request identity.")
        return self

    def require_bundle(self, bundle: SyntheticCallBundle) -> None:
        if (
            self.call_bundle_sha256 != content_hash(bundle.model_dump(by_alias=True))
            or self.call_id != bundle.metadata["call_id"]
            or bundle.metadata.get("audio_file") != "audio.mp3"
            or bundle.metadata.get("duration_ms") != self.duration_ms
            or bundle.metadata.get("timing_source") != self.verification["timing_source"]
        ):
            raise ValueError("Media must match its exact authored call bundle.")
        segments, lines = self.timing.get("segments"), bundle.transcript["lines"]
        duration = timing_number(self.timing.get("duration"))
        if (
            abs(duration * 1000 - self.duration_ms) > 150
            or not isinstance(segments, list)
            or not isinstance(lines, list)
            or len(segments) != len(lines)
        ):
            raise ValueError("Timing must cover the exact authored transcript.")
        previous = 0.0
        for index, (segment, line) in enumerate(zip(segments, lines, strict=True)):
            if not isinstance(segment, dict) or not isinstance(line, dict):
                raise ValueError("Timing must contain exact authored segments.")
            start, end = timing_number(segment.get("start")), timing_number(segment.get("end"))
            if (
                not previous <= start < end <= duration
                or segment.get("n") != index
                or segment.get("text") != line.get("text")
                or segment.get("speaker") != line.get("speaker")
                or abs(start * 1000 - timing_number(line["start_ms"])) > 1
                or abs(end * 1000 - timing_number(line["end_ms"])) > 1
            ):
                raise ValueError("Timing/text/speakers must match every canonical line.")
            previous = end


def media_key(tenant_id: UUID, manifest: SyntheticAudioManifest) -> ObjectKey:
    return ObjectKey(
        tenant_id,
        uuid5(SANDBOX_NAMESPACE, f"synthetic-audio:{tenant_id}:{manifest.call_id}"),
        uuid5(SANDBOX_NAMESPACE, manifest.audio_sha256),
        ObjectKind.SOURCE_AUDIO,
    )


def retain_audio(
    storage: PrivateLocalRecordingStorage,
    key: ObjectKey,
    manifest: SyntheticAudioManifest,
    chunks: Iterable[bytes],
) -> None:
    try:
        storage.put(
            key,
            chunks,
            expected_sha256=manifest.audio_sha256,
            expected_bytes=manifest.audio_bytes,
        )
    except StorageError as error:
        if str(error) != "storage_object_exists":
            raise
        # A process can die after atomic file publication but before the DB commit.
        # Reuse only independently hash/size-verified bytes; never overwrite them.
        iterator = storage.iter_bytes(key, expected_sha256=manifest.audio_sha256)
        try:
            if sum(map(len, iterator)) != manifest.audio_bytes:
                raise StorageError("storage_size_mismatch")
        finally:
            close = getattr(iterator, "close", None)
            if close is not None:
                close()


class SyntheticAudio:
    def __init__(self, imports: SyntheticImports) -> None:
        self.imports = imports
        self.database = imports.database

    async def manifest(
        self, actor: ActorContext, manifest: SyntheticAudioManifest, *, key: str
    ) -> dict[str, Any]:
        now = await self.imports.admit(actor, write=True)
        call = await self._call(manifest.call_id)
        try:
            manifest.require_bundle(SyntheticCallBundle.model_validate(call.payload))
        except ValueError:
            raise ConversationConflict("This media does not match its authored call.") from None
        payload = manifest.model_dump(by_alias=True)
        created = await self.imports._save(
            actor,
            kind="audio_manifest",
            key=manifest.call_id,
            revision=1,
            business_id=call.business_id,
            occurred_at=call.occurred_at,
            payload=payload,
            now=now,
        )
        await self.imports._receipt(
            actor, key, {"audio_manifest_sha256": content_hash(payload)}, now
        )
        return {"synthetic": True, "state": "done", "created": created}

    async def _call(self, call_id: str) -> ConversationSyntheticRecord:
        call = await self.database.get(
            ConversationSyntheticRecord, (self.imports.ownership.tenant_id, "call", call_id, 1)
        )
        if call is None:
            raise ConversationConflict("Import the exact authored call before its media.")
        return call

    async def prepared(
        self, actor: ActorContext, call_id: str, *, write: bool = False
    ) -> tuple[ConversationSyntheticRecord, SyntheticAudioManifest]:
        await self.imports.admit(actor, write=write)
        call = await self._call(call_id)
        row = await self.database.get(
            ConversationSyntheticRecord,
            (self.imports.ownership.tenant_id, "audio_manifest", call_id, 1),
        )
        if row is None:
            raise ConversationConflict("Import this call's verified media manifest first.")
        manifest = SyntheticAudioManifest.model_validate(row.payload)
        manifest.require_bundle(SyntheticCallBundle.model_validate(call.payload))
        return call, manifest

    async def delivered(
        self,
        actor: ActorContext,
        call_id: str,
        *,
        key: str,
        native_sha256: str,
        measured_duration_ms: int,
    ) -> dict[str, Any]:
        call, manifest = await self.prepared(actor, call_id, write=True)
        payload = {
            "synthetic": True,
            "call_id": call_id,
            "call_bundle_sha256": manifest.call_bundle_sha256,
            "audio_sha256": manifest.audio_sha256,
            "audio_bytes": manifest.audio_bytes,
            "content_type": manifest.content_type,
            "native_receipt_sha256": native_sha256,
            "measured_duration_ms": measured_duration_ms,
        }
        now = utc(self.imports.ownership.clock())
        created = await self.imports._save(
            actor,
            kind="audio",
            key=call_id,
            revision=1,
            business_id=call.business_id,
            occurred_at=call.occurred_at,
            payload=payload,
            now=now,
        )
        await self.imports._receipt(
            actor, key, {"audio_sha256": manifest.audio_sha256, "call_id": call_id}, now
        )
        return {"synthetic": True, "state": "done", "created": created}
