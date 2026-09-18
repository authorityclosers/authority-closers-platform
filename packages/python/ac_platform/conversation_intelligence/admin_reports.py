"""Admin-only report reads over the retained, tenant-scoped conversation set."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import select

from ac_platform.kernel.authz import ActorContext

from .application import (
    ConversationApplication,
    ConversationNotFound,
    utc,
)
from .models import ConversationRun
from .report_store import ConversationReports
from .review_service import ConversationReviewService


class AdminConversationReports:
    """Read a verified report for an operations-admin recording.

    Report evidence is admitted through the same retention, ownership and
    durable-checkpoint checks as an assigned reviewer.  The extra tenant
    boundary is applied before that shared evidence path so an operations
    actor cannot use a run id to discover another tenant's recording.
    """

    def __init__(
        self,
        application: ConversationApplication,
        operations_tenant_id: UUID,
        *,
        recording_tenant_ids: tuple[UUID, ...] = (),
    ) -> None:
        self.application = application
        self.database = application.database
        self.operations_tenant_id = operations_tenant_id
        self.recording_tenant_ids = frozenset({operations_tenant_id, *recording_tenant_ids})

    async def get(self, actor: ActorContext, run_id: UUID) -> dict[str, Any]:
        review = ConversationReviewService(
            self.application,
            operations_tenant_id=self.operations_tenant_id,
        )
        now = await review._admin(actor)
        run = await self.database.scalar(
            select(ConversationRun)
            .where(
                ConversationRun.id == run_id,
                ConversationRun.tenant_id.in_(self.recording_tenant_ids),
            )
            .with_for_update(read=True)
            .execution_options(populate_existing=True)
        )
        if run is None:
            raise ConversationNotFound("Report not found.")

        evidence = await review._evidence(run_id, utc(now))
        report, _transcript = ConversationReports(review.application)._validated(
            evidence.draft, evidence.recording
        )
        await review._review_audit(
            actor,
            tenant_id=evidence.recording.tenant_id,
            action="admin_report_view",
            resource_type="conversation_report_draft",
            resource_id=evidence.draft.id,
            intent={
                "run_id": str(evidence.run.id),
                "recording_id": str(evidence.recording.id),
                "report_id": str(evidence.draft.id),
            },
            now=utc(now),
        )
        return {
            "id": str(evidence.draft.id),
            "run_id": str(evidence.run.id),
            "recording_id": str(evidence.recording.id),
            "tenant_id": str(evidence.recording.tenant_id),
            "source": {
                "sha256": evidence.recording.source_sha256,
                "revision": evidence.recording.source_revision,
                "retention_until": evidence.retention_until.isoformat(),
            },
            "report": report.model_dump(mode="json"),
            "message": "Private report loaded for authorized Admin review.",
        }
