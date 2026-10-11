"""Make an accepted plan due atomically with its predecessor's publication."""

from sqlalchemy import func, update
from sqlalchemy.ext.asyncio import AsyncSession

from ac_platform.conversation_intelligence.models import (
    ConversationProcessingPlan,
    ConversationRecording,
)


async def make_plans_due(database: AsyncSession, recording: ConversationRecording) -> None:
    # This is scheduling only. The coordinator still rechecks current consent,
    # actor, source, route, budget and immutable checkpoint before enqueuing.
    await database.execute(
        update(ConversationProcessingPlan)
        .where(
            ConversationProcessingPlan.tenant_id == recording.tenant_id,
            ConversationProcessingPlan.recording_id == recording.id,
            ConversationProcessingPlan.generation == recording.generation,
            ConversationProcessingPlan.state == "active",
            ConversationProcessingPlan.erased_at.is_(None),
        )
        .values(next_check_at=func.clock_timestamp())
        .execution_options(synchronize_session=False)
    )
