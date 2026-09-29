"""Internal canary marking and a tenant-scoped recording predicate."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.selectable import Exists

from ac_platform.conversation_intelligence.canary_models import ConversationCanarySubmission
from ac_platform.conversation_intelligence.guest_models import ConversationGuestSubmission
from ac_platform.conversation_intelligence.models import ConversationRecording


async def mark_canary_submission(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    submission_id: UUID,
    environment: str,
    fixture_sha256: str,
    created_at: datetime,
) -> None:
    db.add(
        ConversationCanarySubmission(
            tenant_id=tenant_id,
            submission_id=submission_id,
            environment=environment,
            fixture_sha256=fixture_sha256,
            created_at=created_at,
        )
    )
    await db.flush()


def recording_is_canary() -> Exists:
    return (
        select(ConversationCanarySubmission.submission_id)
        .join(
            ConversationGuestSubmission,
            (ConversationGuestSubmission.tenant_id == ConversationCanarySubmission.tenant_id)
            & (
                ConversationGuestSubmission.submission_id
                == ConversationCanarySubmission.submission_id
            ),
        )
        .where(
            ConversationGuestSubmission.tenant_id == ConversationRecording.tenant_id,
            ConversationGuestSubmission.recording_id == ConversationRecording.id,
        )
        .correlate(ConversationRecording)
        .exists()
    )
