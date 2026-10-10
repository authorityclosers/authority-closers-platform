"""Customer minutes follow report delivery, independently of provider receipts.

Usage rows serialize this append-only journal. A late worker cannot capture a
released reservation; an explicitly reserved successor can deliver exactly once.
The original acquisition settlements and provider budget records stay intact.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import exists, func, select
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

    async def bind_retry_plan(self, usage_id: UUID, plan: ConversationProcessingPlan) -> None:
        """Fence old workers to the fresh attempt in the preparation transaction."""
        usage = await self._lock(usage_id, plan.tenant_id)
        link = await self.database.get(
            ConversationGuestSubmission, (plan.tenant_id, usage.submission_id)
        )
        if link is None or (link.recording_id, link.processing_lease_id) != (
            plan.recording_id,
            plan.processing_lease_id,
        ):
            raise ConversationConflict("The retry plan does not match this source.")
        previous = await self.latest(usage.id)
        if previous is not None and previous.kind != "reserved":
            raise ConversationConflict("This retry has no minute reservation.")
        await self._append(
            usage, previous, key=f"retry-plan:{plan.id}", kind="reserved", plan_id=plan.id
        )

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

    async def release_expired_source(self, *, now: datetime | None = None) -> bool:
        """Release abandoned uploads/local work even if no plan was accepted."""
        from ac_platform.conversation_intelligence.source_run_budget import (
            expired_source_reservations,
        )

        now = now or await self.database.scalar(select(func.clock_timestamp()))
        assert now is not None
        usage = await self.database.scalar(
            expired_source_reservations(now)
            .with_for_update(of=ConversationAcquisitionUsage, skip_locked=True)
            .limit(1)
        )
        if usage is None:
            return False
        # Recheck under the same usage lock as delivery and renewed admission.
        # A committed successor plan must protect its own immutable budget.
        eligible = await self.database.scalar(
            expired_source_reservations(now).where(ConversationAcquisitionUsage.id == usage.id)
        )
        if eligible is None:
            return False
        previous = await self.latest(usage.id)
        await self._append(
            usage,
            previous,
            key=f"source-budget:{0 if previous is None else previous.revision}",
            kind="released",
        )
        return True

    async def release_failed_local(self) -> bool:
        """An exhausted local job releases minutes before the lease deadline."""
        from ac_platform.conversation_intelligence.application import LOCAL_JOB
        from ac_platform.conversation_intelligence.models import (
            ConversationRecording,
            ConversationRun,
        )
        from ac_platform.outbox.models import Job

        link = ConversationGuestSubmission
        latest_run = (
            select(ConversationRun.id)
            .join(Job, Job.id == ConversationRun.job_id)
            .where(ConversationRun.recording_id == link.recording_id, Job.kind == LOCAL_JOB)
            .order_by(
                ConversationRun.created_at.desc(), Job.created_at.desc(), ConversationRun.id.desc()
            )
            .limit(1)
            .correlate(link)
            .scalar_subquery()
        )
        latest_kind = (
            select(ConversationReportMinuteEvent.kind)
            .where(ConversationReportMinuteEvent.usage_id == ConversationAcquisitionUsage.id)
            .order_by(ConversationReportMinuteEvent.revision.desc())
            .limit(1)
            .correlate(ConversationAcquisitionUsage)
            .scalar_subquery()
        )
        eligible = (
            select(ConversationAcquisitionUsage, ConversationRun)
            .join(link, link.usage_id == ConversationAcquisitionUsage.id)
            .join(ConversationRecording, ConversationRecording.id == link.recording_id)
            .join(ConversationRun, ConversationRun.id == latest_run)
            .join(Job, Job.id == ConversationRun.job_id)
            .where(
                Job.status == "dead_letter",
                Job.lease_token.is_(None),
                ConversationRun.state.in_(("queued", "running", "failed")),
                ConversationRun.generation == ConversationRecording.generation,
                ConversationRecording.state == "ready",
                func.coalesce(latest_kind, "reserved") == "reserved",
                ~exists(
                    select(ConversationProcessingPlan.id).where(
                        ConversationProcessingPlan.recording_id == ConversationRun.recording_id,
                        ConversationProcessingPlan.state.in_(("quoted", "active")),
                        ConversationProcessingPlan.expires_at > func.clock_timestamp(),
                        ConversationProcessingPlan.erased_at.is_(None),
                    )
                ),
                ~exists(
                    select(ConversationAcquisitionSettlement.usage_id).where(
                        ConversationAcquisitionSettlement.usage_id
                        == ConversationAcquisitionUsage.id,
                        ConversationAcquisitionSettlement.kind == "completed",
                    )
                ),
            )
            .order_by(ConversationRun.created_at)
            .limit(1)
        )
        candidate = (
            await self.database.execute(
                eligible.with_for_update(
                    of=(ConversationAcquisitionUsage, ConversationRun, Job), skip_locked=True
                )
            )
        ).first()
        if candidate is None:
            return False
        usage, run = candidate
        # Re-evaluate the snapshot after taking the same usage lock as owner
        # retry admission; a just-committed successor must keep its reservation.
        current = await self.database.execute(
            eligible.where(
                ConversationAcquisitionUsage.id == usage.id, ConversationRun.id == run.id
            )
        )
        if current.first() is None:
            return False
        previous = await self.latest(usage.id)
        await self._append(usage, previous, key=f"failed-local:{run.id}", kind="released")
        run.state = "failed"
        run.completed_at = run.completed_at or await self.database.scalar(
            select(func.clock_timestamp())
        )
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
