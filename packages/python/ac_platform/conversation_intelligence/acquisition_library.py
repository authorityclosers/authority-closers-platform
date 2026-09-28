"""Bounded account library over immutable upload ownership and explicit claims."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import and_, or_, select, tuple_

from ac_platform.conversation_intelligence.acquisition_models import (
    ConversationAcquisitionUsage,
    ConversationVisitorClaim,
)
from ac_platform.conversation_intelligence.acquisition_reports import AcquisitionReports
from ac_platform.conversation_intelligence.application import ConversationNotFound
from ac_platform.conversation_intelligence.guest_models import ConversationGuestSubmission
from ac_platform.conversation_intelligence.guest_ownership import GuestOwnership
from ac_platform.conversation_intelligence.models import (
    ConversationPermission,
    ConversationRecording,
)
from ac_platform.conversation_intelligence.submission_labels import read_submission_label
from ac_platform.kernel.authz import ActorContext

PAGE_SIZE = 20


def _submission_owner_filter(
    usage: Any,
    claim: Any,
    *,
    person_id: UUID | None,
    visitor_id: UUID | None,
) -> Any:
    """Use the same direct/claimed account and visitor scope as the library."""
    return (
        or_(usage.person_id == person_id, claim.person_id == person_id)
        if person_id is not None
        else usage.visitor_id == visitor_id
    )


async def earlier_report_submission_id(
    ownership: GuestOwnership,
    *,
    submission_id: UUID,
    source_sha256: str,
    token: str | None = None,
    actor: ActorContext | None = None,
    shared_identity_locks: bool = False,
) -> str | None:
    """Find the latest earlier retained report owned by this account or guest session."""
    now = await ownership.sessions._admit()
    visitor_id, person_id = await ownership.sessions._owner(
        None if actor is not None else token,
        actor,
        now,
        shared_identity_locks=shared_identity_locks,
    )
    current = await ownership.database.scalar(
        select(ConversationAcquisitionUsage).where(
            ConversationAcquisitionUsage.tenant_id == ownership.tenant_id,
            ConversationAcquisitionUsage.submission_id == submission_id,
            ConversationAcquisitionUsage.source_sha256 == source_sha256,
        )
    )
    if current is None:
        return None
    usage = ConversationAcquisitionUsage
    claim = ConversationVisitorClaim
    query = (
        select(usage)
        .outerjoin(
            claim, and_(claim.visitor_id == usage.visitor_id, claim.tenant_id == usage.tenant_id)
        )
        .where(
            usage.tenant_id == ownership.tenant_id,
            usage.source_sha256 == source_sha256,
            _submission_owner_filter(usage, claim, person_id=person_id, visitor_id=visitor_id),
            tuple_(usage.created_at, usage.submission_id)
            < (current.created_at, current.submission_id),
        )
    )
    rows = (
        await ownership.database.scalars(
            query.order_by(usage.created_at.desc(), usage.submission_id.desc()).limit(PAGE_SIZE)
        )
    ).all()
    reports = AcquisitionReports(ownership)
    for row in rows:
        try:
            progress = await reports.progress(
                row.submission_id,
                token=None if actor is not None else token,
                actor=actor,
                shared_identity_locks=shared_identity_locks,
            )
        except ConversationNotFound:
            continue
        if progress["has_report"]:
            return str(row.submission_id)
    return None


async def account_library(
    ownership: GuestOwnership,
    actor: ActorContext,
    *,
    before: UUID | None = None,
    shared_identity_locks: bool = False,
) -> dict[str, Any]:
    """Read retained direct/claimed uploads without renewing or assigning ownership.

    The cursor is a selector into this account's immutable receipts, never an
    owner assertion. It remains usable after deletion of a previous page's last
    call. Rounded duration comes from the immutable source allowance receipt.
    Every selected row is rechecked through the same port as playback/report reads.
    """
    now = await ownership.sessions._admit()
    await ownership.sessions._owner(
        None,
        actor,
        now,
        shared_identity_locks=shared_identity_locks,
    )
    usage, claim = ConversationAcquisitionUsage, ConversationVisitorClaim
    link, recording = ConversationGuestSubmission, ConversationRecording
    permission = ConversationPermission
    query = (
        select(usage)
        .outerjoin(
            claim, and_(claim.visitor_id == usage.visitor_id, claim.tenant_id == usage.tenant_id)
        )
        .join(
            link,
            and_(
                link.usage_id == usage.id,
                link.tenant_id == usage.tenant_id,
                link.submission_id == usage.submission_id,
            ),
        )
        .join(
            recording,
            and_(
                recording.id == link.recording_id,
                recording.tenant_id == link.tenant_id,
                recording.person_id == link.person_id,
                recording.source_sha256 == link.source_sha256,
                recording.source_sha256 == usage.source_sha256,
            ),
        )
        .join(
            permission,
            and_(
                permission.id == recording.permission_id,
                permission.tenant_id == recording.tenant_id,
                permission.person_id == recording.person_id,
                permission.source_sha256 == recording.source_sha256,
            ),
        )
        .where(
            usage.tenant_id == actor.tenant_id,
            _submission_owner_filter(usage, claim, person_id=actor.person_id, visitor_id=None),
        )
    )
    if before is not None:
        cursor = await ownership.database.scalar(query.where(usage.submission_id == before))
        if cursor is None:
            raise ConversationNotFound("This saved-call page is unavailable.")
        query = query.where(
            tuple_(usage.created_at, usage.submission_id)
            < (cursor.created_at, cursor.submission_id)
        )
    query = query.where(
        recording.state.in_(("awaiting_upload", "ready")),
        permission.revoked_at.is_(None),
        permission.retention_until > now,
    )
    rows = (
        await ownership.database.scalars(
            query.order_by(usage.created_at.desc(), usage.submission_id.desc()).limit(PAGE_SIZE + 1)
        )
    ).all()
    reports = AcquisitionReports(ownership)
    entries = []
    for row in rows[:PAGE_SIZE]:
        try:
            progress = await reports.progress(
                row.submission_id,
                actor=actor,
                shared_identity_locks=shared_identity_locks,
            )
            label = await read_submission_label(
                ownership,
                row.submission_id,
                actor=actor,
                shared_identity_locks=shared_identity_locks,
            )
        except ConversationNotFound:
            # A concurrent deletion/revocation may win before the per-record locks.
            # Never return the stale selector; pagination still advances past it.
            continue
        entries.append(
            {
                "submission_id": str(row.submission_id),
                "created_at": row.created_at.isoformat(),
                "duration_seconds": row.reserved_seconds,
                "display_name": label.display_name,
                "display_name_revision": label.revision,
                "state": progress["state"],
                "has_report": progress["has_report"],
            }
        )
    return {
        "submissions": entries,
        "next_cursor": str(rows[PAGE_SIZE - 1].submission_id) if len(rows) > PAGE_SIZE else None,
    }
