"""Source lifecycle inside an authorized transaction and storage-root fence (ADR 0033)."""

from datetime import datetime
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from ac_platform.conversation_intelligence.async_io import join_thread
from ac_platform.conversation_intelligence.models import ConversationRecording
from ac_platform.conversation_intelligence.source_object_models import (
    ConversationSourceObject,
    ConversationSourceReference,
)
from ac_platform.conversation_intelligence.storage import (
    ObjectKey,
    ObjectKind,
    RecordingObjectStorage,
    SourceAudioKey,
    StorageError,
    StorageKey,
)


async def resolve_source_key(db: AsyncSession, recording: ConversationRecording) -> StorageKey:
    """Only absence of reference history permits the legacy key; invalid history fails closed."""
    reference = await db.get(ConversationSourceReference, recording.id)
    if reference is None:
        return ObjectKey(recording.tenant_id, recording.id, recording.id, ObjectKind.SOURCE_AUDIO)
    if (
        reference.released_at is not None
        or reference.tenant_id != recording.tenant_id
        or reference.person_id != recording.person_id
    ):
        raise StorageError("storage_object_missing")
    source = await db.get(ConversationSourceObject, reference.source_object_id)
    if (
        source is None
        or source.deleted_at is not None
        or source.tenant_id != recording.tenant_id
        or source.source_sha256 != recording.source_sha256
    ):
        raise StorageError("storage_object_missing")
    return SourceAudioKey(source.tenant_id, source.source_sha256)


async def lock_source_object(
    db: AsyncSession, recording: ConversationRecording, now: datetime
) -> ConversationSourceObject:
    """Caller holds the root fence through commit; hits and misses execute identical SQL."""
    await db.execute(
        insert(ConversationSourceObject)
        .values(
            id=uuid4(),
            tenant_id=recording.tenant_id,
            source_sha256=recording.source_sha256,
            created_at=now,
        )
        .on_conflict_do_nothing(
            index_elements=["tenant_id", "source_sha256"],
            index_where=ConversationSourceObject.deleted_at.is_(None),
        )
    )
    source = await db.scalar(
        select(ConversationSourceObject)
        .where(
            ConversationSourceObject.tenant_id == recording.tenant_id,
            ConversationSourceObject.source_sha256 == recording.source_sha256,
            ConversationSourceObject.deleted_at.is_(None),
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if source is None:
        raise StorageError("storage_object_missing")
    return source


async def reference_source_object(
    db: AsyncSession,
    recording: ConversationRecording,
    source: ConversationSourceObject,
    now: datetime,
) -> None:
    """Attach only after the complete incoming body passed verification, under the row lock."""
    await db.execute(
        insert(ConversationSourceReference)
        .values(
            recording_id=recording.id,
            tenant_id=recording.tenant_id,
            person_id=recording.person_id,
            source_object_id=source.id,
            created_at=now,
        )
        .on_conflict_do_nothing(index_elements=["recording_id"])
    )
    if await resolve_source_key(db, recording) != SourceAudioKey(
        source.tenant_id, source.source_sha256
    ):
        raise StorageError("storage_object_changed")


async def release_source_object(
    db: AsyncSession,
    recording: ConversationRecording,
    storage: RecordingObjectStorage,
    now: datetime,
) -> None:
    """Release, unlink if last, then tombstone; caller holds the root fence through commit."""
    reference = await db.get(ConversationSourceReference, recording.id)
    if reference is None:
        return  # Legacy sources are handled by the strict recording inventory.
    source = await db.get(
        ConversationSourceObject,
        reference.source_object_id,
        with_for_update=True,
        populate_existing=True,
    )
    if (
        source is None
        or source.tenant_id != recording.tenant_id
        or source.source_sha256 != recording.source_sha256
        or reference.tenant_id != recording.tenant_id
        or reference.person_id != recording.person_id
    ):
        raise StorageError("storage_object_missing")
    if source.deleted_at is not None:
        if reference.released_at is None:
            raise StorageError("storage_object_missing")
        return
    if reference.released_at is None:
        reference.released_at, reference.release_reason = now, "recording_erasure"
        await db.flush()
    live = await db.scalar(
        select(ConversationSourceReference.recording_id)
        .where(
            ConversationSourceReference.source_object_id == source.id,
            ConversationSourceReference.released_at.is_(None),
        )
        .limit(1)
    )
    if live is None:
        await join_thread(storage.delete, SourceAudioKey(source.tenant_id, source.source_sha256))
        source.deleted_at = now
        await db.flush()
