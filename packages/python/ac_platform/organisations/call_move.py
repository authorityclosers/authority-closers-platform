"""Source-bound eligibility for an append-only Personal-call assignment.

This boundary grants no artifact access and performs no movement. The eventual
assignment command must resolve it again in its own per-call transaction, append
the reviewed mapping/audit, and fence the assignment head. Never rewrite source,
processing, usage, billing or credit lineage to satisfy a destination tenant.
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ac_platform.conversation_intelligence.acquisition_library import _account_library_query
from ac_platform.conversation_intelligence.acquisition_models import (
    ConversationAcquisitionUsage as Usage,
)
from ac_platform.conversation_intelligence.application import ConversationApplication
from ac_platform.conversation_intelligence.guest_models import ConversationGuestSubmission as Source
from ac_platform.conversation_intelligence.models import ConversationPermission as Permission
from ac_platform.conversation_intelligence.models import ConversationRecording as Recording
from ac_platform.kernel.authz import ActorContext
from ac_platform.kernel.errors import ResourceNotFound
from ac_platform.tenancy.models import Membership, Organisation, Tenant


@dataclass(frozen=True, slots=True)
class PersonalCallMoveCandidate:
    submission_id: UUID
    recording_id: UUID
    usage_id: UUID
    source_tenant_id: UUID
    processing_person_id: UUID
    owner_person_id: UUID
    destination_tenant_id: UUID
    source_sha256: str
    source_revision: int
    source_generation: int
    permission_id: UUID


async def personal_call_move_candidate(
    database: AsyncSession,
    actor: ActorContext,
    *,
    submission_id: UUID,
    destination_tenant_id: UUID,
    public_learner_tenant_id: UUID,
    operations_tenant_id: UUID,
    at: datetime | None = None,
) -> PersonalCallMoveCandidate:
    """Use the real Personal actor and the existing retained account-owner scope.

    Destination read locks and source read locks last for the caller's transaction.
    They are not transferable grants. An org owner/admin cannot nominate someone
    else's Personal call, and a processing principal is never treated as its owner.
    """
    if actor.tenant_id != public_learner_tenant_id or destination_tenant_id in {
        public_learner_tenant_id,
        operations_tenant_id,
    }:
        raise ResourceNotFound("Personal call or destination organisation is unavailable.")
    now = at or datetime.now(UTC)
    await ConversationApplication(database, clock=lambda: now).admit(
        actor, shared_identity_locks=True
    )
    destination = await database.scalar(
        select(Membership)
        .join(Organisation, Organisation.tenant_id == Membership.tenant_id)
        .join(Tenant, Tenant.id == Membership.tenant_id)
        .where(
            Membership.tenant_id == destination_tenant_id,
            Membership.person_id == actor.person_id,
            Membership.role.in_(("owner", "admin", "member")),
            Membership.status == "active",
            Membership.ended_at.is_(None),
            Tenant.status == "active",
        )
        .with_for_update(read=True, of=[Membership, Organisation, Tenant])
        .execution_options(populate_existing=True)
    )
    if destination is None:
        raise ResourceNotFound("Destination organisation is unavailable.")
    # Reuse the canonical owner/claim, source hash, consent, retention and canary
    # selectors. No fake actor, uploader impersonation or general cross-tenant grant.
    row = (
        await database.execute(
            _account_library_query(actor, now)
            .where(Usage.submission_id == submission_id)
            .with_only_columns(
                Usage.id,
                Source.recording_id,
                Source.person_id,
                Recording.source_sha256,
                Recording.source_revision,
                Recording.generation,
                Recording.permission_id,
                maintain_column_froms=True,
            )
            .with_for_update(read=True, of=[Usage, Source, Recording, Permission])
        )
    ).one_or_none()
    if row is None:
        raise ResourceNotFound("Personal call is unavailable.")
    usage_id, recording_id, processing_person_id, digest, revision, generation, permission_id = row
    return PersonalCallMoveCandidate(
        submission_id=submission_id,
        recording_id=recording_id,
        usage_id=usage_id,
        source_tenant_id=public_learner_tenant_id,
        processing_person_id=processing_person_id,
        owner_person_id=actor.person_id,
        destination_tenant_id=destination_tenant_id,
        source_sha256=digest,
        source_revision=revision,
        source_generation=generation,
        permission_id=permission_id,
    )
