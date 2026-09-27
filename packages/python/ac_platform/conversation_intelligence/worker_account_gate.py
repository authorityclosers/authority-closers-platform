"""Account-profile admission and durable worker holds for Sales Xray jobs."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ac_platform.audit.service import AuditRepository
from ac_platform.conversation_intelligence.acquisition_models import (
    ConversationAcquisitionUsage,
    ConversationVisitorClaim,
)
from ac_platform.conversation_intelligence.models import ConversationRecording
from ac_platform.outbox.models import Job, JobStatus, RecoveryStatus
from ac_platform.outbox.repository import RecoveryStateRepository

ACCOUNT_REQUIRED_HOLD_REASON = "sales_xray_account_required"
PROFILE_INCOMPLETE_HOLD_REASON = "sales_xray_profile_incomplete"
ACCOUNT_PROFILE_HOLD_REASONS = frozenset(
    {ACCOUNT_REQUIRED_HOLD_REASON, PROFILE_INCOMPLETE_HOLD_REASON}
)


class AccountProfileRequired(Exception):
    """The source owner must complete authenticated Sales Xray onboarding."""

    def __init__(self, hold_reason: str, *, dispatch_started: bool = False) -> None:
        if hold_reason not in ACCOUNT_PROFILE_HOLD_REASONS:
            raise ValueError("unsupported Sales Xray account-profile hold reason")
        self.hold_reason = hold_reason
        self.dispatch_started = dispatch_started
        super().__init__(hold_reason)


async def _customer_person_id(
    session: AsyncSession,
    recording: ConversationRecording,
    *,
    now: datetime,
) -> UUID | None:
    """Resolve the actual upload owner, never the processing service identity."""

    from ac_platform.conversation_intelligence.guest_ownership import admit_processing_recording

    usage: ConversationAcquisitionUsage | None = await admit_processing_recording(
        session,
        recording.tenant_id,
        recording.id,
        now,
    )
    if usage is None:
        return recording.person_id
    if usage.visitor_id is None:
        return usage.person_id
    claim = await session.get(
        ConversationVisitorClaim,
        usage.visitor_id,
        populate_existing=True,
    )
    return None if claim is None else claim.person_id


async def require_recording_owner_profile(
    session: AsyncSession,
    recording: ConversationRecording,
    *,
    now: datetime,
) -> None:
    """Require a current complete canonical profile for this recording owner."""

    person_id = await _customer_person_id(session, recording, now=now)
    await require_person_profile(session, person_id=person_id)


async def require_person_profile(
    session: AsyncSession,
    *,
    person_id: UUID | None,
) -> None:
    """Check a resolved canonical person without substituting a service actor."""

    if person_id is None:
        raise AccountProfileRequired(ACCOUNT_REQUIRED_HOLD_REASON)
    try:
        from ac_platform.identity.models import Person
        from ac_platform.identity.sales_xray_profile import (
            SalesXrayProfileUnavailable,
            get_sales_xray_profile,
        )
        from ac_platform.identity.sales_xray_profile_models import SalesXrayProfile
    except ImportError as error:  # pragma: no cover - release wiring guard
        raise RuntimeError("Sales Xray profile service is not installed") from error

    # The profile service update locks the same canonical Person row FOR
    # UPDATE. Take a fresh shared lock on both inputs before its reads: this
    # refreshes any identity-map values and serializes profile changes through
    # provider execution transactions that remain open around the effect.
    await session.scalar(
        select(Person)
        .where(Person.id == person_id)
        .with_for_update(read=True)
        .execution_options(populate_existing=True)
    )
    await session.scalar(
        select(SalesXrayProfile)
        .where(SalesXrayProfile.person_id == person_id)
        .with_for_update(read=True)
        .execution_options(populate_existing=True)
    )
    try:
        profile = await get_sales_xray_profile(session, person_id=person_id)
    except SalesXrayProfileUnavailable as error:
        # Suspension, deletion, and missing verified identity remain ordinary
        # authority denials, never an onboarding hold that can be reconciled.
        from ac_platform.conversation_intelligence.application import ConversationDenied

        raise ConversationDenied("The upload owner's account is unavailable.") from error
    if not profile.profile_complete:
        raise AccountProfileRequired(PROFILE_INCOMPLETE_HOLD_REASON)


async def hold_current_job_for_account_profile(
    session: AsyncSession,
    *,
    job_id: UUID,
    lease_token: UUID,
    recovery_generation: int,
    expected_kind: str,
    hold_reason: str,
    now: datetime,
) -> bool:
    """Hold one current pre-dispatch lease, preserving every reservation and receipt.

    A false result means a global recovery hold, a stale lease, or dispatch
    evidence won the race. The caller must leave the job to the normal recovery
    or ambiguity path instead of converting it into an account hold.
    """

    if hold_reason not in ACCOUNT_PROFILE_HOLD_REASONS:
        raise ValueError("unsupported Sales Xray account-profile hold reason")
    recovery = await RecoveryStateRepository(session).get(lock=True, shared_lock=True)
    if (
        recovery is None
        or recovery.status != RecoveryStatus.READY.value
        or recovery.generation != recovery_generation
    ):
        return False
    job = await session.scalar(
        select(Job)
        .where(Job.id == job_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    current_time = now.replace(tzinfo=UTC) if now.tzinfo is None else now.astimezone(UTC)
    if (
        job is None
        or job.kind != expected_kind
        or job.status != JobStatus.LEASED.value
        or job.lease_token != lease_token
        or job.leased_until is None
        or job.leased_until <= current_time
        or (job.external_side_effect and job.recovery_generation != recovery_generation)
    ):
        return False
    if (
        job.dispatch_started_at is not None
        or job.delivery_ambiguous_at is not None
        or job.provider_idempotency_key is not None
        or job.provider_receipt is not None
        or job.provider_receipt_digest is not None
        or job.receipt_recorded_at is not None
    ):
        return False
    if job.tenant_id is None:
        return False

    job.status = JobStatus.HELD.value
    job.held_at = current_time
    job.hold_reason = hold_reason
    job.lease_token = None
    job.leased_until = None
    job.updated_at = current_time
    await AuditRepository(session).append(
        tenant_id=job.tenant_id,
        actor_person_id=None,
        actor_type="system",
        action="conversation.account_profile_required_held",
        resource_type="job",
        resource_id=job.id,
        payload={"hold_reason": hold_reason, "job_kind": job.kind},
        reason="Sales Xray account profile is required before processing.",
        now=current_time,
    )
    await session.flush()
    return True


def is_account_profile_hold(job: Job | None) -> bool:
    """Return only the bounded customer-safe account-profile hold indicator."""

    return bool(
        job is not None
        and job.status == JobStatus.HELD.value
        and job.hold_reason in ACCOUNT_PROFILE_HOLD_REASONS
    )
