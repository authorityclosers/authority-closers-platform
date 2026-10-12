"""Person-entered call outcomes: append-only, fenced, audited (AUT-1677).

A call's owner records won, lost (reason), follow-up (date) or no decision,
with an optional deal value. A prospect's deal stage is derived on read from
the latest outcome of its most recent linked call, so linking an older call,
unlinking or correcting an old call never leaves a wrong stage behind.

Each write names the outcome revision, the call's prospect link and the
prospect's stage revision (the number of outcome revisions on its linked
calls) it saw, so a moved link or a concurrent edit is a conflict, never a
silent overwrite. Repeating the current fact is a no-op. AI output never
reaches this module.
"""

from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import and_, case, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from ac_platform.audit.service import AuditRepository
from ac_platform.conversation_intelligence.acquisition_models import ConversationAcquisitionUsage
from ac_platform.conversation_intelligence.application import (
    ConversationConflict,
    ConversationDenied,
    ConversationError,
    ConversationNotFound,
    utc,
)
from ac_platform.conversation_intelligence.guest_ownership import SubmissionScope
from ac_platform.conversation_intelligence.prospect_call_outcome import (
    SCHEMA,
    DealValue,
    HumanOutcome,
    HumanOutcomeCommand,
)
from ac_platform.conversation_intelligence.prospect_call_outcome_models import (
    OUTCOME_STAGES,
    ConversationCallOutcomeRevision,
)
from ac_platform.conversation_intelligence.prospect_models import (
    ConversationProspect,
    ConversationProspectMembership,
)
from ac_platform.conversation_intelligence.prospect_store import ProspectStore
from ac_platform.kernel.authz import ActorContext

NOT_CALL_OWNER = "not_call_owner"


class NotCallOwner(ConversationError):
    """Only the call's owner records its outcome; others see nothing to record."""

    status = 403


def outcome_value(row: ConversationCallOutcomeRevision) -> HumanOutcome:
    return HumanOutcome(
        row.outcome,
        row.lost_reason,
        row.follow_up_on,
        DealValue(row.deal_amount, row.deal_currency)
        if row.deal_amount is not None and row.deal_currency is not None
        else None,
    )


def effective_stage(tenant_id: Any, prospect_id: Any) -> Any:
    """The latest outcome of the prospect's most recent linked call, as a stage label.

    Returns a SELECT of one labelled value; callers correlate or bind the ids.
    """
    outcome = aliased(ConversationCallOutcomeRevision)
    newer = aliased(ConversationCallOutcomeRevision)
    member, usage = ConversationProspectMembership, ConversationAcquisitionUsage
    latest_revision = (
        select(func.max(newer.revision))
        .where(newer.tenant_id == outcome.tenant_id, newer.submission_id == outcome.submission_id)
        .scalar_subquery()
    )
    return (
        select(case(OUTCOME_STAGES, value=outcome.outcome))
        .join(
            member,
            and_(
                member.tenant_id == outcome.tenant_id,
                member.submission_id == outcome.submission_id,
                member.ended_at.is_(None),
            ),
        )
        .join(
            usage,
            and_(
                usage.tenant_id == outcome.tenant_id,
                usage.submission_id == outcome.submission_id,
            ),
        )
        .where(
            member.tenant_id == tenant_id,
            member.prospect_id == prospect_id,
            outcome.revision == latest_revision,
        )
        .order_by(usage.created_at.desc(), outcome.created_at.desc())
        .limit(1)
    )


class CallOutcomeStore:
    def __init__(self, prospects: ProspectStore) -> None:
        self.prospects = prospects
        self.database: AsyncSession = prospects.database

    async def _scope(self, actor: ActorContext, submission_id: UUID, *, read_only: bool) -> Any:
        try:
            return await self.prospects._write_scope(actor, submission_id, read_only=read_only)
        except (ConversationDenied, ConversationNotFound):
            raise NotCallOwner(NOT_CALL_OWNER) from None

    async def _current(self, scope: SubmissionScope) -> ConversationCallOutcomeRevision | None:
        row: ConversationCallOutcomeRevision | None = await self.database.scalar(
            select(ConversationCallOutcomeRevision)
            .where(
                ConversationCallOutcomeRevision.tenant_id == scope.tenant_id,
                ConversationCallOutcomeRevision.submission_id == scope.submission_id,
            )
            .order_by(ConversationCallOutcomeRevision.revision.desc())
            .limit(1)
        )
        return row

    async def _stage_revision(self, tenant_id: UUID, prospect_id: UUID) -> int:
        """Outcome revisions on the prospect's linked calls: grows by one per save."""
        outcome, member = ConversationCallOutcomeRevision, ConversationProspectMembership
        value = await self.database.scalar(
            select(func.count())
            .select_from(outcome)
            .join(
                member,
                and_(
                    member.tenant_id == outcome.tenant_id,
                    member.submission_id == outcome.submission_id,
                    member.ended_at.is_(None),
                ),
            )
            .where(member.tenant_id == tenant_id, member.prospect_id == prospect_id)
        )
        return int(value or 0)

    async def _stage(self, tenant_id: UUID, prospect_id: UUID) -> str | None:
        stage: str | None = await self.database.scalar(effective_stage(tenant_id, prospect_id))
        return stage

    def _json(
        self,
        actor: ActorContext,
        scope: SubmissionScope,
        current: ConversationCallOutcomeRevision | None,
        member: ConversationProspectMembership | None,
        stage_revision: int | None,
    ) -> dict[str, Any]:
        return {
            "schema": SCHEMA,
            "submission_id": str(scope.submission_id),
            "person_id": str(actor.person_id),
            "tenant_id": str(scope.tenant_id),
            "session_id": str(actor.session_id),
            "revision": current.revision if current else 0,
            "value": outcome_value(current).json() if current else None,
            "basis": "person" if current else None,
            "locked": current is not None,
            "set_by_person_id": str(current.set_by_person_id) if current else None,
            "set_at": utc(current.created_at).isoformat() if current else None,
            "prospect_binding": (
                {
                    "prospect_id": str(member.prospect_id),
                    "membership_id": str(member.id),
                    "stage_revision": stage_revision or 0,
                }
                if member is not None
                else None
            ),
            # Only the owner reaches this point; everyone else gets NotCallOwner.
            "can_edit": True,
        }

    async def read(self, actor: ActorContext, submission_id: UUID) -> dict[str, Any]:
        scope = await self._scope(actor, submission_id, read_only=True)
        current = await self._current(scope)
        member = await self.prospects._active(scope)
        stage = (
            await self._stage_revision(scope.tenant_id, member.prospect_id)
            if member is not None
            else None
        )
        return self._json(actor, scope, current, member, stage)

    async def save(
        self, actor: ActorContext, submission_id: UUID, command: HumanOutcomeCommand
    ) -> dict[str, Any]:
        # The write scope locks the recording, serialising writers for this call.
        scope = await self._scope(actor, submission_id, read_only=False)
        current = await self._current(scope)
        member = await self.prospects._active(scope)
        if (current.revision if current else 0) != command.expected_revision or (
            (member.id if member else None) != command.expected_membership_id
        ):
            raise ConversationConflict("This call's outcome changed. Reload before saving again.")
        stage_revision: int | None = None
        before: str | None = None
        if member is not None:
            # Lock the prospect so concurrent saves on its calls are ordered.
            locked = await self.database.scalar(
                select(ConversationProspect.id)
                .where(
                    ConversationProspect.tenant_id == scope.tenant_id,
                    ConversationProspect.id == member.prospect_id,
                )
                .with_for_update()
            )
            if locked is None:
                raise ConversationNotFound("This prospect is unavailable.")
            stage_revision = await self._stage_revision(scope.tenant_id, member.prospect_id)
            if stage_revision != command.expected_prospect_stage_revision:
                raise ConversationConflict(
                    "This prospect's calls changed. Reload before saving again."
                )
            before = await self._stage(scope.tenant_id, member.prospect_id)
        if current is not None and outcome_value(current) == command.value:
            return self._json(actor, scope, current, member, stage_revision)
        now = utc(self.prospects.ownership.clock())
        value = command.value
        row = ConversationCallOutcomeRevision(
            id=uuid4(),
            tenant_id=scope.tenant_id,
            submission_id=scope.submission_id,
            revision=(current.revision if current else 0) + 1,
            outcome=value.outcome,
            lost_reason=value.lost_reason,
            follow_up_on=value.follow_up_on,
            deal_amount=value.deal_value.amount if value.deal_value else None,
            deal_currency=value.deal_value.currency_code if value.deal_value else None,
            set_by_person_id=actor.person_id,
            prospect_id=member.prospect_id if member else None,
            created_at=now,
        )
        self.database.add(row)
        await self.database.flush()
        audit = AuditRepository(self.database)
        await audit.append(
            tenant_id=scope.tenant_id,
            actor_person_id=actor.person_id,
            session_id=actor.session_id,
            action="conversation.call_outcome_set",
            resource_type="conversation_submission",
            resource_id=scope.submission_id,
            payload={
                "outcome": value.outcome,
                "revision": str(row.revision),
                "previous_revision": str(current.revision if current else 0),
                "has_deal_value": str(value.deal_value is not None).lower(),
            },
            now=now,
        )
        if member is not None:
            stage_revision = (stage_revision or 0) + 1
            after = await self._stage(scope.tenant_id, member.prospect_id)
            if after != before:
                await audit.append(
                    tenant_id=scope.tenant_id,
                    actor_person_id=actor.person_id,
                    session_id=actor.session_id,
                    action="conversation.prospect_stage_changed",
                    resource_type="conversation_prospect",
                    resource_id=member.prospect_id,
                    payload={
                        "stage": after or "",
                        "previous_stage": before or "",
                        "submission_id": str(scope.submission_id),
                    },
                    now=now,
                )
        return self._json(actor, scope, row, member, stage_revision)
