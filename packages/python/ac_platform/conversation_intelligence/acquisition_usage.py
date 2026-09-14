"""Read shared acquisition usage without changing the existing account ledger.

Account mutations hold the canonical Person lock before these reads. Guest
claim commands use that same lock, so a claim and an existing-account enqueue
cannot each spend the balance observed before the other commits.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ac_platform.conversation_intelligence.acquisition_models import (
    ConversationAcquisitionSettlement,
    ConversationAcquisitionUsage,
    ConversationVisitorClaim,
)
from ac_platform.conversation_intelligence.entitlements import MinuteAccount
from ac_platform.conversation_intelligence.models import ConversationMinuteAccount

ALLOWANCE_SECONDS = 3600


async def acquisition_seconds(
    database: AsyncSession,
    *,
    tenant_id: UUID,
    visitor_id: UUID | None = None,
    person_id: UUID | None = None,
) -> int:
    """Acquisition reservations plus all immutable claims for the exact owner."""
    if (visitor_id is None) == (person_id is None):
        raise ValueError("Exactly one acquisition owner is required.")
    usage = ConversationAcquisitionUsage
    if person_id is not None:
        claimed = select(ConversationVisitorClaim.visitor_id).where(
            ConversationVisitorClaim.tenant_id == tenant_id,
            ConversationVisitorClaim.person_id == person_id,
        )
        owner = or_(usage.person_id == person_id, usage.visitor_id.in_(claimed))
    else:
        owner = usage.visitor_id == visitor_id
    charged = func.coalesce(
        ConversationAcquisitionSettlement.charged_seconds, usage.reserved_seconds
    )
    total = await database.scalar(
        select(func.coalesce(func.sum(charged), 0))
        .select_from(usage)
        .outerjoin(
            ConversationAcquisitionSettlement,
            ConversationAcquisitionSettlement.usage_id == usage.id,
        )
        .where(usage.tenant_id == tenant_id, owner)
    )
    return int(total or 0)


async def existing_account_seconds(
    database: AsyncSession, *, tenant_id: UUID, person_id: UUID
) -> int:
    """Count reserved/uncertain/settled use; only confirmed releases count zero."""
    row = await database.scalar(
        select(ConversationMinuteAccount)
        .where(
            ConversationMinuteAccount.tenant_id == tenant_id,
            ConversationMinuteAccount.person_id == person_id,
        )
        .execution_options(populate_existing=True)
    )
    if row is None:
        return 0
    account = MinuteAccount.from_dict(row.snapshot)
    if (account.tenant_id, account.account_id) != (str(tenant_id), str(person_id)):
        raise ValueError("The processing account does not match its owner.")
    return sum(reservation.committed_seconds for reservation in account.reservations)
