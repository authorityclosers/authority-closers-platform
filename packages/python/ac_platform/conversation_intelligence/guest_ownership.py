"""Caller-transaction guest ownership and explicit non-login processing authority.

The processing identity owns canonical worker rows, not the customer's account.
Immutable submission links resolve the actual visitor/account owner. Leases
never create browser credentials, verification assertions, consent or quota.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ac_platform.audit.service import AuditRepository
from ac_platform.conversation_intelligence.acquisition_models import (
    ConversationAcquisitionSettlement,
    ConversationAcquisitionUsage,
    ConversationVisitor,
    ConversationVisitorClaim,
)
from ac_platform.conversation_intelligence.acquisition_sessions import AcquisitionSessions
from ac_platform.conversation_intelligence.application import (
    ConversationApplication,
    ConversationConflict,
    ConversationDenied,
    ConversationError,
    ConversationNotFound,
    utc,
)
from ac_platform.conversation_intelligence.entitlements import MinuteAccount
from ac_platform.conversation_intelligence.guest_models import (
    ConversationGuestSubmission,
    ConversationProcessingLease,
    ConversationProcessingPrincipal,
)
from ac_platform.conversation_intelligence.models import (
    ConversationMinuteAccount,
    ConversationPermission,
    ConversationRecording,
)
from ac_platform.conversation_intelligence.processing_actor import ProcessingActor
from ac_platform.identity.models import PasswordCredential, Person, ProviderIdentity
from ac_platform.identity.models import Session as IdentitySession
from ac_platform.kernel.authz import ActorContext
from ac_platform.tenancy.models import Membership


@dataclass(frozen=True, slots=True)
class SubmissionScope:
    tenant_id: UUID
    submission_id: UUID
    recording_id: UUID
    processing_person_id: UUID
    processing_lease_id: UUID
    usage_id: UUID
    source_sha256: str
    claimed_account: bool


class GuestOwnership:
    def __init__(self, sessions: AcquisitionSessions) -> None:
        self.sessions, self.database = sessions, sessions.database
        self.tenant_id, self.clock = sessions.tenant_id, sessions.clock

    async def provision(self, *, operator_reference: str, reason: str) -> UUID:
        """Operator-only composition command; never mount on an anonymous route."""
        if (
            not isinstance(operator_reference, str)
            or re.fullmatch(r"[A-Za-z0-9_.:/-]{6,160}", operator_reference) is None
            or not isinstance(reason, str)
            or not 1 <= len(reason.strip()) <= 500
        ):
            raise ConversationError("An attributable non-secret operator intent is required.")
        now = await self.sessions._admit(mutation=True)
        existing = await self.database.scalar(
            select(ConversationProcessingPrincipal)
            .where(ConversationProcessingPrincipal.tenant_id == self.tenant_id)
            .execution_options(populate_existing=True)
        )
        if existing is not None:
            if existing.revoked_at is not None:
                raise ConversationDenied("This processing principal has been revoked.")
            ledger = await self.database.get(
                ConversationMinuteAccount, (existing.tenant_id, existing.person_id)
            )
            if ledger is None:
                raise ConversationDenied(
                    "The processing ledger needs its complete restore history."
                )
            return existing.id
        person_id, principal_id = uuid4(), uuid4()
        self.database.add(
            Person(id=person_id, display_name="Sales Xray processing", status="active")
        )
        await self.database.flush()
        # This role is deliberately absent from MembershipRole and supported
        # human tenant-context roles. It grants no learner/admin permissions.
        self.database.add(
            Membership(
                tenant_id=self.tenant_id, person_id=person_id, role="processing", status="active"
            )
        )
        await self.database.flush()
        self.database.add(
            ConversationProcessingPrincipal(
                id=principal_id,
                tenant_id=self.tenant_id,
                person_id=person_id,
                operator_reference=operator_reference,
                created_at=now,
            )
        )
        # An empty canonical ledger permits zero-entitlement local processing.
        # Provisioning grants no minutes or provider budget; guest source usage
        # remains in the acquisition ledger and hosted approval remains separate.
        self.database.add(
            ConversationMinuteAccount(
                tenant_id=self.tenant_id,
                person_id=person_id,
                snapshot=MinuteAccount(str(self.tenant_id), str(person_id)).as_dict(),
                revision=1,
            )
        )
        await self.database.flush()
        await AuditRepository(self.database).append(
            tenant_id=self.tenant_id,
            actor_person_id=None,
            actor_type="operator",
            action="conversation.processing_principal_created",
            resource_type="conversation_processing_principal",
            resource_id=principal_id,
            payload={
                "operator_reference": operator_reference,
                "processing_person_id": str(person_id),
            },
            reason=reason,
            now=now,
        )
        return principal_id

    async def _owned_usage(
        self, submission_id: UUID, *, token: str | None, actor: ActorContext | None, mutation: bool
    ) -> tuple[ConversationAcquisitionUsage, datetime, bool]:
        if actor is not None:
            await ConversationApplication(self.database, clock=self.clock).admit(actor)
        now = await self.sessions._admit(mutation=mutation)
        visitor_id, person_id = await self.sessions._owner(token, actor, now)
        usage = await self.database.scalar(
            select(ConversationAcquisitionUsage).where(
                ConversationAcquisitionUsage.tenant_id == self.tenant_id,
                ConversationAcquisitionUsage.submission_id == submission_id,
            )
        )
        if usage is None:
            raise ConversationNotFound("This upload is unavailable.")
        owner_matches = (usage.visitor_id, usage.person_id) == (visitor_id, person_id)
        if not owner_matches and person_id is not None and usage.visitor_id is not None:
            claim = await self.database.get(ConversationVisitorClaim, usage.visitor_id)
            owner_matches = claim is not None and claim.person_id == person_id
        if not owner_matches:
            raise ConversationNotFound("This upload is unavailable.")
        return usage, now, person_id is not None

    async def resolve_processing_actor(
        self,
        submission_id: UUID,
        *,
        token: str | None = None,
        actor: ActorContext | None = None,
        lifetime: timedelta = timedelta(hours=1),
    ) -> ProcessingActor:
        if not timedelta(minutes=5) <= lifetime <= timedelta(days=7):
            raise ConversationError("A bounded processing lease is required.")
        usage, now, claimed = await self._owned_usage(
            submission_id, token=token, actor=actor, mutation=True
        )
        principal = await self.database.scalar(
            select(ConversationProcessingPrincipal).where(
                ConversationProcessingPrincipal.tenant_id == self.tenant_id,
                ConversationProcessingPrincipal.revoked_at.is_(None),
            )
        )
        if principal is None:
            raise ConversationDenied("This workspace has no processing principal.")
        lease = await self.database.scalar(
            select(ConversationProcessingLease).where(
                ConversationProcessingLease.usage_id == usage.id
            )
        )
        if lease is None:
            expires = now + lifetime
            if usage.visitor_id is not None and not claimed:
                visitor = await self.database.get(ConversationVisitor, usage.visitor_id)
                if visitor is None:
                    raise ConversationDenied("This upload session is unavailable.")
                expires = min(expires, utc(visitor.expires_at))
            lease = ConversationProcessingLease(
                id=uuid4(),
                principal_id=principal.id,
                tenant_id=self.tenant_id,
                person_id=principal.person_id,
                usage_id=usage.id,
                created_at=now,
                expires_at=expires,
            )
            self.database.add(lease)
            await self.database.flush()
            await AuditRepository(self.database).append(
                tenant_id=self.tenant_id,
                actor_person_id=None,
                actor_type="system",
                action="conversation.processing_lease_issued",
                resource_type="conversation_processing_lease",
                resource_id=lease.id,
                payload={"usage_id": str(usage.id), "submission_id": str(submission_id)},
                now=now,
            )
        resolved = ProcessingActor(principal.person_id, self.tenant_id, lease.id)
        await admit_processing_actor(self.database, resolved, now)
        return resolved

    async def require_submission_owner(
        self, submission_id: UUID, *, token: str | None = None, actor: ActorContext | None = None
    ) -> SubmissionScope:
        usage, now, claimed = await self._owned_usage(
            submission_id, token=token, actor=actor, mutation=False
        )
        if usage.visitor_id is not None:
            await self.sessions.fence_visitor(usage.visitor_id, shared=True)
            usage, now, claimed = await self._owned_usage(
                submission_id, token=token, actor=actor, mutation=False
            )
        link = await self.database.get(ConversationGuestSubmission, (self.tenant_id, submission_id))
        if link is None or link.usage_id != usage.id or link.source_sha256 != usage.source_sha256:
            raise ConversationNotFound("This upload is unavailable.")
        recording = await self.database.get(ConversationRecording, link.recording_id)
        permission = (
            None
            if recording is None
            else await self.database.get(ConversationPermission, recording.permission_id)
        )
        if (
            recording is None
            or recording.state in {"deleted", "deleting"}
            or (recording.tenant_id, recording.person_id, recording.source_sha256)
            != (link.tenant_id, link.person_id, link.source_sha256)
            or permission is None
            or permission.revoked_at is not None
            or utc(permission.retention_until) <= now
        ):
            raise ConversationNotFound("This upload is unavailable.")
        # Reading owned, retained results does not renew an expired execution
        # lease or permit another paid request. No full account token is issued.
        return SubmissionScope(
            link.tenant_id,
            link.submission_id,
            link.recording_id,
            link.person_id,
            link.processing_lease_id,
            usage.id,
            link.source_sha256,
            claimed,
        )

    async def request_deletion(
        self,
        submission_id: UUID,
        *,
        token: str | None = None,
        actor: ActorContext | None = None,
        key: str,
    ) -> dict[str, Any]:
        usage, now, _ = await self._owned_usage(
            submission_id, token=token, actor=actor, mutation=False
        )
        if usage.visitor_id is not None:
            await self.sessions.fence_visitor(usage.visitor_id, shared=False)
            usage, now, _ = await self._owned_usage(
                submission_id, token=token, actor=actor, mutation=False
            )
        link = await self.database.get(ConversationGuestSubmission, (self.tenant_id, submission_id))
        if link is None or link.usage_id != usage.id or link.source_sha256 != usage.source_sha256:
            raise ConversationNotFound("This upload is unavailable.")
        recording = await self.database.scalar(
            select(ConversationRecording)
            .where(
                ConversationRecording.id == link.recording_id,
                ConversationRecording.tenant_id == self.tenant_id,
                ConversationRecording.person_id == link.person_id,
                ConversationRecording.source_sha256 == link.source_sha256,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if recording is None:
            raise ConversationNotFound("This upload is unavailable.")
        # This reference scopes audit/idempotency only. Owner-authorized deletion
        # never renews or admits an expired execution lease and ignores expired
        # processing permission, so customers can still erase retained audio.
        processing_actor = ProcessingActor(link.person_id, self.tenant_id, link.processing_lease_id)
        previous_state = recording.state
        result = await ConversationApplication(
            self.database, clock=self.clock
        )._request_owned_deletion(processing_actor, recording, key=key, now=now)
        if previous_state not in {"deleting", "deleted"}:
            await AuditRepository(self.database).append(
                tenant_id=self.tenant_id,
                actor_person_id=actor.person_id if actor is not None else None,
                actor_type="person" if actor is not None else "guest",
                action="conversation.owner_deletion_requested",
                resource_type="conversation_recording",
                resource_id=recording.id,
                payload={
                    "submission_id": str(submission_id),
                    "usage_id": str(usage.id),
                    "visitor_id": str(usage.visitor_id) if usage.visitor_id is not None else None,
                },
                now=now,
            )
        return result


async def admit_processing_actor(
    database: AsyncSession, actor: ProcessingActor, now: datetime
) -> ConversationAcquisitionUsage:
    sessions = AcquisitionSessions(
        database, tenant_id=actor.tenant_id, policy_revision="processing-lease-v1"
    )
    await sessions._admit()
    if database.get_bind().dialect.name != "postgresql":
        raise ConversationError("Processing leases require PostgreSQL.")
    # Only this source serializes while its worker runs. A long provider call
    # must not hold the tenant acquisition lock or block every visitor's upload.
    lock = int.from_bytes(
        hashlib.sha256(b"processing:" + actor.processing_lease_id.bytes).digest()[:8],
        "big",
        signed=True,
    )
    await database.execute(select(func.pg_advisory_xact_lock(lock)))
    lease = await database.scalar(
        select(ConversationProcessingLease)
        .where(
            ConversationProcessingLease.id == actor.processing_lease_id,
            ConversationProcessingLease.tenant_id == actor.tenant_id,
            ConversationProcessingLease.person_id == actor.person_id,
        )
        .with_for_update(read=True)
        .execution_options(populate_existing=True)
    )
    principal = (
        None
        if lease is None
        else await database.get(
            ConversationProcessingPrincipal, lease.principal_id, populate_existing=True
        )
    )
    person = await database.scalar(
        select(Person)
        .where(Person.id == actor.person_id)
        .with_for_update(read=True)
        .execution_options(populate_existing=True)
    )
    member = await database.get(
        Membership, (actor.tenant_id, actor.person_id), populate_existing=True
    )
    if (
        lease is None
        or lease.revoked_at is not None
        or utc(lease.expires_at) <= now
        or principal is None
        or principal.revoked_at is not None
        or (principal.tenant_id, principal.person_id) != (actor.tenant_id, actor.person_id)
        or person is None
        or person.status != "active"
        or person.email is not None
        or person.email_verified_at is not None
        or member is None
        or member.role != "processing"
        or member.status != "active"
        or member.ended_at is not None
    ):
        raise ConversationDenied("A current non-login processing lease is required.")
    for model in (PasswordCredential, ProviderIdentity, IdentitySession):
        if (
            await database.scalar(
                select(model.person_id).where(model.person_id == actor.person_id).limit(1)
            )
            is not None
        ):
            raise ConversationDenied("Processing identities cannot hold login credentials.")
    usage = await database.get(ConversationAcquisitionUsage, lease.usage_id)
    settlement = await database.get(ConversationAcquisitionSettlement, lease.usage_id)
    if (
        usage is None
        or usage.tenant_id != actor.tenant_id
        or (settlement is not None and settlement.kind == "no_work_performed")
    ):
        raise ConversationDenied("A reserved source is required for processing.")
    if usage.visitor_id is not None:
        visitor = await database.get(ConversationVisitor, usage.visitor_id, populate_existing=True)
        if visitor is None or visitor.revoked_at is not None:
            raise ConversationDenied("This upload session has been revoked.")
        claim = await database.get(ConversationVisitorClaim, usage.visitor_id)
        owner_id = claim.person_id if claim is not None else None
        if claim is None and utc(visitor.expires_at) <= now:
            raise ConversationDenied("This upload session has expired.")
    else:
        owner_id = usage.person_id
    if owner_id is not None:
        # Do not take a human Person lock while holding the acquisition lock:
        # account requests acquire those in the opposite order. Read current
        # account state, without requiring a browser session for queued work.
        owner = await database.get(Person, owner_id, populate_existing=True)
        owner_member = await database.get(
            Membership, (actor.tenant_id, owner_id), populate_existing=True
        )
        if (
            owner is None
            or owner.status != "active"
            or owner_member is None
            or owner_member.status != "active"
            or owner_member.ended_at is not None
            or owner_member.role == "processing"
        ):
            raise ConversationDenied("The upload owner's account is unavailable.")
    return usage


async def link_registered_recording(
    database: AsyncSession, actor: ProcessingActor, recording: ConversationRecording, now: datetime
) -> None:
    usage = await admit_processing_actor(database, actor, now)
    if (recording.tenant_id, recording.person_id) != (
        actor.tenant_id,
        actor.person_id,
    ) or recording.source_sha256 != usage.source_sha256:
        raise ConversationDenied("The recording differs from its reserved source.")
    previous = await database.get(
        ConversationGuestSubmission, (actor.tenant_id, usage.submission_id)
    )
    if previous is not None:
        if (
            previous.recording_id != recording.id
            or previous.processing_lease_id != actor.processing_lease_id
        ):
            raise ConversationConflict("This upload already owns a different recording.")
        return
    database.add(
        ConversationGuestSubmission(
            tenant_id=actor.tenant_id,
            submission_id=usage.submission_id,
            person_id=actor.person_id,
            recording_id=recording.id,
            processing_lease_id=actor.processing_lease_id,
            usage_id=usage.id,
            source_sha256=usage.source_sha256,
            created_at=now,
        )
    )
    await database.flush()


async def admit_processing_recording(
    database: AsyncSession, tenant_id: UUID, recording_id: UUID, now: datetime
) -> ConversationAcquisitionUsage | None:
    """Worker admission before taking service-person/recording row locks."""
    link = await database.scalar(
        select(ConversationGuestSubmission).where(
            ConversationGuestSubmission.tenant_id == tenant_id,
            ConversationGuestSubmission.recording_id == recording_id,
        )
    )
    if link is None:
        return None
    actor = ProcessingActor(link.person_id, tenant_id, link.processing_lease_id)
    usage = await admit_processing_actor(database, actor, now)
    if usage.id != link.usage_id or usage.source_sha256 != link.source_sha256:
        raise ConversationDenied("The processing source differs from its ownership link.")
    return usage
