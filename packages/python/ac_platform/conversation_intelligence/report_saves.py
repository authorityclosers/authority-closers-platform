"""Saved reports: one person's Save and Unsave of a call's report (Reports V4, 13 Nov 2026).

Dipak's spec makes "Saved Reports" its own choice in the Reports filter. A report is saved
for the person who saved it, in that workspace: the newest row per person and call stands
(``report_save_models``). Saving needs only the right to read the call, so an owner who
reads a seller's report can save it for themselves; it never changes the call, its report
or anyone else's list. Rows are erased with the recording and with the person's account.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ac_platform.conversation_intelligence.application import (
    ConversationConflict,
    ConversationDenied,
    ConversationNotFound,
    utc,
)
from ac_platform.conversation_intelligence.guest_models import ConversationGuestSubmission
from ac_platform.conversation_intelligence.guest_ownership import GuestOwnership
from ac_platform.conversation_intelligence.report_save_models import ConversationReportSave
from ac_platform.kernel.authz import ActorContext


async def _latest(
    database: AsyncSession, *, tenant_id: UUID, person_id: UUID, submission_id: UUID
) -> ConversationReportSave | None:
    save = ConversationReportSave
    row: ConversationReportSave | None = await database.scalar(
        select(save)
        .where(
            save.tenant_id == tenant_id,
            save.person_id == person_id,
            save.submission_id == submission_id,
        )
        .order_by(save.revision.desc())
        .limit(1)
    )
    return row


async def set_report_saved(
    ownership: GuestOwnership,
    submission_id: UUID,
    *,
    actor: ActorContext | None,
    saved: bool,
    now: datetime | None = None,
    shared_identity_locks: bool = False,
) -> bool:
    """Save or unsave a call's report for the signed-in person; answers whether it is saved.

    Asking for what already stands writes nothing, so a repeated tap or a retry is harmless.
    Two writes racing for the same next revision: one wins, the other is a conflict.
    """
    if actor is None or actor.tenant_id is None:
        raise ConversationDenied("Sign in to save reports.")
    scope = await ownership.require_submission_owner(
        submission_id,
        actor=actor,
        shared_identity_locks=shared_identity_locks,
        allow_organisation_read=True,
    )
    if scope.tenant_id != actor.tenant_id or scope.tenant_id != ownership.tenant_id:
        raise ConversationNotFound("This saved call is unavailable.")
    latest = await _latest(
        ownership.database,
        tenant_id=scope.tenant_id,
        person_id=actor.person_id,
        submission_id=scope.submission_id,
    )
    if (latest.saved if latest is not None else False) == saved:
        return saved
    row = ConversationReportSave(
        id=uuid4(),
        tenant_id=scope.tenant_id,
        person_id=actor.person_id,
        submission_id=scope.submission_id,
        revision=1 if latest is None else latest.revision + 1,
        saved=saved,
        created_at=utc(now or datetime.now(UTC)),
    )
    try:
        async with ownership.database.begin_nested():
            ownership.database.add(row)
            await ownership.database.flush()
    except IntegrityError:
        raise ConversationConflict("This report changed. Try again.") from None
    return saved


async def saved_submissions(
    database: AsyncSession, *, tenant_id: UUID, person_id: UUID, submission_ids: list[UUID]
) -> set[UUID]:
    """Which of these calls the person has saved now, in one statement."""
    if not submission_ids:
        return set()
    save = ConversationReportSave
    rows = await database.execute(
        select(save.submission_id, save.saved)
        .where(
            save.tenant_id == tenant_id,
            save.person_id == person_id,
            save.submission_id.in_(submission_ids),
        )
        .order_by(save.submission_id, save.revision.desc())
        .distinct(save.submission_id)
    )
    return {submission_id for submission_id, saved in rows if saved}


async def erase_report_saves_for_recording(
    database: AsyncSession, *, tenant_id: UUID, recording_id: UUID
) -> int:
    """Remove every saved mark on a recording's calls when the recording is erased."""
    submission_ids = select(ConversationGuestSubmission.submission_id).where(
        ConversationGuestSubmission.tenant_id == tenant_id,
        ConversationGuestSubmission.recording_id == recording_id,
    )
    result = await database.execute(
        delete(ConversationReportSave).where(
            ConversationReportSave.tenant_id == tenant_id,
            ConversationReportSave.submission_id.in_(submission_ids),
        )
    )
    return int(getattr(result, "rowcount", 0) or 0)


async def erase_report_saves_for_person(database: AsyncSession, *, person_id: UUID) -> int:
    """Remove a person's saved marks in the canonical account-deletion transaction."""
    result = await database.execute(
        delete(ConversationReportSave).where(ConversationReportSave.person_id == person_id)
    )
    return int(getattr(result, "rowcount", 0) or 0)
