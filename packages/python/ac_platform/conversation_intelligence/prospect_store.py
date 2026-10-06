"""Explicit prospect storage; callers own the transaction, HTTP writes live elsewhere."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import Select, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ac_platform.audit.service import AuditRepository
from ac_platform.conversation_intelligence.acquisition_library import _account_library_query
from ac_platform.conversation_intelligence.acquisition_models import ConversationAcquisitionUsage
from ac_platform.conversation_intelligence.application import (
    ConversationConflict,
    ConversationDenied,
    ConversationError,
    ConversationNotFound,
    utc,
)
from ac_platform.conversation_intelligence.guest_models import ConversationGuestSubmission
from ac_platform.conversation_intelligence.guest_ownership import GuestOwnership, SubmissionScope
from ac_platform.conversation_intelligence.models import ConversationRecording
from ac_platform.conversation_intelligence.prospect_models import (
    ConversationProspect,
    ConversationProspectMembership,
)
from ac_platform.kernel.authz import ActorContext


@dataclass(frozen=True)
class ProspectQueries:
    """Authorized SQL building blocks for bounded API pages/aggregates.

    Aggregate only ``memberships``. It contains active links to retained Calls
    visible to this reader. ``prospects`` also includes creator/owner name-only
    rows. Neither query grants access to audio, reports or mutation.
    """

    prospects: Select[tuple[ConversationProspect]]
    memberships: Select[tuple[ConversationProspectMembership]]


class ProspectStore:
    def __init__(self, ownership: GuestOwnership) -> None:
        self.ownership = ownership
        self.database: AsyncSession = ownership.database

    async def queries(self, actor: ActorContext) -> ProspectQueries:
        now = await self.ownership.sessions._admit()
        await self.ownership.sessions._owner(None, actor, now, shared_identity_locks=True)
        if actor.tenant_id != self.ownership.tenant_id:
            raise ConversationDenied("Select the same workspace as this prospect library.")
        every_owner = await self.ownership.organisation_call_reader(actor)
        usage, member, prospect = (
            ConversationAcquisitionUsage,
            ConversationProspectMembership,
            ConversationProspect,
        )
        visible_calls = _account_library_query(
            actor, now, every_owner=every_owner
        ).with_only_columns(usage.submission_id)
        memberships = select(member).where(
            member.tenant_id == actor.tenant_id,
            member.ended_at.is_(None),
            member.submission_id.in_(visible_calls),
        )
        prospects = select(prospect).where(
            prospect.tenant_id == actor.tenant_id,
            or_(
                prospect.created_by_person_id == actor.person_id,
                prospect.owner_person_id == actor.person_id,
                prospect.id.in_(memberships.with_only_columns(member.prospect_id)),
            ),
        )
        return ProspectQueries(prospects, memberships)

    async def read(self, actor: ActorContext, prospect_id: UUID) -> ConversationProspect:
        query = (await self.queries(actor)).prospects
        row = await self.database.scalar(query.where(ConversationProspect.id == prospect_id))
        if row is None:
            raise ConversationNotFound("This prospect is unavailable.")
        return row

    async def read_memberships(
        self, actor: ActorContext, prospect_id: UUID, *, limit: int = 100
    ) -> Sequence[ConversationProspectMembership]:
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ConversationError("Read between 1 and 100 call memberships.")
        query = (await self.queries(actor)).memberships
        member = ConversationProspectMembership
        return (
            await self.database.scalars(
                query.where(member.prospect_id == prospect_id)
                .order_by(member.created_at.desc(), member.id.desc())
                .limit(limit)
            )
        ).all()

    async def _write_scope(
        self, actor: ActorContext, submission_id: UUID, *, read_only: bool = False
    ) -> SubmissionScope:
        scope = await self.ownership.require_submission_owner(
            submission_id, actor=actor, shared_identity_locks=True
        )
        if not scope.claimed_account or scope.tenant_id != actor.tenant_id:
            raise ConversationDenied("Claim this call before linking a prospect.")
        recording = await self.database.scalar(
            select(ConversationRecording)
            .where(
                ConversationRecording.id == scope.recording_id,
                ConversationRecording.tenant_id == scope.tenant_id,
            )
            .with_for_update(read=read_only)
            .execution_options(populate_existing=True)
        )
        if recording is None or recording.state not in ("awaiting_upload", "ready"):
            raise ConversationNotFound("This call is unavailable.")
        # Recheck source retention/ownership after the erasure fence is acquired.
        if (
            await self.ownership.require_submission_owner(
                submission_id, actor=actor, shared_identity_locks=True
            )
            != scope
            or await self.database.scalar(
                _account_library_query(actor, utc(self.ownership.clock())).where(
                    ConversationAcquisitionUsage.submission_id == submission_id
                )
            )
            is None
        ):
            raise ConversationNotFound("This call is unavailable.")
        return scope

    async def _active(self, scope: SubmissionScope) -> ConversationProspectMembership | None:
        member = ConversationProspectMembership
        row: ConversationProspectMembership | None = await self.database.scalar(
            select(member).where(
                member.tenant_id == scope.tenant_id,
                member.submission_id == scope.submission_id,
                member.ended_at.is_(None),
            )
        )
        return row

    async def create_from_call(
        self, actor: ActorContext, submission_id: UUID, *, display_name: str
    ) -> ConversationProspect:
        """Create a new stable ID only on an explicit person's command; no name lookup."""
        if not isinstance(display_name, str) or not 1 <= len(display_name.strip()) <= 160:
            raise ConversationError("Enter a prospect name of at most 160 characters.")
        scope = await self._write_scope(actor, submission_id)
        if await self._active(scope) is not None:
            raise ConversationConflict(
                "This call already has a prospect. Confirm a new link first."
            )
        now = utc(self.ownership.clock())
        prospect = ConversationProspect(
            id=uuid4(),
            tenant_id=scope.tenant_id,
            display_name=display_name.strip(),
            created_by_person_id=actor.person_id,
            owner_person_id=actor.person_id,
            created_at=now,
            updated_at=now,
            revision=1,
        )
        self.database.add(prospect)
        await self.database.flush()
        await self._audit(actor, prospect.id, "created", {}, now)
        await self._append(actor, scope, prospect.id, now)
        return prospect

    async def confirm_link(
        self,
        actor: ActorContext,
        submission_id: UUID,
        prospect_id: UUID,
        *,
        expected_membership_id: UUID | None,
    ) -> ConversationProspectMembership:
        scope = await self._write_scope(actor, submission_id)
        prospect = await self.read(actor, prospect_id)
        if prospect.owner_person_id != actor.person_id:
            raise ConversationNotFound("This prospect is unavailable.")
        current = await self._active(scope)
        if current is not None and current.prospect_id == prospect_id:
            return current
        if (None if current is None else current.id) != expected_membership_id:
            raise ConversationConflict("The call link changed. Reload before confirming.")
        now = utc(self.ownership.clock())
        if current is not None:
            await self._end(current, "superseded", now, actor)
        return await self._append(actor, scope, prospect_id, now)

    async def unlink(
        self, actor: ActorContext, submission_id: UUID, *, expected_membership_id: UUID
    ) -> None:
        scope = await self._write_scope(actor, submission_id)
        current = await self._active(scope)
        if current is None or current.id != expected_membership_id:
            raise ConversationConflict("The call link changed. Reload before unlinking.")
        await self._end(current, "unlinked", utc(self.ownership.clock()), actor)

    async def _append(
        self, actor: ActorContext, scope: SubmissionScope, prospect_id: UUID, now: datetime
    ) -> ConversationProspectMembership:
        row = ConversationProspectMembership(
            id=uuid4(),
            tenant_id=scope.tenant_id,
            prospect_id=prospect_id,
            submission_id=scope.submission_id,
            linked_by_person_id=actor.person_id,
            created_at=now,
        )
        self.database.add(row)
        await self.database.flush()
        await self._audit(
            actor,
            prospect_id,
            "call_linked",
            {"membership_id": str(row.id), "submission_id": str(scope.submission_id)},
            now,
        )
        return row

    async def _end(
        self, row: ConversationProspectMembership, reason: str, now: datetime, actor: ActorContext
    ) -> None:
        await end_membership(self.database, row, reason, now, actor)

    async def _audit(
        self,
        actor: ActorContext,
        prospect_id: UUID,
        action: str,
        payload: dict[str, str],
        now: datetime,
    ) -> None:
        await AuditRepository(self.database).append(
            tenant_id=self.ownership.tenant_id,
            actor_person_id=actor.person_id,
            session_id=actor.session_id,
            action=f"conversation.prospect_{action}",
            resource_type="conversation_prospect",
            resource_id=prospect_id,
            payload=payload,
            now=now,
        )


async def end_membership(
    database: AsyncSession,
    row: ConversationProspectMembership,
    reason: str,
    now: datetime,
    actor: ActorContext | None = None,
) -> None:
    row.ended_at, row.ended_reason = now, reason
    row.ended_by_person_id = None if actor is None else actor.person_id
    await database.flush()
    await AuditRepository(database).append(
        tenant_id=row.tenant_id,
        actor_person_id=None if actor is None else actor.person_id,
        actor_type="system" if actor is None else "person",
        session_id=None if actor is None else actor.session_id,
        action="conversation.prospect_call_ended",
        resource_type="conversation_prospect",
        resource_id=row.prospect_id,
        payload={
            "membership_id": str(row.id),
            "submission_id": str(row.submission_id),
            "reason": reason,
        },
        now=now,
    )


async def end_prospect_memberships_for_recording(
    database: AsyncSession, *, tenant_id: UUID, recording_id: UUID, now: datetime
) -> None:
    """Called under the canonical recording erasure lock; keeps non-content history."""
    submission_ids = select(ConversationGuestSubmission.submission_id).where(
        ConversationGuestSubmission.tenant_id == tenant_id,
        ConversationGuestSubmission.recording_id == recording_id,
    )
    member = ConversationProspectMembership
    rows = (
        await database.scalars(
            select(member)
            .where(
                member.tenant_id == tenant_id,
                member.submission_id.in_(submission_ids),
                member.ended_at.is_(None),
            )
            .order_by(member.id)
        )
    ).all()
    for row in rows:
        await end_membership(database, row, "source_erasure", now)
