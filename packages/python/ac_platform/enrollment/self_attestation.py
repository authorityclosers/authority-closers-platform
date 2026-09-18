"""Consent-backed eligibility for the exact v0.1 public free-course path.

The registration consent records an explicit 18+ learner attestation.  This
application turns that already-recorded, versioned statement into the
canonical eligibility fact only when the learner explicitly starts the exact
published Authority Closers free course.  It does not infer eligibility from
analytics, provider state, an admin role, or the existence of a session.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import SessionTransactionOrigin

from ac_platform.catalog.models import (
    CatalogScope,
    Program,
    ProgramVersion,
    ProgramVersionStatus,
)
from ac_platform.enrollment.models import EnrollmentEligibilityFact
from ac_platform.identity.models import Person, PersonStatus
from ac_platform.kernel.errors import AuthorizationDenied
from ac_platform.tenancy.models import (
    Membership,
    MembershipRole,
    MembershipStatus,
    Tenant,
    TenantStatus,
)

AUTHORITY_CLOSERS_FREE_PROGRAM_SLUG = "authority-closers-free-course"
SELF_ATTESTED_ELIGIBILITY_POLICY_VERSION = "AC-FREE-SELF-ATTESTATION-v1"


class SelfAttestedEligibilityDenied(AuthorizationDenied):
    """The canonical learner facts do not authorize self-attested eligibility."""

    code = "self_attested_eligibility_denied"
    title = "Free-course eligibility could not be confirmed"


class LearnerConsentUpdateRequired(SelfAttestedEligibilityDenied):
    """The learner must explicitly renew the server-published consent document."""

    code = "learner_consent_update_required"
    title = "Current learner consent is required"


class SelfAttestedEligibilityTransactionRequired(SelfAttestedEligibilityDenied):
    """The eligibility fact must be created in the enrollment transaction."""

    code = "self_attested_eligibility_transaction_required"


@dataclass(frozen=True, slots=True)
class SelfAttestedEligibilityResult:
    fact_id: UUID
    tenant_id: UUID
    person_id: UUID
    program_version_id: UUID
    policy_version: str
    created: bool


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


class AsyncSelfAttestedEligibilityApplication:
    """Create or reuse one auditable eligibility fact for the approved course."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._session = session
        self._clock = clock or (lambda: datetime.now(UTC))

    def _require_transaction(self) -> None:
        transaction = self._session.get_transaction()
        sync_transaction = None if transaction is None else transaction.sync_transaction
        if (
            sync_transaction is None
            or sync_transaction.origin is not SessionTransactionOrigin.BEGIN
        ):
            raise SelfAttestedEligibilityTransactionRequired(
                "self-attested eligibility requires a caller-owned transaction"
            )

    @staticmethod
    def _require_reusable_fact(
        fact: EnrollmentEligibilityFact,
        *,
        now: datetime,
        tenant_id: UUID,
        person_id: UUID,
        program: Program,
        version: ProgramVersion,
        consent_version: str,
        consented_at: datetime,
    ) -> None:
        if (
            fact.age_gate_passed is not True
            or fact.eligibility_passed is not True
            or fact.prerequisites_satisfied is not True
            or (fact.valid_until is not None and _as_utc(fact.valid_until) <= now)
        ):
            raise SelfAttestedEligibilityDenied(
                "the existing eligibility decision does not permit enrollment"
            )
        evidence = fact.evidence
        if (
            fact.policy_version != SELF_ATTESTED_ELIGIBILITY_POLICY_VERSION
            or fact.tenant_id != tenant_id
            or fact.person_id != person_id
            or fact.program_version_id != version.id
            or fact.program_id != program.id
            or fact.program_id != version.program_id
            or fact.program_scope != program.scope
            or fact.program_scope != version.scope
            or fact.program_tenant_id != program.tenant_id
            or fact.program_tenant_id != version.tenant_id
            or fact.program_owner_key != program.owner_key
            or fact.program_owner_key != version.owner_key
            or not isinstance(evidence, dict)
            or evidence.get("source") != "recorded_learner_consent"
            or evidence.get("consent_version") != consent_version
            or evidence.get("consented_at") != _as_utc(consented_at).isoformat()
            or evidence.get("explicit_action") != "start_free_course"
            or evidence.get("program_slug") != AUTHORITY_CLOSERS_FREE_PROGRAM_SLUG
        ):
            raise SelfAttestedEligibilityDenied(
                "the existing eligibility decision is not compatible with the current "
                "self-attestation policy and evidence"
            )

    async def ensure(
        self,
        *,
        person_id: UUID,
        tenant_id: UUID,
        program_version_id: UUID,
        required_consent_version: str,
    ) -> SelfAttestedEligibilityResult:
        """Persist the consent-backed fact before the enrollment command runs."""

        self._require_transaction()
        consent_version = required_consent_version.strip()
        now = _as_utc(self._clock())

        # Match the enrollment repository's lock order so the subsequent
        # command can safely reuse the same transaction and rows.
        person = await self._session.scalar(
            select(Person).where(Person.id == person_id).with_for_update()
        )
        tenant = await self._session.scalar(
            select(Tenant).where(Tenant.id == tenant_id).with_for_update()
        )
        membership = await self._session.scalar(
            select(Membership)
            .where(Membership.tenant_id == tenant_id, Membership.person_id == person_id)
            .with_for_update()
        )
        version = await self._session.scalar(
            select(ProgramVersion).where(ProgramVersion.id == program_version_id).with_for_update()
        )
        program = None
        if version is not None:
            program = await self._session.scalar(
                select(Program).where(Program.id == version.program_id).with_for_update(read=True)
            )

        if (
            person is None
            or person.status != PersonStatus.ACTIVE.value
            or person.email_verified_at is None
        ):
            raise SelfAttestedEligibilityDenied(
                "only an active email-verified learner can start the free course"
            )
        if tenant is None or tenant.status != TenantStatus.ACTIVE.value:
            raise SelfAttestedEligibilityDenied("the public learner tenant is unavailable")
        if (
            membership is None
            or membership.status != MembershipStatus.ACTIVE.value
            or membership.ended_at is not None
            or membership.role != MembershipRole.LEARNER.value
        ):
            raise SelfAttestedEligibilityDenied(
                "an active learner membership is required for free-course access"
            )
        if (
            version is None
            or program is None
            or version.status != ProgramVersionStatus.PUBLISHED.value
            or program.id != version.program_id
        ):
            raise SelfAttestedEligibilityDenied("the requested program version is not published")

        if not 1 <= len(consent_version) <= 64:
            raise SelfAttestedEligibilityDenied(
                "the reviewed learner consent version is not configured"
            )
        if person.consent_version != consent_version or person.consented_at is None:
            if person.consent_version is not None and person.consent_version != consent_version:
                raise LearnerConsentUpdateRequired(
                    "Review and accept the current learner consent document before enrolling."
                )
            raise SelfAttestedEligibilityDenied(
                "the exact required 18+ learner consent has not been recorded"
            )
        if (
            version.scope != CatalogScope.GLOBAL.value
            or program.scope != CatalogScope.GLOBAL.value
            or program.slug != AUTHORITY_CLOSERS_FREE_PROGRAM_SLUG
        ):
            raise SelfAttestedEligibilityDenied(
                "self-attestation is limited to the published Authority Closers free course"
            )

        existing = await self._session.scalar(
            select(EnrollmentEligibilityFact)
            .where(
                EnrollmentEligibilityFact.tenant_id == tenant_id,
                EnrollmentEligibilityFact.person_id == person_id,
                EnrollmentEligibilityFact.program_version_id == version.id,
                EnrollmentEligibilityFact.program_id == version.program_id,
                EnrollmentEligibilityFact.program_scope == version.scope,
                EnrollmentEligibilityFact.program_owner_key == version.owner_key,
            )
            .with_for_update()
        )
        if existing is not None:
            self._require_reusable_fact(
                existing,
                now=now,
                tenant_id=tenant_id,
                person_id=person_id,
                program=program,
                version=version,
                consent_version=consent_version,
                consented_at=person.consented_at,
            )
            return SelfAttestedEligibilityResult(
                fact_id=existing.id,
                tenant_id=tenant_id,
                person_id=person_id,
                program_version_id=version.id,
                policy_version=existing.policy_version,
                created=False,
            )

        candidate = EnrollmentEligibilityFact(
            tenant_id=tenant_id,
            person_id=person_id,
            program_version_id=version.id,
            program_id=version.program_id,
            program_scope=version.scope,
            program_tenant_id=version.tenant_id,
            program_owner_key=version.owner_key,
            age_gate_passed=True,
            eligibility_passed=True,
            prerequisites_satisfied=True,
            policy_version=SELF_ATTESTED_ELIGIBILITY_POLICY_VERSION,
            evidence={
                "source": "recorded_learner_consent",
                "consent_version": consent_version,
                "consented_at": _as_utc(person.consented_at).isoformat(),
                "explicit_action": "start_free_course",
                "program_slug": AUTHORITY_CLOSERS_FREE_PROGRAM_SLUG,
            },
            evaluated_at=now,
            valid_until=None,
        )
        try:
            async with self._session.begin_nested():
                self._session.add(candidate)
                await self._session.flush()
        except IntegrityError:
            existing = await self._session.scalar(
                select(EnrollmentEligibilityFact)
                .where(
                    EnrollmentEligibilityFact.tenant_id == tenant_id,
                    EnrollmentEligibilityFact.person_id == person_id,
                    EnrollmentEligibilityFact.program_version_id == version.id,
                    EnrollmentEligibilityFact.program_id == version.program_id,
                    EnrollmentEligibilityFact.program_scope == version.scope,
                    EnrollmentEligibilityFact.program_owner_key == version.owner_key,
                )
                .with_for_update()
            )
            if existing is None:
                raise SelfAttestedEligibilityDenied(
                    "eligibility creation raced without a canonical result"
                ) from None
            self._require_reusable_fact(
                existing,
                now=now,
                tenant_id=tenant_id,
                person_id=person_id,
                program=program,
                version=version,
                consent_version=consent_version,
                consented_at=person.consented_at,
            )
            return SelfAttestedEligibilityResult(
                fact_id=existing.id,
                tenant_id=tenant_id,
                person_id=person_id,
                program_version_id=version.id,
                policy_version=existing.policy_version,
                created=False,
            )

        return SelfAttestedEligibilityResult(
            fact_id=candidate.id,
            tenant_id=tenant_id,
            person_id=person_id,
            program_version_id=version.id,
            policy_version=candidate.policy_version,
            created=True,
        )


__all__ = [
    "AUTHORITY_CLOSERS_FREE_PROGRAM_SLUG",
    "LearnerConsentUpdateRequired",
    "SELF_ATTESTED_ELIGIBILITY_POLICY_VERSION",
    "AsyncSelfAttestedEligibilityApplication",
    "SelfAttestedEligibilityDenied",
    "SelfAttestedEligibilityResult",
    "SelfAttestedEligibilityTransactionRequired",
]
