"""Audited, append-only sensitive-segment marks (ADR 0051, AUT-519 D1–D2).

Every write happens in the caller's transaction, adds one row per segment and
one audit event per row in the recording's tenant, and names the operator and a
``reason_ref``. Nothing here reads, stores or returns segment text: a mark is
checked against the segment IDs of a non-erased C2 checkpoint only.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4, uuid5

from sqlalchemy import exists, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ac_platform.audit.models import AuditEvent
from ac_platform.audit.service import AuditRepository
from ac_platform.conversation_intelligence.checkpoints import content_hash
from ac_platform.conversation_intelligence.models import (
    ConversationCheckpoint,
    ConversationRecording,
)
from ac_platform.conversation_intelligence.sensitive_segment_models import (
    REASON_REF_PATTERN,
    SENSITIVE_CATEGORIES,
    ConversationSensitiveSegmentMark,
)
from ac_platform.conversation_intelligence.sensitive_segments import (
    EMPTY_PLAN,
    Gram,
    WithheldPlan,
    grams,
    withheld_plan,
)
from ac_platform.kernel.authz import ActorContext
from ac_platform.kernel.errors import DomainError

_COMMAND_NAMESPACE = UUID("8f0b6c2e-3d1a-4f7e-9b61-5c2a0d4e7f10")
MAX_SEGMENTS_PER_COMMAND = 20


class SensitiveSegmentRecordingNotFound(DomainError):
    code = "sensitive_segment_recording_not_found"
    title = "The recording is unavailable"
    status = 404


class SensitiveSegmentRevisionUnknown(DomainError):
    code = "sensitive_segment_revision_unknown"
    title = "The transcript revision is not held for this recording"
    status = 409


class SensitiveSegmentConflict(DomainError):
    code = "sensitive_segment_conflict"
    title = "The sensitive-segment command conflicts with history"
    status = 409


class SensitiveSegmentInvalid(DomainError):
    code = "sensitive_segment_invalid"
    title = "The sensitive-segment command is invalid"
    status = 422


@dataclass(frozen=True, slots=True)
class EffectiveMark:
    """An unreleased mark, identified by IDs only; never carries text."""

    mark_id: UUID
    tenant_id: UUID
    recording_id: UUID
    transcript_revision: str
    segment_id: str
    category: str
    source: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class TranscriptRevisionSummary:
    revision: str
    segment_count: int


@dataclass(frozen=True, slots=True)
class RecordingMarks:
    recording_id: UUID
    tenant_id: UUID
    transcript_revisions: tuple[TranscriptRevisionSummary, ...]
    marks: tuple[ConversationSensitiveSegmentMark, ...]


def _effective_statement(*conditions: Any) -> Any:
    release = ConversationSensitiveSegmentMark.__table__.alias("release")
    unreleased = ~exists().where(
        release.c.supersedes_mark_id == ConversationSensitiveSegmentMark.id
    )
    return (
        select(ConversationSensitiveSegmentMark)
        .where(ConversationSensitiveSegmentMark.action == "mark", unreleased, *conditions)
        .order_by(ConversationSensitiveSegmentMark.created_at, ConversationSensitiveSegmentMark.id)
    )


def _effective(row: ConversationSensitiveSegmentMark) -> EffectiveMark:
    return EffectiveMark(
        mark_id=row.id,
        tenant_id=row.tenant_id,
        recording_id=row.recording_id,
        transcript_revision=row.transcript_revision,
        segment_id=row.segment_id,
        category=row.category,
        source=row.source,
        created_at=row.created_at,
    )


async def effective_marks(
    database: AsyncSession, *, recording_id: UUID, transcript_revision: str
) -> tuple[EffectiveMark, ...]:
    """Marks in force for this recording or for any recording serving the same transcript.

    Duplicate uploads reuse the retained C2 transcript, so a mark keyed on one
    recording must also withhold the segment wherever that revision is served.
    """

    rows = await database.scalars(
        _effective_statement(
            or_(
                ConversationSensitiveSegmentMark.recording_id == recording_id,
                ConversationSensitiveSegmentMark.transcript_revision == transcript_revision,
            )
        )
    )
    return tuple(_effective(row) for row in rows)


async def _c2_segment_texts(
    database: AsyncSession, recording_id: UUID, *, tenant_id: UUID | None = None
) -> dict[str, dict[str, str]]:
    """Segment text per transcript revision, from the recording's non-erased C2 checkpoints."""

    conditions = [
        ConversationCheckpoint.recording_id == recording_id,
        ConversationCheckpoint.stage == "C2",
        ConversationCheckpoint.erased_at.is_(None),
    ]
    if tenant_id is not None:
        conditions.append(ConversationCheckpoint.tenant_id == tenant_id)
    checkpoints = await database.scalars(
        select(ConversationCheckpoint)
        .where(*conditions)
        .order_by(ConversationCheckpoint.created_at, ConversationCheckpoint.id)
    )
    revisions: dict[str, dict[str, str]] = {}
    for checkpoint in checkpoints:
        payload = checkpoint.payload
        if not isinstance(payload, dict):
            continue
        revision = payload.get("revision")
        segments = payload.get("segments")
        if not isinstance(revision, str) or not revision or not isinstance(segments, list):
            continue
        texts: dict[str, str] = {}
        for segment in segments:
            if isinstance(segment, dict) and isinstance(segment.get("id"), str):
                text = segment.get("text")
                texts[segment["id"]] = text if isinstance(text, str) else ""
        revisions[revision] = texts
    return revisions


async def _marks_for_read(
    database: AsyncSession, recording_id: UUID, served: frozenset[str]
) -> tuple[EffectiveMark, ...]:
    condition = ConversationSensitiveSegmentMark.recording_id == recording_id
    if served:
        condition = or_(condition, ConversationSensitiveSegmentMark.transcript_revision.in_(served))
    rows = await database.scalars(_effective_statement(condition))
    return tuple(_effective(row) for row in rows)


async def withheld_plan_for(
    database: AsyncSession, *, recording_id: UUID, served_revisions: Iterable[str] | None = None
) -> WithheldPlan:
    """W* for one read (AUT-519 D4), in two queries; ``EMPTY_PLAN`` when nothing is marked.

    Marks on a served revision contribute segment IDs and grams; marks on any
    other revision of this recording contribute grams only. ``None`` serves
    every C2 revision of the recording (the raw checkpoints surface).
    """

    texts = await _c2_segment_texts(database, recording_id)
    served = frozenset(texts) if served_revisions is None else frozenset(served_revisions)
    marks = await _marks_for_read(database, recording_id, served)
    if not marks:
        return EMPTY_PLAN
    marked_ids = {mark.segment_id for mark in marks if mark.transcript_revision in served}
    marked_grams: set[Gram] = set()
    for mark in marks:
        marked_grams |= grams(texts.get(mark.transcript_revision, {}).get(mark.segment_id, ""))
    served_segments = [
        (segment_id, text)
        for revision in served
        for segment_id, text in texts.get(revision, {}).items()
    ]
    return withheld_plan(served_segments, marked_ids, marked_grams)


async def marks_in_force(database: AsyncSession, *, recording_id: UUID) -> bool:
    """True while any mark is effective for this recording or a revision it serves (D7)."""

    texts = await _c2_segment_texts(database, recording_id)
    return bool(await _marks_for_read(database, recording_id, frozenset(texts)))


class SensitiveSegmentsStore:
    """Platform-operator reads and writes; the caller has already checked the capability."""

    def __init__(self, database: AsyncSession) -> None:
        self.database = database

    async def recording(self, recording_id: UUID) -> RecordingMarks:
        recording = await self._recording(recording_id, lock=False)
        revisions = await self._revisions(recording)
        rows = await self.database.scalars(
            select(ConversationSensitiveSegmentMark)
            .where(ConversationSensitiveSegmentMark.recording_id == recording.id)
            .order_by(
                ConversationSensitiveSegmentMark.created_at.desc(),
                ConversationSensitiveSegmentMark.id.desc(),
            )
        )
        return RecordingMarks(
            recording_id=recording.id,
            tenant_id=recording.tenant_id,
            transcript_revisions=tuple(
                TranscriptRevisionSummary(revision=revision, segment_count=len(segments))
                for revision, segments in revisions.items()
            ),
            marks=tuple(rows),
        )

    async def mark(
        self,
        actor: ActorContext,
        *,
        recording_id: UUID,
        transcript_revision: str,
        segments: Sequence[tuple[str, str]],
        reason_ref: str,
        idempotency_key: str,
        source: str = "operator",
    ) -> tuple[ConversationSensitiveSegmentMark, ...]:
        """Mark segments; a segment already effectively marked is returned unchanged."""

        reason_ref = _reason_ref(reason_ref)
        key = _idempotency_key(idempotency_key)
        if not 1 <= len(segments) <= MAX_SEGMENTS_PER_COMMAND:
            raise SensitiveSegmentInvalid(
                f"Mark between 1 and {MAX_SEGMENTS_PER_COMMAND} segments per command."
            )
        requested: dict[str, str] = {}
        for segment_id, category in segments:
            if category not in SENSITIVE_CATEGORIES:
                raise SensitiveSegmentInvalid("The category is not supported.")
            if requested.get(segment_id, category) != category:
                raise SensitiveSegmentInvalid(f"Segment {segment_id} is listed twice.")
            requested[segment_id] = category
        recording = await self._recording(recording_id, lock=True)
        revisions = await self._revisions(recording)
        known = revisions.get(transcript_revision)
        if known is None:
            raise SensitiveSegmentRevisionUnknown(
                f"Recording {recording.id} holds no transcript revision {transcript_revision}."
            )
        unknown = sorted(set(requested) - known)
        if unknown:
            raise SensitiveSegmentInvalid(
                f"Segment {unknown[0]} is not in transcript revision {transcript_revision}."
            )
        now = datetime.now(UTC)
        await self._request_receipt(
            actor,
            recording,
            key=key,
            fingerprint=content_hash(
                {
                    "recording_id": str(recording.id),
                    "transcript_revision": transcript_revision,
                    "segments": sorted(requested.items()),
                    "reason_ref": reason_ref,
                }
            ),
            reason_ref=reason_ref,
            now=now,
        )
        current = {
            row.segment_id: row
            for row in await self.database.scalars(
                _effective_statement(
                    ConversationSensitiveSegmentMark.recording_id == recording.id,
                    ConversationSensitiveSegmentMark.transcript_revision == transcript_revision,
                )
            )
        }
        replayed = {
            row.id: row
            for row in await self.database.scalars(
                select(ConversationSensitiveSegmentMark).where(
                    ConversationSensitiveSegmentMark.id.in_(
                        [_command_id(actor, key, segment_id) for segment_id in requested]
                    )
                )
            )
        }
        result: list[ConversationSensitiveSegmentMark] = []
        for segment_id, category in requested.items():
            command_id = _command_id(actor, key, segment_id)
            existing = replayed.get(command_id)
            if existing is not None:
                if (
                    existing.recording_id != recording.id
                    or existing.transcript_revision != transcript_revision
                    or existing.category != category
                    or existing.reason_ref != reason_ref
                ):
                    raise SensitiveSegmentConflict(
                        "The Idempotency-Key has already been used for another change."
                    )
                result.append(existing)
                continue
            effective = current.get(segment_id)
            if effective is not None:
                result.append(effective)
                continue
            result.append(
                await self._append(
                    actor,
                    recording,
                    command_id=command_id,
                    transcript_revision=transcript_revision,
                    segment_id=segment_id,
                    category=category,
                    action="mark",
                    supersedes_mark_id=None,
                    source=source,
                    reason_ref=reason_ref,
                    now=now,
                )
            )
        return tuple(result)

    async def release(
        self, actor: ActorContext, *, mark_id: UUID, reason_ref: str, idempotency_key: str
    ) -> ConversationSensitiveSegmentMark:
        reason_ref = _reason_ref(reason_ref)
        key = _idempotency_key(idempotency_key)
        mark = await self.database.get(ConversationSensitiveSegmentMark, mark_id)
        if mark is None or mark.action != "mark":
            raise SensitiveSegmentRecordingNotFound(f"Mark {mark_id} is unavailable.")
        recording = await self._recording(mark.recording_id, lock=True)
        command_id = _command_id(actor, key, f"release:{mark.id}")
        existing = await self.database.get(ConversationSensitiveSegmentMark, command_id)
        if existing is not None:
            if existing.supersedes_mark_id != mark.id or existing.reason_ref != reason_ref:
                raise SensitiveSegmentConflict(
                    "The Idempotency-Key has already been used for another change."
                )
            return existing
        released = await self.database.scalar(
            select(ConversationSensitiveSegmentMark).where(
                ConversationSensitiveSegmentMark.supersedes_mark_id == mark.id
            )
        )
        if released is not None:
            raise SensitiveSegmentConflict(f"Mark {mark.id} was already released.")
        return await self._append(
            actor,
            recording,
            command_id=command_id,
            transcript_revision=mark.transcript_revision,
            segment_id=mark.segment_id,
            category=mark.category,
            action="release",
            supersedes_mark_id=mark.id,
            source="operator",
            reason_ref=reason_ref,
            now=datetime.now(UTC),
        )

    async def _recording(self, recording_id: UUID, *, lock: bool) -> ConversationRecording:
        statement = select(ConversationRecording).where(ConversationRecording.id == recording_id)
        if lock:
            statement = statement.with_for_update()
        recording = await self.database.scalar(statement)
        if recording is None:
            raise SensitiveSegmentRecordingNotFound(f"Recording {recording_id} is unavailable.")
        return recording

    async def _revisions(self, recording: ConversationRecording) -> dict[str, frozenset[str]]:
        """Segment IDs per transcript revision, from the recording's non-erased C2 checkpoints."""

        texts = await _c2_segment_texts(self.database, recording.id, tenant_id=recording.tenant_id)
        return {revision: frozenset(segments) for revision, segments in texts.items()}

    async def _request_receipt(
        self,
        actor: ActorContext,
        recording: ConversationRecording,
        *,
        key: str,
        fingerprint: str,
        reason_ref: str,
        now: datetime,
    ) -> None:
        """One audit event per actor and Idempotency-Key binds the key to the whole request body."""

        request_id = str(_command_id(actor, key, "request"))
        prior = await self.database.scalar(
            select(AuditEvent).where(
                AuditEvent.action == "conversation.sensitive_segment.mark_request",
                AuditEvent.resource_id == request_id,
            )
        )
        if prior is not None:
            if prior.payload.get("fingerprint_sha256") != fingerprint:
                raise SensitiveSegmentConflict(
                    "The Idempotency-Key has already been used for another change."
                )
            return
        await AuditRepository(self.database).append(
            tenant_id=recording.tenant_id,
            actor_person_id=actor.person_id,
            session_id=actor.session_id,
            action="conversation.sensitive_segment.mark_request",
            resource_type="conversation_sensitive_segment_mark",
            resource_id=request_id,
            payload={"recording_id": str(recording.id), "fingerprint_sha256": fingerprint},
            reason=reason_ref,
            now=now,
        )

    async def _append(
        self,
        actor: ActorContext,
        recording: ConversationRecording,
        *,
        command_id: UUID,
        transcript_revision: str,
        segment_id: str,
        category: str,
        action: str,
        supersedes_mark_id: UUID | None,
        source: str,
        reason_ref: str,
        now: datetime,
    ) -> ConversationSensitiveSegmentMark:
        audit_id = uuid4()
        await AuditRepository(self.database).append(
            event_id=audit_id,
            tenant_id=recording.tenant_id,
            actor_person_id=actor.person_id,
            session_id=actor.session_id,
            action=f"conversation.sensitive_segment.{action}",
            resource_type="conversation_sensitive_segment_mark",
            resource_id=command_id,
            payload={
                "recording_id": str(recording.id),
                "transcript_revision": transcript_revision,
                "segment_id": segment_id,
                "category": category,
                "source": source,
                "supersedes_mark_id": (
                    str(supersedes_mark_id) if supersedes_mark_id is not None else None
                ),
            },
            reason=reason_ref,
            now=now,
        )
        row = ConversationSensitiveSegmentMark(
            id=command_id,
            tenant_id=recording.tenant_id,
            recording_id=recording.id,
            transcript_revision=transcript_revision,
            segment_id=segment_id,
            category=category,
            action=action,
            supersedes_mark_id=supersedes_mark_id,
            source=source,
            actor_person_id=actor.person_id,
            reason_ref=reason_ref,
            audit_event_id=audit_id,
            created_at=now,
        )
        self.database.add(row)
        await self.database.flush()
        return row


def _command_id(actor: ActorContext, key: str, suffix: str) -> UUID:
    return uuid5(_COMMAND_NAMESPACE, f"{actor.person_id}|{key}|{suffix}")


def _idempotency_key(value: str) -> str:
    key = value.strip()
    if not key or len(key) > 128:
        raise SensitiveSegmentInvalid("Idempotency-Key must be 1 to 128 characters.")
    return key


def _reason_ref(value: str) -> str:
    if REASON_REF_PATTERN.fullmatch(value) is None:
        raise SensitiveSegmentInvalid("reason_ref must be a short reference such as an issue ID.")
    return value


__all__ = [
    "MAX_SEGMENTS_PER_COMMAND",
    "EffectiveMark",
    "RecordingMarks",
    "SensitiveSegmentConflict",
    "SensitiveSegmentInvalid",
    "SensitiveSegmentRecordingNotFound",
    "SensitiveSegmentRevisionUnknown",
    "SensitiveSegmentsStore",
    "TranscriptRevisionSummary",
    "effective_marks",
    "marks_in_force",
    "withheld_plan_for",
]
