"""Idempotent public-learner membership provisioning.

Canonical people remain global. This application adds only the configured
self-directed learner context and never creates an arbitrary tenant or changes
an existing membership role.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ac_platform.identity.models import Person, PersonStatus
from ac_platform.tenancy.models import (
    Membership,
    MembershipRole,
    MembershipStatus,
    Tenant,
    TenantStatus,
)


class LearnerProvisioningError(RuntimeError):
    """The configured learner context cannot be safely assigned."""


class LearnerConsentMissingError(LearnerProvisioningError):
    """The person has not recorded the reviewed learner consent."""


class LearnerConsentUpdateRequiredError(LearnerProvisioningError):
    """The person has a consent version that cannot be silently replaced."""


@dataclass(frozen=True, slots=True)
class LearnerProvisioningResult:
    tenant_id: UUID
    person_id: UUID
    role: str
    created: bool


class AsyncLearnerProvisioningApplication:
    """Ensure one active person has an active context in an exact tenant."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def ensure(
        self,
        *,
        person_id: UUID,
        tenant_id: UUID,
        required_consent_version: str,
    ) -> LearnerProvisioningResult:
        if not required_consent_version.strip() or len(required_consent_version) > 64:
            raise LearnerProvisioningError("the required learner consent version is invalid")

        # Lock every provisioning path in person -> tenant -> membership order.
        # The person lock serializes duplicate provisioning for one identity,
        # while the shared tenant lock allows unrelated learners to proceed in
        # parallel and prevents the configured tenant from changing lifecycle
        # state until this transaction finishes.
        person = await self._session.scalar(
            select(Person).where(Person.id == person_id).with_for_update()
        )
        if (
            person is None
            or person.status != PersonStatus.ACTIVE.value
            or person.email_verified_at is None
        ):
            raise LearnerProvisioningError(
                "only an active email-verified person can receive learner context"
            )
        if (
            person.consent_version is not None
            and person.consent_version != required_consent_version
        ):
            raise LearnerConsentUpdateRequiredError(
                "the exact required learner consent has not been recorded"
            )
        if person.consent_version is None or person.consented_at is None:
            raise LearnerConsentMissingError(
                "the exact required learner consent has not been recorded"
            )
        tenant = await self._session.scalar(
            select(Tenant).where(Tenant.id == tenant_id).with_for_update(read=True)
        )
        if tenant is None or tenant.status != TenantStatus.ACTIVE.value:
            raise LearnerProvisioningError("the configured public learner tenant is unavailable")
        membership = await self._session.scalar(
            select(Membership)
            .where(Membership.tenant_id == tenant_id, Membership.person_id == person_id)
            .with_for_update(read=True)
        )
        if membership is not None:
            if membership.status != MembershipStatus.ACTIVE.value:
                raise LearnerProvisioningError(
                    "an inactive membership cannot be reactivated by learner registration"
                )
            if membership.role != MembershipRole.LEARNER.value:
                raise LearnerProvisioningError(
                    "learner registration requires the canonical membership role "
                    "to be exactly learner"
                )
            return LearnerProvisioningResult(
                tenant_id=tenant_id,
                person_id=person_id,
                role=membership.role,
                created=False,
            )
        candidate = Membership(
            tenant_id=tenant_id,
            person_id=person_id,
            role=MembershipRole.LEARNER.value,
            status=MembershipStatus.ACTIVE.value,
        )
        try:
            async with self._session.begin_nested():
                self._session.add(candidate)
                await self._session.flush()
        except IntegrityError:
            membership = await self._session.scalar(
                select(Membership)
                .where(Membership.tenant_id == tenant_id, Membership.person_id == person_id)
                .with_for_update(read=True)
            )
            if membership is None or membership.status != MembershipStatus.ACTIVE.value:
                raise LearnerProvisioningError(
                    "learner membership creation raced without an active canonical result"
                ) from None
            if membership.role != MembershipRole.LEARNER.value:
                raise LearnerProvisioningError(
                    "learner registration requires the raced canonical membership role "
                    "to be exactly learner"
                ) from None
            return LearnerProvisioningResult(
                tenant_id=tenant_id,
                person_id=person_id,
                role=membership.role,
                created=False,
            )
        return LearnerProvisioningResult(
            tenant_id=tenant_id,
            person_id=person_id,
            role=MembershipRole.LEARNER.value,
            created=True,
        )


__all__ = [
    "AsyncLearnerProvisioningApplication",
    "LearnerConsentMissingError",
    "LearnerConsentUpdateRequiredError",
    "LearnerProvisioningError",
    "LearnerProvisioningResult",
]
