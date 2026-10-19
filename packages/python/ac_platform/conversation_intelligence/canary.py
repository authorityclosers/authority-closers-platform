"""Internal canary marking and tenant-scoped recording predicates."""

import hashlib
from datetime import datetime
from functools import cache
from importlib import resources
from uuid import UUID

from sqlalchemy import ColumnElement, or_, select
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


@cache
def fixture_sha256s() -> frozenset[str]:
    """The bundled canary recordings. The QA smoke accounts upload the same file."""
    fixtures = resources.files("ac_platform.conversation_intelligence") / "canary_fixture"
    return frozenset(
        hashlib.sha256(item.read_bytes()).hexdigest()
        for item in fixtures.iterdir()
        if item.name.endswith(".wav")
    )


def recording_is_canary() -> ColumnElement[bool]:
    """Our own test calls: marked canary submissions and any upload of a bundled
    canary recording (the nightly QA account run), kept out of usage, recordings,
    review, gold and the library."""
    return or_(
        recording_is_marked_canary(),
        ConversationRecording.source_sha256.in_(sorted(fixture_sha256s())),
    )


def recording_is_marked_canary() -> Exists:
    """Only submissions the canary marked. Use where the fixture file alone must not
    count: the profile gate (anyone can upload a public file) and retention (QA calls
    are deleted on the normal schedule)."""
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
