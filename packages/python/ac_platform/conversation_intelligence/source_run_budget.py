"""The upload lease owns work before an accepted processing plan takes over."""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import Select, exists, func, select

from ac_platform.conversation_intelligence.acquisition_models import (
    ConversationAcquisitionSettlement,
    ConversationAcquisitionUsage,
    ConversationReportMinuteEvent,
)
from ac_platform.conversation_intelligence.guest_models import (
    ConversationProcessingContinuation,
    ConversationProcessingLease,
)
from ac_platform.conversation_intelligence.models import ConversationProcessingPlan


def expired_source_reservations(now: datetime) -> Select[tuple[ConversationAcquisitionUsage]]:
    """Only unsatisfied reservations without a live plan; no execution authority."""
    usage = ConversationAcquisitionUsage
    lease = ConversationProcessingLease
    latest_kind = (
        select(ConversationReportMinuteEvent.kind)
        .where(ConversationReportMinuteEvent.usage_id == usage.id)
        .order_by(ConversationReportMinuteEvent.revision.desc())
        .limit(1)
        .correlate(usage)
        .scalar_subquery()
    )
    live_plan = exists(
        select(ConversationProcessingPlan.id).where(
            ConversationProcessingPlan.processing_lease_id == lease.id,
            ConversationProcessingPlan.state.in_(("quoted", "active")),
            ConversationProcessingPlan.expires_at > now,
            ConversationProcessingPlan.erased_at.is_(None),
        )
    )
    delivered_legacy = exists(
        select(ConversationAcquisitionSettlement.usage_id).where(
            ConversationAcquisitionSettlement.usage_id == usage.id,
            ConversationAcquisitionSettlement.kind == "completed",
        )
    )
    continuation_expiry = (
        select(func.max(ConversationProcessingContinuation.expires_at))
        .where(
            ConversationProcessingContinuation.processing_lease_id == lease.id,
            ConversationProcessingContinuation.usage_id == usage.id,
        )
        .correlate(usage, lease)
        .scalar_subquery()
    )
    return (
        select(usage)
        .outerjoin(lease, lease.usage_id == usage.id)
        .where(
            func.greatest(
                func.coalesce(lease.expires_at, usage.created_at + timedelta(hours=1)),
                continuation_expiry,
            )
            <= now,
            func.coalesce(latest_kind, "reserved") == "reserved",
            ~live_plan,
            ~delivered_legacy,
        )
        .order_by(usage.created_at, usage.id)
    )
