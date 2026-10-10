"""Customer minutes follow report delivery, independently of provider receipts.

Usage rows serialize this append-only journal. A late worker cannot capture a
released reservation; an explicitly reserved successor can deliver exactly once.
The original acquisition settlements and provider budget records stay intact.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ac_platform.conversation_intelligence.acquisition_models import (
    ConversationAcquisitionSettlement,
    ConversationAcquisitionUsage,
    ConversationReportMinuteEvent,
)
from ac_platform.conversation_intelligence.application import ConversationConflict
from ac_platform.conversation_intelligence.checkpoints import content_hash
from ac_platform.conversation_intelligence.guest_models import (
    ConversationGuestSubmission,
    ConversationProcessingLease,
)
from ac_platform.conversation_intelligence.models import (
    ConversationProcessingPlan,
    ConversationReportDraft,
)


class ReportMinutes:
    def __init__(self, database: AsyncSession) -> None:
        self.database = database

    async def _lock(self, usage_id: UUID, tenant_id: UUID) -> ConversationAcquisitionUsage:
        usage = await self.database.scalar(
            select(ConversationAcquisitionUsage)
            .where(
                ConversationAcquisitionUsage.id == usage_id,
                ConversationAcquisitionUsage.tenant_id == tenant_id,
            )
            .with_for_update()
        )
        if usage is None:
            raise ConversationConflict("The source minute reservation is unavailable.")
        return usage

    async def latest(self, usage_id: UUID) -> ConversationReportMinuteEvent | None:
        result: ConversationReportMinuteEvent | None = await self.database.scalar(
            select(ConversationReportMinuteEvent)
            .where(ConversationReportMinuteEvent.usage_id == usage_id)
            .order_by(ConversationReportMinuteEvent.revision.desc())
            .limit(1)
        )
        return result

    async def reserve_retry(
        self, usage_id: UUID, tenant_id: UUID, *, key: str, available_seconds: int
    ) -> None:
        """Caller holds owner/admission locks and supplies the current allowance."""
        usage = await self._lock(usage_id, tenant_id)
        previous = await self.latest(usage.id)
        if previous is None or previous.kind != "released":
            return
        if type(available_seconds) is not int or available_seconds < usage.reserved_seconds:
            raise ConversationConflict("Your remaining minutes are not enough to retry this call.")
        await self._append(usage, previous, key=key, kind="reserved")

    async def settle_terminal_plan(self) -> bool:
        """Sweep one pre-existing terminal plan after a coordinator restart."""
        row = await self.database.scalar(
            select(ConversationProcessingPlan)
            .where(
                ConversationProcessingPlan.state.in_(("held", "cancelled")),
                ConversationProcessingPlan.processing_lease_id.is_not(None),
                ConversationProcessingPlan.erased_at.is_(None),
                ConversationProcessingPlan.progress["minute_outcome_checked"]
                .as_boolean()
                .is_(None),
            )
            .order_by(ConversationProcessingPlan.created_at)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        if row is None:
            return False
        await self.release_plan(row)
        row.progress = {**row.progress, "minute_outcome_checked": True}
        return True

    async def _append(
        self,
        usage: ConversationAcquisitionUsage,
        previous: ConversationReportMinuteEvent | None,
        *,
        key: str,
        kind: str,
        plan_id: UUID | None = None,
        draft: ConversationReportDraft | None = None,
    ) -> None:
        receipt = content_hash(
            {
                "schema": "ac.sales_xray.report_minutes/1",
                "usage_id": str(usage.id),
                "source_sha256": usage.source_sha256,
                "reserved_seconds": usage.reserved_seconds,
                "kind": kind,
                "plan_id": str(plan_id) if plan_id else None,
                "report_draft_id": str(draft.id) if draft else None,
                "report_sha256": draft.report_sha256 if draft else None,
            }
        )
        replay = await self.database.scalar(
            select(ConversationReportMinuteEvent).where(
                ConversationReportMinuteEvent.usage_id == usage.id,
                ConversationReportMinuteEvent.key == key,
            )
        )
        if replay is not None:
            if replay.receipt_sha256 != receipt:
                raise ConversationConflict(
                    "The minute receipt conflicts with its original request."
                )
            return
        self.database.add(
            ConversationReportMinuteEvent(
                usage_id=usage.id,
                revision=1 if previous is None else previous.revision + 1,
                key=key,
                kind=kind,
                seconds=0 if kind == "released" else usage.reserved_seconds,
                plan_id=plan_id,
                report_draft_id=draft.id if draft else None,
                receipt_sha256=receipt,
                created_at=datetime.now(UTC),
            )
        )
        await self.database.flush()

    async def release_plan(self, plan: ConversationProcessingPlan) -> bool:
        """Terminal customer failure needs no renewed execution permission."""
        if plan.processing_lease_id is None or plan.state not in {"held", "cancelled"}:
            return False
        lease = await self.database.get(ConversationProcessingLease, plan.processing_lease_id)
        if lease is None or (lease.tenant_id, lease.person_id) != (plan.tenant_id, plan.person_id):
            raise ConversationConflict("The processing source does not match its minute owner.")
        usage = await self._lock(lease.usage_id, plan.tenant_id)
        link = await self.database.get(
            ConversationGuestSubmission, (plan.tenant_id, usage.submission_id)
        )
        if link is None or (
            link.recording_id,
            link.processing_lease_id,
            link.usage_id,
            link.source_sha256,
        ) != (plan.recording_id, lease.id, usage.id, usage.source_sha256):
            raise ConversationConflict("The processing source does not match its minute owner.")
        latest_plan = await self.database.scalar(
            select(ConversationProcessingPlan.id)
            .where(
                ConversationProcessingPlan.recording_id == plan.recording_id,
                ConversationProcessingPlan.erased_at.is_(None),
            )
            .order_by(
                ConversationProcessingPlan.created_at.desc(), ConversationProcessingPlan.id.desc()
            )
            .limit(1)
        )
        if latest_plan != plan.id:
            return False
        previous = await self.latest(usage.id)
        legacy = await self.database.get(ConversationAcquisitionSettlement, usage.id)
        if (previous is not None and previous.kind in {"released", "delivered"}) or (
            legacy is not None and legacy.kind == "completed"
        ):
            return False
        if previous is not None and previous.plan_id is not None and previous.plan_id != plan.id:
            return False
        await self._append(
            usage, previous, key=f"failed-plan:{plan.id}", kind="released", plan_id=plan.id
        )
        return True

    async def deliver(
        self, usage_id: UUID, draft: ConversationReportDraft, *, plan_id: UUID | None = None
    ) -> None:
        usage = await self._lock(usage_id, draft.tenant_id)
        link = await self.database.get(
            ConversationGuestSubmission, (draft.tenant_id, usage.submission_id)
        )
        if (
            link is None
            or link.recording_id != draft.recording_id
            or link.person_id != draft.person_id
            or link.usage_id != usage.id
            or link.source_sha256 != usage.source_sha256
            or draft.source_sha256 != usage.source_sha256
            or draft.erased_at is not None
            or draft.payload is None
            or draft.evidence_receipt is None
        ):
            raise ConversationConflict(
                "The delivered report does not match its minute reservation."
            )
        previous = await self.latest(usage.id)
        if previous is not None and previous.kind == "released":
            raise ConversationConflict("This failed analysis needs a new reserved retry.")
        if previous is not None and previous.kind == "delivered":
            return
        if previous is not None and previous.plan_id is not None and previous.plan_id != plan_id:
            raise ConversationConflict("This report belongs to an earlier analysis attempt.")
        await self._append(
            usage, previous, key="report-delivered", kind="delivered", plan_id=plan_id, draft=draft
        )
