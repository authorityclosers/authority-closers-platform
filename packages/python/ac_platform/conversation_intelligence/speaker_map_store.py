"""Speaker-choice erasure within the existing recording/account transactions."""

from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from ac_platform.conversation_intelligence.guest_models import ConversationGuestSubmission
from ac_platform.conversation_intelligence.speaker_map_models import (
    ConversationSpeakerMapRevision,
)


async def erase_speaker_maps_for_recording(
    database: AsyncSession, *, tenant_id: UUID, recording_id: UUID
) -> int:
    """Called after canonical recording erasure passes its ownership/lease fences."""
    submission_ids = select(ConversationGuestSubmission.submission_id).where(
        ConversationGuestSubmission.tenant_id == tenant_id,
        ConversationGuestSubmission.recording_id == recording_id,
    )
    result = await database.execute(
        delete(ConversationSpeakerMapRevision).where(
            ConversationSpeakerMapRevision.tenant_id == tenant_id,
            ConversationSpeakerMapRevision.submission_id.in_(submission_ids),
        )
    )
    return int(getattr(result, "rowcount", 0) or 0)


async def erase_speaker_maps_for_person(database: AsyncSession, *, person_id: UUID) -> int:
    """Called by canonical account deletion before membership termination."""
    result = await database.execute(
        delete(ConversationSpeakerMapRevision).where(
            ConversationSpeakerMapRevision.actor_person_id == person_id,
        )
    )
    return int(getattr(result, "rowcount", 0) or 0)
