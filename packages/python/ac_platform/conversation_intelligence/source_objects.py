"""Resolve source audio inside the caller's authorized recording transaction (ADR 0033)."""

from sqlalchemy.ext.asyncio import AsyncSession

from ac_platform.conversation_intelligence.models import ConversationRecording
from ac_platform.conversation_intelligence.source_object_models import (
    ConversationSourceObject,
    ConversationSourceReference,
)
from ac_platform.conversation_intelligence.storage import (
    ObjectKey,
    ObjectKind,
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
