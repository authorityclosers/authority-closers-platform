"""Transaction-oriented commands for the G1 access boundary.

This module owns the only application paths that may create an entitlement in
the first slice.  The free command is self-only.  A separate, deliberately
named manual-grant command exists for a later admin seam and requires an
explicit authorization input and reason.  There is no generic "grant"
operation and no provider, ERP, analytics, or UI callback path here.
"""

from __future__ import annotations

import copy
import hashlib
import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from typing import Any, Protocol, Self, cast
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import SessionTransactionOrigin

from ac_platform.audit.service import AuditRepository
from ac_platform.catalog.models import (
    GLOBAL_CATALOG_OWNER_KEY,
    ProgramVersion,
    ProgramVersionStatus,
)
from ac_platform.enrollment.models import (
    CommandIdempotency,
    CommandStatus,
    Enrollment,
    EnrollmentEligibilityFact,
    EnrollmentProvenance,
    EnrollmentSource,
    EnrollmentStatus,
    Entitlement,
    EntitlementStatus,
)
from ac_platform.identity.models import Person, PersonStatus
from ac_platform.kernel.authz import ActorContext
from ac_platform.kernel.errors import AuthorizationDenied, DomainError, ResourceConflict
from ac_platform.kernel.events import EventCategory, EventEnvelope
from ac_platform.outbox.repository import OutboxRepository
from ac_platform.tenancy.models import (
    Membership,
    MembershipStatus,
    Tenant,
    TenantStatus,
)

CONTROLLED_GAP_AGE_ELIGIBILITY = "PROV-G1-AGE-ELIGIBILITY-POLICY"
CONTROLLED_POLICY_VERSION = "PROV-G1-ELIGIBILITY-INPUTS-v1"
FREE_ENROLLMENT_OPERATION = "enroll_free"
MANUAL_GRANT_OPERATION = "grant_manual"
ENROLLMENT_GRANT_PERMISSION = "enrollment_grant"
LEARNER_ROLE = "learner"
MANUAL_GRANT_ROLES = frozenset({"support", "admin", "owner"})


def utc_now() -> datetime:
    """Return an aware UTC timestamp suitable for command defaults."""

    return datetime.now(UTC)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


class EnrollmentError(DomainError):
    """Base error for the enrollment capability boundary."""

    code = "enrollment_rejected"
    title = "Enrollment was rejected"


class EnrollmentAuthorizationError(AuthorizationDenied, EnrollmentError):
    """Base error for an access policy rejection."""

    code = "enrollment_authorization_denied"
    title = "Enrollment access was denied"


class EnrollmentSourceDeniedError(EnrollmentAuthorizationError):
    """The caller used a source that is not an access-grant command."""

    code = "enrollment_source_denied"


class ActorSubjectMismatchError(EnrollmentAuthorizationError):
    """Free enrollment was requested for a person other than the actor."""

    code = "enrollment_actor_subject_mismatch"


class CrossSubjectEnrollmentError(EnrollmentAuthorizationError):
    """A policy input belongs to a different subject."""

    code = "enrollment_cross_subject"


class CrossTenantEnrollmentError(EnrollmentAuthorizationError):
    """A policy input or resource belongs to a different tenant."""

    code = "enrollment_cross_tenant"


class MembershipPolicyDeniedError(EnrollmentAuthorizationError):
    """The required active tenant membership was not proven."""

    code = "enrollment_membership_denied"


class EligibilityPolicyDeniedError(EnrollmentAuthorizationError):
    """An explicit eligibility policy input was absent or negative."""

    code = "enrollment_eligibility_denied"


class ProgramVersionPolicyDeniedError(EnrollmentAuthorizationError):
    """The requested program version was not proven publishable and immutable."""

    code = "enrollment_program_version_denied"


class ManualGrantAuthorizationDeniedError(EnrollmentAuthorizationError):
    """The separately named manual-grant seam was not authorized."""

    code = "enrollment_manual_grant_denied"


class DuplicateEnrollmentError(ResourceConflict, EnrollmentError):
    """The learner already has an enrollment for this pinned version."""

    code = "enrollment_duplicate"
    title = "Enrollment already exists"


class IdempotencyConflictError(ResourceConflict, EnrollmentError):
    """The same scoped idempotency key was reused for another request."""

    code = "idempotency_conflict"
    title = "Idempotency key was reused"


class CommandInProgressError(ResourceConflict, EnrollmentError):
    """A concurrent command currently owns the same idempotency key."""

    code = "command_in_progress"
    title = "The command is already in progress"


class IdempotencyStateError(EnrollmentError):
    """A completed command did not retain a complete canonical result."""

    code = "idempotency_state_invalid"


class EnrollmentPersistenceError(EnrollmentError):
    """The persistence boundary could not establish the requested state."""

    code = "enrollment_persistence_failed"


class EnrollmentTransactionRequiredError(EnrollmentPersistenceError):
    """A production command was called outside a caller-owned transaction."""

    code = "enrollment_transaction_required"


class UniqueConstraintViolation(Exception):
    """Internal repository signal for a database uniqueness race."""


@dataclass(frozen=True, slots=True)
class MembershipPolicyInput:
    """Explicit, server-derived membership facts for one subject and tenant."""

    person_id: UUID
    tenant_id: UUID
    active: bool
    tenant_active: bool
    role: str | None = None


@dataclass(frozen=True, slots=True)
class ProgramVersionPolicyInput:
    """Explicit facts proving the requested version can be pinned."""

    id: UUID
    tenant_id: UUID
    published: bool
    immutable: bool
    # The catalog owner identity is optional only for legacy in-memory policy
    # fixtures. Durable enrollment rows require the complete identity through
    # the database composite FK.
    program_id: UUID | None = None
    scope: str | None = None
    program_scope: str | None = None
    program_tenant_id: UUID | None = None
    program_owner_key: UUID | None = None
    owner_key: UUID | None = None


@dataclass(frozen=True, slots=True)
class EligibilityPolicyInput:
    """Policy outputs; this service never derives age or eligibility itself.

    ``None`` is intentionally distinct from ``False`` and is rejected by the
    free command.  ``controlled_gaps`` records the unresolved controlled
    contract instead of silently treating an absent age rule as a fact.
    """

    person_id: UUID
    age_gate_passed: bool | None
    eligibility_passed: bool | None
    prerequisites_satisfied: bool | None
    policy_version: str = CONTROLLED_POLICY_VERSION
    controlled_gaps: tuple[str, ...] = (CONTROLLED_GAP_AGE_ELIGIBILITY,)
    evidence: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ManualGrantPolicyInput:
    """Explicit authorization facts for the later named manual-grant seam."""

    actor_person_id: UUID
    tenant_id: UUID
    active: bool
    authorized: bool
    role: str | None = None


@dataclass(frozen=True, slots=True)
class EnrollmentPolicyInput:
    """All policy inputs required before a command can create access."""

    membership: MembershipPolicyInput
    program_version: ProgramVersionPolicyInput
    eligibility: EligibilityPolicyInput | None = None
    manual_grant: ManualGrantPolicyInput | None = None

    @classmethod
    def for_free_enrollment(
        cls,
        *,
        subject_person_id: UUID,
        tenant_id: UUID,
        program_version_id: UUID,
        age_gate_passed: bool | None,
        eligibility_passed: bool | None,
        prerequisites_satisfied: bool | None,
        membership_active: bool = True,
        tenant_active: bool = True,
        membership_role: str | None = LEARNER_ROLE,
        program_version_published: bool = True,
        program_version_immutable: bool = True,
        program_id: UUID | None = None,
        program_scope: str | None = None,
        program_tenant_id: UUID | None = None,
        program_owner_key: UUID | None = None,
        controlled_gaps: tuple[str, ...] = (CONTROLLED_GAP_AGE_ELIGIBILITY,),
    ) -> EnrollmentPolicyInput:
        """Build a policy value while keeping all access-relevant facts explicit."""

        return cls(
            membership=MembershipPolicyInput(
                person_id=subject_person_id,
                tenant_id=tenant_id,
                active=membership_active,
                tenant_active=tenant_active,
                role=membership_role,
            ),
            program_version=ProgramVersionPolicyInput(
                id=program_version_id,
                tenant_id=tenant_id,
                published=program_version_published,
                immutable=program_version_immutable,
                program_id=program_id,
                program_scope=program_scope,
                program_tenant_id=program_tenant_id,
                program_owner_key=program_owner_key,
            ),
            eligibility=EligibilityPolicyInput(
                person_id=subject_person_id,
                age_gate_passed=age_gate_passed,
                eligibility_passed=eligibility_passed,
                prerequisites_satisfied=prerequisites_satisfied,
                controlled_gaps=controlled_gaps,
            ),
        )


@dataclass(frozen=True, slots=True)
class FreeEnrollmentCommand:
    """Self-service command that can create the first-slice access capability."""

    actor_person_id: UUID
    subject_person_id: UUID
    tenant_id: UUID
    program_version_id: UUID
    idempotency_key: str
    source: str = EnrollmentSource.FREE_SELF.value


@dataclass(frozen=True, slots=True)
class ManualEnrollmentGrantCommand:
    """Named, audited seam reserved for a future authorized admin route."""

    actor_person_id: UUID
    subject_person_id: UUID
    tenant_id: UUID
    program_version_id: UUID
    idempotency_key: str
    reason: str
    policy: EnrollmentPolicyInput
    source: str = EnrollmentSource.MANUAL_GRANT.value


@dataclass(frozen=True, slots=True)
class EnrollmentResult:
    """Stable command result returned for both creation and replay."""

    enrollment_id: UUID
    entitlement_id: UUID
    provenance_id: UUID
    command_idempotency_id: UUID
    created: bool
    replayed: bool


@dataclass(frozen=True, slots=True)
class OutboxIntent:
    """A durable-side-effect intent, never a provider callback or send."""

    name: str
    aggregate_type: str
    aggregate_id: UUID
    tenant_id: UUID
    dedupe_key: str
    payload: dict[str, Any]


class OutboxIntentPort(Protocol):
    """Port staged by the same unit of work as the canonical state."""

    def enqueue(self, intent: OutboxIntent) -> None: ...


class EnrollmentRepository(Protocol):
    """Async persistence port used by the transaction-oriented service."""

    async def get_idempotency(
        self,
        *,
        tenant_id: UUID,
        actor_person_id: UUID,
        operation: str,
        idempotency_key: str,
        for_update: bool = False,
    ) -> CommandIdempotency | None: ...

    async def claim_idempotency(self, command: CommandIdempotency) -> None: ...

    async def load_free_enrollment_policy(
        self,
        *,
        actor_person_id: UUID,
        subject_person_id: UUID,
        tenant_id: UUID,
        program_version_id: UUID,
        now: datetime,
    ) -> EnrollmentPolicyInput: ...

    async def load_manual_grant_policy(
        self,
        *,
        actor_person_id: UUID,
        subject_person_id: UUID,
        tenant_id: UUID,
        program_version_id: UUID,
        now: datetime,
    ) -> EnrollmentPolicyInput: ...

    async def find_enrollment(
        self,
        *,
        tenant_id: UUID,
        person_id: UUID,
        program_version_id: UUID,
    ) -> Enrollment | None: ...

    async def save_records(
        self,
        enrollment: Enrollment,
        provenance: EnrollmentProvenance,
        entitlement: Entitlement,
    ) -> None: ...

    async def load_command_result(self, command: CommandIdempotency) -> EnrollmentResult | None: ...


class EnrollmentUnitOfWork(Protocol):
    """Transaction seam containing state, audit events, and outbox intents."""

    repository: EnrollmentRepository
    outbox: OutboxIntentPort

    async def __aenter__(self) -> Self: ...

    async def __aexit__(self, exc_type: Any, exc_value: Any, traceback: Any) -> None: ...

    def add_event(self, event: EventEnvelope) -> None: ...

    async def commit(self) -> None: ...

    async def rollback(self) -> None: ...


class SqlAlchemyEnrollmentRepository:
    """SQLAlchemy 2 async adapter for the enrollment persistence port."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_idempotency(
        self,
        *,
        tenant_id: UUID,
        actor_person_id: UUID,
        operation: str,
        idempotency_key: str,
        for_update: bool = False,
    ) -> CommandIdempotency | None:
        statement = select(CommandIdempotency).where(
            CommandIdempotency.tenant_id == tenant_id,
            CommandIdempotency.actor_person_id == actor_person_id,
            CommandIdempotency.operation == operation,
            CommandIdempotency.idempotency_key == idempotency_key,
        )
        if for_update:
            statement = statement.with_for_update()
        return cast(CommandIdempotency | None, await self._session.scalar(statement))

    async def claim_idempotency(self, command: CommandIdempotency) -> None:
        try:
            async with self._session.begin_nested():
                self._session.add(command)
                await self._session.flush()
        except IntegrityError as exc:
            raise UniqueConstraintViolation("idempotency scope key already exists") from exc

    async def load_free_enrollment_policy(
        self,
        *,
        actor_person_id: UUID,
        subject_person_id: UUID,
        tenant_id: UUID,
        program_version_id: UUID,
        now: datetime,
    ) -> EnrollmentPolicyInput:
        """Lock and derive every free-enrollment authorization fact from canonical rows."""

        del actor_person_id
        person = await self._session.scalar(
            select(Person).where(Person.id == subject_person_id).with_for_update()
        )
        tenant = await self._session.scalar(
            select(Tenant).where(Tenant.id == tenant_id).with_for_update()
        )
        membership = await self._session.scalar(
            select(Membership)
            .where(
                Membership.tenant_id == tenant_id,
                Membership.person_id == subject_person_id,
            )
            .with_for_update()
        )
        version = await self._session.scalar(
            select(ProgramVersion).where(ProgramVersion.id == program_version_id).with_for_update()
        )
        eligibility: EnrollmentEligibilityFact | None = None
        if version is not None:
            eligibility = await self._session.scalar(
                select(EnrollmentEligibilityFact)
                .where(
                    EnrollmentEligibilityFact.tenant_id == tenant_id,
                    EnrollmentEligibilityFact.person_id == subject_person_id,
                    EnrollmentEligibilityFact.program_version_id == version.id,
                    EnrollmentEligibilityFact.program_id == version.program_id,
                    EnrollmentEligibilityFact.program_scope == version.scope,
                    EnrollmentEligibilityFact.program_owner_key == version.owner_key,
                )
                .with_for_update()
            )

        person_active = person is not None and person.status == PersonStatus.ACTIVE.value
        membership_active = bool(
            person_active
            and membership is not None
            and membership.status == MembershipStatus.ACTIVE.value
            and membership.ended_at is None
        )
        tenant_active = tenant is not None and tenant.status == TenantStatus.ACTIVE.value
        version_policy = ProgramVersionPolicyInput(
            id=program_version_id,
            tenant_id=tenant_id,
            published=(
                version is not None and version.status == ProgramVersionStatus.PUBLISHED.value
            ),
            immutable=(
                version is not None and version.status == ProgramVersionStatus.PUBLISHED.value
            ),
            program_id=version.program_id if version is not None else None,
            program_scope=version.scope if version is not None else "tenant",
            program_tenant_id=version.tenant_id if version is not None else tenant_id,
            program_owner_key=(version.owner_key if version is not None else tenant_id),
        )
        eligibility_valid = bool(
            eligibility is not None
            and (eligibility.valid_until is None or _as_utc(eligibility.valid_until) > _as_utc(now))
        )
        eligibility_policy = EligibilityPolicyInput(
            person_id=subject_person_id,
            age_gate_passed=(
                eligibility.age_gate_passed
                if eligibility is not None and eligibility_valid
                else None
            ),
            eligibility_passed=(
                eligibility.eligibility_passed
                if eligibility is not None and eligibility_valid
                else None
            ),
            prerequisites_satisfied=(
                eligibility.prerequisites_satisfied
                if eligibility is not None and eligibility_valid
                else None
            ),
            policy_version=(
                eligibility.policy_version if eligibility is not None else CONTROLLED_POLICY_VERSION
            ),
            controlled_gaps=(),
            evidence=(dict(eligibility.evidence) if eligibility is not None else {}),
        )
        return EnrollmentPolicyInput(
            membership=MembershipPolicyInput(
                person_id=subject_person_id,
                tenant_id=tenant_id,
                active=membership_active,
                tenant_active=tenant_active,
                role=membership.role if membership is not None else None,
            ),
            program_version=version_policy,
            eligibility=eligibility_policy,
        )

    async def load_manual_grant_policy(
        self,
        *,
        actor_person_id: UUID,
        subject_person_id: UUID,
        tenant_id: UUID,
        program_version_id: UUID,
        now: datetime,
    ) -> EnrollmentPolicyInput:
        """Reload the grant actor and target from canonical, locked rows.

        The command may carry a policy for audit context, but authorization is
        derived here from the live actor membership.  In particular, the
        caller cannot make an inactive actor, arbitrary role, or boolean
        authorization assertion authoritative.
        """

        actor = await self._session.scalar(
            select(Person).where(Person.id == actor_person_id).with_for_update()
        )
        tenant = await self._session.scalar(
            select(Tenant).where(Tenant.id == tenant_id).with_for_update()
        )
        actor_membership = await self._session.scalar(
            select(Membership)
            .where(
                Membership.tenant_id == tenant_id,
                Membership.person_id == actor_person_id,
            )
            .with_for_update()
        )
        policy = await self.load_free_enrollment_policy(
            actor_person_id=actor_person_id,
            subject_person_id=subject_person_id,
            tenant_id=tenant_id,
            program_version_id=program_version_id,
            now=now,
        )
        actor_active = bool(actor is not None and actor.status == PersonStatus.ACTIVE.value)
        tenant_active = bool(tenant is not None and tenant.status == TenantStatus.ACTIVE.value)
        membership_active = bool(
            actor_membership is not None
            and actor_membership.status == MembershipStatus.ACTIVE.value
            and actor_membership.ended_at is None
        )
        return replace(
            policy,
            manual_grant=ManualGrantPolicyInput(
                actor_person_id=actor_person_id,
                tenant_id=tenant_id,
                active=actor_active and tenant_active and membership_active,
                authorized=(
                    actor_active
                    and tenant_active
                    and membership_active
                    and actor_membership is not None
                    and actor_membership.role in MANUAL_GRANT_ROLES
                ),
                role=actor_membership.role if actor_membership is not None else None,
            ),
        )

    async def find_enrollment(
        self,
        *,
        tenant_id: UUID,
        person_id: UUID,
        program_version_id: UUID,
    ) -> Enrollment | None:
        statement = select(Enrollment).where(
            Enrollment.tenant_id == tenant_id,
            Enrollment.person_id == person_id,
            Enrollment.program_version_id == program_version_id,
        )
        return cast(Enrollment | None, await self._session.scalar(statement))

    async def save_records(
        self,
        enrollment: Enrollment,
        provenance: EnrollmentProvenance,
        entitlement: Entitlement,
    ) -> None:
        try:
            async with self._session.begin_nested():
                self._session.add_all([enrollment, provenance, entitlement])
                await self._session.flush()
        except IntegrityError as exc:
            raise UniqueConstraintViolation(
                "enrollment uniqueness constraint rejected the write"
            ) from exc

    async def load_command_result(self, command: CommandIdempotency) -> EnrollmentResult | None:
        if (
            command.result_enrollment_id is None
            or command.result_entitlement_id is None
            or command.result_provenance_id is None
        ):
            return None
        identity = (
            Enrollment.tenant_id == command.tenant_id,
            Enrollment.person_id == command.subject_person_id,
            Enrollment.program_version_id == command.program_version_id,
            Enrollment.program_id == command.program_id,
            Enrollment.program_scope == command.program_scope,
            Enrollment.program_owner_key == command.program_owner_key,
        )
        enrollment = await self._session.scalar(
            select(Enrollment).where(Enrollment.id == command.result_enrollment_id, *identity)
        )
        if enrollment is None:
            return None
        provenance = await self._session.scalar(
            select(EnrollmentProvenance).where(
                EnrollmentProvenance.id == command.result_provenance_id,
                EnrollmentProvenance.tenant_id == command.tenant_id,
                EnrollmentProvenance.enrollment_id == enrollment.id,
                EnrollmentProvenance.person_id == command.subject_person_id,
                EnrollmentProvenance.program_version_id == command.program_version_id,
                EnrollmentProvenance.program_id == command.program_id,
                EnrollmentProvenance.program_scope == command.program_scope,
                EnrollmentProvenance.program_owner_key == command.program_owner_key,
                EnrollmentProvenance.command_idempotency_id == command.id,
            )
        )
        entitlement = await self._session.scalar(
            select(Entitlement).where(
                Entitlement.id == command.result_entitlement_id,
                Entitlement.tenant_id == command.tenant_id,
                Entitlement.enrollment_id == enrollment.id,
                Entitlement.provenance_id == command.result_provenance_id,
                Entitlement.person_id == command.subject_person_id,
                Entitlement.program_version_id == command.program_version_id,
                Entitlement.program_id == command.program_id,
                Entitlement.program_scope == command.program_scope,
                Entitlement.program_owner_key == command.program_owner_key,
            )
        )
        if provenance is None or entitlement is None:
            return None
        return EnrollmentResult(
            enrollment_id=enrollment.id,
            entitlement_id=entitlement.id,
            provenance_id=provenance.id,
            command_idempotency_id=command.id,
            created=False,
            replayed=True,
        )


class _SqlAlchemyOutboxIntentPort:
    """Stage domain intents until the SQL UoW flushes the public outbox port."""

    def __init__(self) -> None:
        self.pending: list[OutboxIntent] = []

    def enqueue(self, intent: OutboxIntent) -> None:
        self.pending.append(intent)


class SqlAlchemyEnrollmentUnitOfWork:
    """Async UoW over one explicit caller-owned session and transaction."""

    def __init__(self, session: AsyncSession, outbox: OutboxIntentPort | None = None) -> None:
        del outbox  # Legacy sinks are intentionally not used for durable commands.
        self._session = session
        self.repository: EnrollmentRepository = SqlAlchemyEnrollmentRepository(self._session)
        self.audit_repository = AuditRepository(self._session)
        self.outbox_repository = OutboxRepository(self._session)
        self._outbox = _SqlAlchemyOutboxIntentPort()
        self.outbox: OutboxIntentPort = self._outbox
        self.events: list[EventEnvelope] = []
        self._committed = False
        self._entered = False

    async def __aenter__(self) -> SqlAlchemyEnrollmentUnitOfWork:
        transaction = self._session.get_transaction()
        sync_transaction = None if transaction is None else transaction.sync_transaction
        if (
            sync_transaction is None
            or sync_transaction.origin is not SessionTransactionOrigin.BEGIN
        ):
            raise EnrollmentTransactionRequiredError(
                "enrollment commands require an explicit caller-owned AsyncSession transaction"
            )
        self._entered = True
        return self

    async def __aexit__(self, exc_type: Any, exc_value: Any, traceback: Any) -> None:
        del exc_value, traceback
        if exc_type is not None or not self._committed:
            await self.rollback()

    def add_event(self, event: EventEnvelope) -> None:
        if event.category is not EventCategory.AUDIT:
            raise EnrollmentPersistenceError("enrollment audit staging accepts audit events only")
        self.events.append(event)

    async def commit(self) -> None:
        if not self._entered:
            raise EnrollmentPersistenceError("unit of work is not active")
        try:
            for event in self.events:
                if event.tenant_id is None:
                    raise EnrollmentPersistenceError(
                        "enrollment audit events require an explicit tenant"
                    )
                actor_value = event.payload.get("actor_person_id")
                actor_person_id = UUID(str(actor_value)) if actor_value is not None else None
                await self.audit_repository.append(
                    tenant_id=event.tenant_id,
                    actor_person_id=actor_person_id,
                    action=event.name,
                    resource_type=event.aggregate_type,
                    resource_id=event.aggregate_id,
                    payload=event.payload,
                    request_id=str(event.payload.get("command_idempotency_id", "")) or None,
                    now=event.occurred_at,
                    event_id=event.event_id,
                )
            for intent in self._outbox.pending:
                await self.outbox_repository.enqueue(
                    EventEnvelope(
                        name=intent.name,
                        category=EventCategory.DOMAIN_FACT,
                        aggregate_type=intent.aggregate_type,
                        aggregate_id=intent.aggregate_id,
                        tenant_id=intent.tenant_id,
                        payload=dict(intent.payload),
                    ),
                    dedupe_key=intent.dedupe_key,
                )
            await self._session.flush()
            self._committed = True
        except BaseException:
            self._outbox.pending.clear()
            self.events.clear()
            raise

    async def rollback(self) -> None:
        self._outbox.pending.clear()
        self.events.clear()


class InMemoryOutboxIntentPort:
    """Small committed intent sink used by unit tests and local composition."""

    def __init__(self) -> None:
        self.intents: list[OutboxIntent] = []

    def enqueue(self, intent: OutboxIntent) -> None:
        self.intents.append(intent)


class _StagedOutboxIntentPort:
    def __init__(self, committed: InMemoryOutboxIntentPort) -> None:
        self._committed = committed
        self.pending: list[OutboxIntent] = []

    def enqueue(self, intent: OutboxIntent) -> None:
        self.pending.append(intent)


class InMemoryEnrollmentRepository:
    """Deterministic async repository with the same uniqueness boundaries."""

    def __init__(self) -> None:
        self.commands: dict[tuple[UUID, UUID, str, str], CommandIdempotency] = {}
        self.enrollments: dict[UUID, Enrollment] = {}
        self.provenance: dict[UUID, EnrollmentProvenance] = {}
        self.entitlements: dict[UUID, Entitlement] = {}
        self.free_policies: dict[tuple[UUID, UUID, UUID], EnrollmentPolicyInput] = {}
        self.manual_policies: dict[tuple[UUID, UUID, UUID, UUID], EnrollmentPolicyInput] = {}

    def clone(self) -> InMemoryEnrollmentRepository:
        return copy.deepcopy(self)

    def adopt(self, other: InMemoryEnrollmentRepository) -> None:
        self.commands = copy.deepcopy(other.commands)
        self.enrollments = copy.deepcopy(other.enrollments)
        self.provenance = copy.deepcopy(other.provenance)
        self.entitlements = copy.deepcopy(other.entitlements)
        self.free_policies = copy.deepcopy(other.free_policies)
        self.manual_policies = copy.deepcopy(other.manual_policies)

    def set_free_enrollment_policy(
        self,
        *,
        tenant_id: UUID,
        person_id: UUID,
        program_version_id: UUID,
        policy: EnrollmentPolicyInput,
    ) -> None:
        self.free_policies[(tenant_id, person_id, program_version_id)] = copy.deepcopy(policy)

    def set_manual_grant_policy(
        self,
        *,
        actor_person_id: UUID,
        tenant_id: UUID,
        subject_person_id: UUID,
        program_version_id: UUID,
        policy: EnrollmentPolicyInput,
    ) -> None:
        self.manual_policies[
            (actor_person_id, tenant_id, subject_person_id, program_version_id)
        ] = copy.deepcopy(policy)

    async def get_idempotency(
        self,
        *,
        tenant_id: UUID,
        actor_person_id: UUID,
        operation: str,
        idempotency_key: str,
        for_update: bool = False,
    ) -> CommandIdempotency | None:
        del for_update
        return self.commands.get((tenant_id, actor_person_id, operation, idempotency_key))

    async def claim_idempotency(self, command: CommandIdempotency) -> None:
        key = (
            command.tenant_id,
            command.actor_person_id,
            command.operation,
            command.idempotency_key,
        )
        if key in self.commands:
            raise UniqueConstraintViolation("idempotency scope key already exists")
        self.commands[key] = command

    async def load_free_enrollment_policy(
        self,
        *,
        actor_person_id: UUID,
        subject_person_id: UUID,
        tenant_id: UUID,
        program_version_id: UUID,
        now: datetime,
    ) -> EnrollmentPolicyInput:
        del actor_person_id, now
        policy = self.free_policies.get((tenant_id, subject_person_id, program_version_id))
        if policy is None:
            return EnrollmentPolicyInput(
                membership=MembershipPolicyInput(
                    person_id=subject_person_id,
                    tenant_id=tenant_id,
                    active=False,
                    tenant_active=False,
                    role=None,
                ),
                program_version=ProgramVersionPolicyInput(
                    id=program_version_id,
                    tenant_id=tenant_id,
                    published=False,
                    immutable=False,
                ),
                eligibility=EligibilityPolicyInput(
                    person_id=subject_person_id,
                    age_gate_passed=None,
                    eligibility_passed=None,
                    prerequisites_satisfied=None,
                    controlled_gaps=(),
                ),
            )
        return copy.deepcopy(policy)

    async def load_manual_grant_policy(
        self,
        *,
        actor_person_id: UUID,
        subject_person_id: UUID,
        tenant_id: UUID,
        program_version_id: UUID,
        now: datetime,
    ) -> EnrollmentPolicyInput:
        del now
        policy = self.manual_policies.get(
            (actor_person_id, tenant_id, subject_person_id, program_version_id)
        )
        if policy is None:
            raise ManualGrantAuthorizationDeniedError(
                "manual grant authorization was not resolved by the server"
            )
        return copy.deepcopy(policy)

    async def find_enrollment(
        self,
        *,
        tenant_id: UUID,
        person_id: UUID,
        program_version_id: UUID,
    ) -> Enrollment | None:
        return next(
            (
                enrollment
                for enrollment in self.enrollments.values()
                if enrollment.tenant_id == tenant_id
                and enrollment.person_id == person_id
                and enrollment.program_version_id == program_version_id
            ),
            None,
        )

    async def save_records(
        self,
        enrollment: Enrollment,
        provenance: EnrollmentProvenance,
        entitlement: Entitlement,
    ) -> None:
        duplicate = await self.find_enrollment(
            tenant_id=enrollment.tenant_id,
            person_id=enrollment.person_id,
            program_version_id=enrollment.program_version_id,
        )
        if duplicate is not None:
            raise UniqueConstraintViolation("enrollment uniqueness constraint rejected the write")
        if enrollment.id in self.enrollments:
            raise UniqueConstraintViolation("enrollment id already exists")
        if entitlement.id in self.entitlements or provenance.id in self.provenance:
            raise UniqueConstraintViolation("enrollment record id already exists")
        self.enrollments[enrollment.id] = enrollment
        self.provenance[provenance.id] = provenance
        self.entitlements[entitlement.id] = entitlement

    async def load_command_result(self, command: CommandIdempotency) -> EnrollmentResult | None:
        if (
            command.result_enrollment_id is None
            or command.result_entitlement_id is None
            or command.result_provenance_id is None
        ):
            return None
        enrollment = self.enrollments.get(command.result_enrollment_id)
        provenance = self.provenance.get(command.result_provenance_id)
        entitlement = self.entitlements.get(command.result_entitlement_id)
        if enrollment is None or provenance is None or entitlement is None:
            return None
        expected_identity = (
            command.tenant_id,
            command.subject_person_id,
            command.program_version_id,
            command.program_id,
            command.program_scope,
            command.program_owner_key,
        )
        if (
            (
                enrollment.tenant_id,
                enrollment.person_id,
                enrollment.program_version_id,
                enrollment.program_id,
                enrollment.program_scope,
                enrollment.program_owner_key,
            )
            != expected_identity
            or provenance.enrollment_id != enrollment.id
            or provenance.command_idempotency_id != command.id
            or entitlement.enrollment_id != enrollment.id
            or entitlement.provenance_id != provenance.id
        ):
            return None
        return EnrollmentResult(
            enrollment_id=enrollment.id,
            entitlement_id=entitlement.id,
            provenance_id=provenance.id,
            command_idempotency_id=command.id,
            created=False,
            replayed=True,
        )


class InMemoryEnrollmentUnitOfWork:
    """Transactional in-memory UoW for policy and replay tests."""

    def __init__(
        self,
        store: InMemoryEnrollmentRepository,
        outbox: InMemoryOutboxIntentPort | None = None,
    ) -> None:
        self._store = store
        self.repository: EnrollmentRepository = store.clone()
        self._outbox_sink = outbox or InMemoryOutboxIntentPort()
        self.outbox = _StagedOutboxIntentPort(self._outbox_sink)
        self.events: list[EventEnvelope] = []
        self._committed = False

    async def __aenter__(self) -> InMemoryEnrollmentUnitOfWork:
        return self

    async def __aexit__(self, exc_type: Any, exc_value: Any, traceback: Any) -> None:
        if exc_type is not None or not self._committed:
            await self.rollback()

    def add_event(self, event: EventEnvelope) -> None:
        self.events.append(event)

    async def commit(self) -> None:
        repository = self.repository
        if not isinstance(repository, InMemoryEnrollmentRepository):
            raise EnrollmentPersistenceError("in-memory enrollment repository was not initialized")
        self._store.adopt(repository)
        self._outbox_sink.intents.extend(self.outbox.pending)
        self._committed = True

    async def rollback(self) -> None:
        self.outbox.pending.clear()
        self.events.clear()


class EnrollmentCommandService:
    """Create explicit access through audited, idempotent transactions only."""

    def __init__(
        self,
        uow_factory: Callable[[], EnrollmentUnitOfWork] | None = None,
        *,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._uow_factory = uow_factory
        self._clock = clock

    async def enroll_free(
        self,
        command: FreeEnrollmentCommand,
        *,
        uow: EnrollmentUnitOfWork | None = None,
    ) -> EnrollmentResult:
        """Execute the self-only explicit free-enrollment command."""

        self._validate_free_command(command)
        return await self._run(
            operation=FREE_ENROLLMENT_OPERATION,
            actor_person_id=command.actor_person_id,
            tenant_id=command.tenant_id,
            idempotency_key=command.idempotency_key,
            request_payload=_free_request_payload(command),
            source=EnrollmentSource.FREE_SELF.value,
            subject_person_id=command.subject_person_id,
            program_version_id=command.program_version_id,
            policy=None,
            reason=None,
            uow=uow,
        )

    async def grant_manual(
        self,
        command: ManualEnrollmentGrantCommand,
        *,
        uow: EnrollmentUnitOfWork | None = None,
    ) -> EnrollmentResult:
        """Execute the later named manual-grant seam with an audit reason."""

        self._validate_manual_command(command)
        return await self._run(
            operation=MANUAL_GRANT_OPERATION,
            actor_person_id=command.actor_person_id,
            tenant_id=command.tenant_id,
            idempotency_key=command.idempotency_key,
            request_payload=_manual_request_payload(command),
            source=EnrollmentSource.MANUAL_GRANT.value,
            subject_person_id=command.subject_person_id,
            program_version_id=command.program_version_id,
            policy=command.policy,
            reason=command.reason.strip(),
            uow=uow,
        )

    async def create_free_enrollment(
        self,
        command: FreeEnrollmentCommand,
        *,
        uow: EnrollmentUnitOfWork | None = None,
    ) -> EnrollmentResult:
        """Descriptive alias for :meth:`enroll_free`."""

        return await self.enroll_free(command, uow=uow)

    async def manual_grant(
        self,
        command: ManualEnrollmentGrantCommand,
        *,
        uow: EnrollmentUnitOfWork | None = None,
    ) -> EnrollmentResult:
        """Descriptive alias for :meth:`grant_manual`."""

        return await self.grant_manual(command, uow=uow)

    async def _run(
        self,
        *,
        operation: str,
        actor_person_id: UUID,
        tenant_id: UUID,
        idempotency_key: str,
        request_payload: dict[str, Any],
        source: str,
        subject_person_id: UUID,
        program_version_id: UUID,
        policy: EnrollmentPolicyInput | None,
        reason: str | None,
        uow: EnrollmentUnitOfWork | None,
    ) -> EnrollmentResult:
        if uow is not None:
            return await self._execute(
                uow=uow,
                operation=operation,
                actor_person_id=actor_person_id,
                tenant_id=tenant_id,
                idempotency_key=idempotency_key,
                request_payload=request_payload,
                source=source,
                subject_person_id=subject_person_id,
                program_version_id=program_version_id,
                policy=policy,
                reason=reason,
            )
        if self._uow_factory is None:
            raise EnrollmentPersistenceError("an enrollment unit-of-work factory is required")
        async with self._uow_factory() as transaction:
            try:
                result = await self._execute(
                    uow=transaction,
                    operation=operation,
                    actor_person_id=actor_person_id,
                    tenant_id=tenant_id,
                    idempotency_key=idempotency_key,
                    request_payload=request_payload,
                    source=source,
                    subject_person_id=subject_person_id,
                    program_version_id=program_version_id,
                    policy=policy,
                    reason=reason,
                )
                await transaction.commit()
                return result
            except BaseException:
                await transaction.rollback()
                raise

    async def _execute(
        self,
        *,
        uow: EnrollmentUnitOfWork,
        operation: str,
        actor_person_id: UUID,
        tenant_id: UUID,
        idempotency_key: str,
        request_payload: dict[str, Any],
        source: str,
        subject_person_id: UUID,
        program_version_id: UUID,
        policy: EnrollmentPolicyInput | None,
        reason: str | None,
    ) -> EnrollmentResult:
        now = self._clock()
        if source == EnrollmentSource.FREE_SELF.value:
            policy = await uow.repository.load_free_enrollment_policy(
                actor_person_id=actor_person_id,
                subject_person_id=subject_person_id,
                tenant_id=tenant_id,
                program_version_id=program_version_id,
                now=now,
            )
            _validate_policy_scope(
                policy=policy,
                subject_person_id=subject_person_id,
                tenant_id=tenant_id,
                program_version_id=program_version_id,
                require_eligibility=True,
            )
        elif policy is None:
            raise EnrollmentPersistenceError("manual enrollment requires resolved policy facts")
        request_digest = _request_digest(request_payload)
        existing = await uow.repository.get_idempotency(
            tenant_id=tenant_id,
            actor_person_id=actor_person_id,
            operation=operation,
            idempotency_key=idempotency_key,
            for_update=True,
        )
        if existing is not None:
            return await _replay_or_reject(uow.repository, existing, request_digest)

        catalog_scope, catalog_tenant_id, catalog_owner_key = _program_identity(
            policy.program_version, tenant_id
        )
        catalog_program_id = policy.program_version.program_id
        if catalog_program_id is None:
            raise ProgramVersionPolicyDeniedError(
                "canonical program-version identity must include its program"
            )

        command = CommandIdempotency(
            id=uuid4(),
            tenant_id=tenant_id,
            actor_person_id=actor_person_id,
            subject_person_id=subject_person_id,
            program_version_id=program_version_id,
            program_id=catalog_program_id,
            program_scope=catalog_scope,
            program_tenant_id=catalog_tenant_id,
            program_owner_key=catalog_owner_key,
            operation=operation,
            idempotency_key=idempotency_key,
            request_digest=request_digest,
            status=CommandStatus.PENDING.value,
        )
        try:
            await uow.repository.claim_idempotency(command)
        except UniqueConstraintViolation:
            existing = await uow.repository.get_idempotency(
                tenant_id=tenant_id,
                actor_person_id=actor_person_id,
                operation=operation,
                idempotency_key=idempotency_key,
                for_update=True,
            )
            if existing is None:
                raise EnrollmentPersistenceError(
                    "idempotency claim raced but its canonical row was unavailable"
                ) from None
            return await _replay_or_reject(uow.repository, existing, request_digest)

        existing_enrollment = await uow.repository.find_enrollment(
            tenant_id=tenant_id,
            person_id=subject_person_id,
            program_version_id=program_version_id,
        )
        if existing_enrollment is not None:
            raise DuplicateEnrollmentError(
                "the learner is already enrolled in this program version"
            )

        enrollment = Enrollment(
            id=uuid4(),
            tenant_id=tenant_id,
            person_id=subject_person_id,
            program_version_id=program_version_id,
            program_id=catalog_program_id,
            program_scope=catalog_scope,
            program_tenant_id=catalog_tenant_id,
            program_owner_key=catalog_owner_key,
            source=source,
            status=EnrollmentStatus.ACTIVE.value,
            enrolled_at=now,
            created_at=now,
            updated_at=now,
        )
        provenance = EnrollmentProvenance(
            id=uuid4(),
            tenant_id=tenant_id,
            enrollment_id=enrollment.id,
            person_id=subject_person_id,
            actor_person_id=actor_person_id,
            program_version_id=program_version_id,
            program_id=catalog_program_id,
            program_scope=catalog_scope,
            program_tenant_id=catalog_tenant_id,
            program_owner_key=catalog_owner_key,
            command_idempotency_id=command.id,
            source=source,
            reason=reason,
            audit_event_name="audit.enrollment.created.v1",
            policy_inputs=_policy_to_json(policy),
            controlled_gaps=list(_controlled_gaps(policy)),
            created_at=now,
        )
        entitlement = Entitlement(
            id=uuid4(),
            tenant_id=tenant_id,
            person_id=subject_person_id,
            enrollment_id=enrollment.id,
            provenance_id=provenance.id,
            program_version_id=program_version_id,
            program_id=catalog_program_id,
            program_scope=catalog_scope,
            program_tenant_id=catalog_tenant_id,
            program_owner_key=catalog_owner_key,
            status=EntitlementStatus.ACTIVE.value,
            granted_at=now,
            created_at=now,
            updated_at=now,
        )
        try:
            await uow.repository.save_records(enrollment, provenance, entitlement)
        except UniqueConstraintViolation as exc:
            existing_enrollment = await uow.repository.find_enrollment(
                tenant_id=tenant_id,
                person_id=subject_person_id,
                program_version_id=program_version_id,
            )
            if existing_enrollment is not None:
                raise DuplicateEnrollmentError(
                    "a concurrent command already enrolled this learner"
                ) from exc
            raise EnrollmentPersistenceError("enrollment records could not be persisted") from exc

        command.status = CommandStatus.COMPLETED.value
        command.result_enrollment_id = enrollment.id
        command.result_entitlement_id = entitlement.id
        command.result_provenance_id = provenance.id
        command.completed_at = now
        uow.add_event(_audit_event(enrollment, provenance, command))
        uow.outbox.enqueue(_welcome_intent(enrollment, entitlement, provenance, command))
        return EnrollmentResult(
            enrollment_id=enrollment.id,
            entitlement_id=entitlement.id,
            provenance_id=provenance.id,
            command_idempotency_id=command.id,
            created=True,
            replayed=False,
        )

    @staticmethod
    def _validate_free_command(command: FreeEnrollmentCommand) -> None:
        _validate_command_ids(
            actor_person_id=command.actor_person_id,
            subject_person_id=command.subject_person_id,
            tenant_id=command.tenant_id,
            program_version_id=command.program_version_id,
            idempotency_key=command.idempotency_key,
        )
        if command.source != EnrollmentSource.FREE_SELF.value:
            raise EnrollmentSourceDeniedError(
                "only the explicit free_self command source may use free enrollment"
            )
        if command.actor_person_id != command.subject_person_id:
            raise ActorSubjectMismatchError("free enrollment is self-only")

    @staticmethod
    def _validate_manual_command(command: ManualEnrollmentGrantCommand) -> None:
        _validate_command_ids(
            actor_person_id=command.actor_person_id,
            subject_person_id=command.subject_person_id,
            tenant_id=command.tenant_id,
            program_version_id=command.program_version_id,
            idempotency_key=command.idempotency_key,
        )
        if command.source != EnrollmentSource.MANUAL_GRANT.value:
            raise EnrollmentSourceDeniedError(
                "manual access must use the named manual_grant command source"
            )
        if not command.reason.strip():
            raise ManualGrantAuthorizationDeniedError("manual grants require a non-blank reason")
        _validate_policy_scope(
            policy=command.policy,
            subject_person_id=command.subject_person_id,
            tenant_id=command.tenant_id,
            program_version_id=command.program_version_id,
            require_eligibility=False,
            actor_person_id=command.actor_person_id,
        )


class AsyncEnrollmentApplication:
    """Production free-enrollment command over a caller-owned AsyncSession."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._session = session
        self._clock = clock

    def _require_transaction(self) -> None:
        transaction = self._session.get_transaction()
        sync_transaction = None if transaction is None else transaction.sync_transaction
        if (
            sync_transaction is None
            or sync_transaction.origin is not SessionTransactionOrigin.BEGIN
        ):
            raise EnrollmentTransactionRequiredError(
                "enrollment commands require an explicit caller-owned AsyncSession transaction"
            )

    @staticmethod
    def _canonical_free_command(
        command: FreeEnrollmentCommand, actor: ActorContext
    ) -> FreeEnrollmentCommand:
        """Bind the request to a trusted actor before any database work."""

        if actor.tenant_id is None:
            raise EnrollmentAuthorizationError("enrollment requires a selected tenant")
        if (
            command.actor_person_id != actor.person_id
            or command.subject_person_id != actor.person_id
        ):
            raise ActorSubjectMismatchError("free enrollment is self-only and actor-bound")
        if command.tenant_id != actor.tenant_id:
            raise CrossTenantEnrollmentError("enrollment tenant must come from the actor context")
        return replace(
            command,
            actor_person_id=actor.person_id,
            subject_person_id=actor.person_id,
            tenant_id=actor.tenant_id,
        )

    @staticmethod
    def _canonical_manual_command(
        command: ManualEnrollmentGrantCommand, actor: ActorContext
    ) -> ManualEnrollmentGrantCommand:
        if actor.tenant_id is None:
            raise ManualGrantAuthorizationDeniedError("manual grant requires a selected tenant")
        if ENROLLMENT_GRANT_PERMISSION not in actor.permissions:
            raise ManualGrantAuthorizationDeniedError(
                "manual grant requires the enrollment_grant permission"
            )
        if command.actor_person_id != actor.person_id:
            raise ManualGrantAuthorizationDeniedError(
                "manual grant actor must match the trusted actor context"
            )
        if command.tenant_id != actor.tenant_id:
            raise CrossTenantEnrollmentError("manual grant tenant must come from the actor context")
        return replace(command, actor_person_id=actor.person_id, tenant_id=actor.tenant_id)

    async def enroll_free(
        self, command: FreeEnrollmentCommand, *, actor: ActorContext
    ) -> EnrollmentResult:
        """Derive, lock, and persist free access from a trusted actor context."""

        self._require_transaction()
        canonical_command = self._canonical_free_command(command, actor)
        async with self._session.begin_nested():
            transaction = SqlAlchemyEnrollmentUnitOfWork(self._session)
            async with transaction:
                result = await EnrollmentCommandService(clock=self._clock).enroll_free(
                    canonical_command,
                    uow=transaction,
                )
                await transaction.commit()
                return result

    async def grant_manual(
        self, command: ManualEnrollmentGrantCommand, *, actor: ActorContext
    ) -> EnrollmentResult:
        """Create a manual grant only from live actor membership authority."""

        self._require_transaction()
        canonical_command = self._canonical_manual_command(command, actor)
        async with self._session.begin_nested():
            transaction = SqlAlchemyEnrollmentUnitOfWork(self._session)
            async with transaction:
                if actor.tenant_id is None:
                    raise ManualGrantAuthorizationDeniedError(
                        "manual grant requires a selected tenant"
                    )
                canonical_policy = await transaction.repository.load_manual_grant_policy(
                    actor_person_id=actor.person_id,
                    subject_person_id=canonical_command.subject_person_id,
                    tenant_id=actor.tenant_id,
                    program_version_id=canonical_command.program_version_id,
                    now=self._clock(),
                )
                result = await EnrollmentCommandService(clock=self._clock).grant_manual(
                    replace(canonical_command, policy=canonical_policy),
                    uow=transaction,
                )
                await transaction.commit()
                return result


def _validate_command_ids(
    *,
    actor_person_id: UUID,
    subject_person_id: UUID,
    tenant_id: UUID,
    program_version_id: UUID,
    idempotency_key: str,
) -> None:
    del actor_person_id, subject_person_id, tenant_id, program_version_id
    if not idempotency_key.strip():
        raise EnrollmentError("idempotency key must not be blank")


def _validate_policy_scope(
    *,
    policy: EnrollmentPolicyInput,
    subject_person_id: UUID,
    tenant_id: UUID,
    program_version_id: UUID,
    require_eligibility: bool,
    actor_person_id: UUID | None = None,
) -> None:
    membership = policy.membership
    if membership.person_id != subject_person_id:
        raise CrossSubjectEnrollmentError("membership policy input is for another subject")
    if membership.tenant_id != tenant_id:
        raise CrossTenantEnrollmentError("membership policy input is for another tenant")
    if not membership.tenant_active or not membership.active:
        raise MembershipPolicyDeniedError("an active tenant membership is required")
    if membership.role != LEARNER_ROLE:
        raise MembershipPolicyDeniedError("the subject must have an explicit learner membership")

    program_version = policy.program_version
    if program_version.id != program_version_id:
        raise CrossSubjectEnrollmentError("program-version policy input does not match the request")
    scope, program_tenant_id, owner_key = _program_identity(program_version, tenant_id)
    if scope == "tenant" and program_tenant_id != tenant_id:
        raise CrossTenantEnrollmentError("program-version policy input is for another tenant")
    if scope == "global" and program_tenant_id is not None:
        raise CrossTenantEnrollmentError("global program versions cannot carry an owner tenant")
    if (
        program_version.program_owner_key is not None
        and program_version.program_owner_key != owner_key
    ):
        raise CrossTenantEnrollmentError("program-version owner key does not match its scope")
    if program_version.owner_key is not None and program_version.owner_key != owner_key:
        raise CrossTenantEnrollmentError("program-version owner key does not match its scope")
    if not program_version.published or not program_version.immutable:
        raise ProgramVersionPolicyDeniedError(
            "only a published immutable program version may be pinned"
        )

    if require_eligibility:
        eligibility = policy.eligibility
        if eligibility is None or eligibility.person_id != subject_person_id:
            raise CrossSubjectEnrollmentError("eligibility policy input is for another subject")
        if (
            eligibility.age_gate_passed is not True
            or eligibility.eligibility_passed is not True
            or eligibility.prerequisites_satisfied is not True
        ):
            raise EligibilityPolicyDeniedError(
                "age, eligibility, and prerequisite policy inputs must all be true"
            )
        if not eligibility.policy_version.strip():
            raise EligibilityPolicyDeniedError("eligibility policy version is required")
    if actor_person_id is not None:
        grant = policy.manual_grant
        if grant is None or grant.actor_person_id != actor_person_id:
            raise CrossSubjectEnrollmentError("manual-grant authorization is for another actor")
        if grant.tenant_id != tenant_id:
            raise CrossTenantEnrollmentError("manual-grant authorization is for another tenant")
        if not grant.active or not grant.authorized or grant.role not in MANUAL_GRANT_ROLES:
            raise ManualGrantAuthorizationDeniedError(
                "manual grant requires an active support/admin/owner authorization input"
            )


def _program_identity(
    policy: ProgramVersionPolicyInput,
    learner_tenant_id: UUID,
) -> tuple[str, UUID | None, UUID]:
    """Normalize policy aliases into the non-null catalog owner identity."""

    scope = policy.program_scope or policy.scope
    if scope is None:
        # Existing policy fixtures describe a learner-tenant-owned version by
        # putting the learner tenant in ``tenant_id``.
        scope = "tenant"
    if scope not in {"global", "tenant"}:
        raise ProgramVersionPolicyDeniedError("program-version scope is unsupported")
    program_tenant_id = policy.program_tenant_id
    if scope == "tenant":
        declared_tenant_id = program_tenant_id or policy.tenant_id
        if declared_tenant_id != learner_tenant_id:
            raise CrossTenantEnrollmentError("program-version policy input is for another tenant")
        program_tenant_id = declared_tenant_id
    if scope == "global":
        program_tenant_id = None
    owner_key = policy.program_owner_key or policy.owner_key
    expected_owner = GLOBAL_CATALOG_OWNER_KEY if scope == "global" else program_tenant_id
    if expected_owner is None:
        raise ProgramVersionPolicyDeniedError("tenant catalog versions require an owner tenant")
    if owner_key is None:
        owner_key = expected_owner
    if owner_key != expected_owner:
        raise ProgramVersionPolicyDeniedError("program-version owner key is inconsistent")
    return scope, program_tenant_id, owner_key


def _free_request_payload(command: FreeEnrollmentCommand) -> dict[str, Any]:
    return {
        "operation": FREE_ENROLLMENT_OPERATION,
        "actor_person_id": str(command.actor_person_id),
        "subject_person_id": str(command.subject_person_id),
        "tenant_id": str(command.tenant_id),
        "program_version_id": str(command.program_version_id),
        "source": command.source,
    }


def _manual_request_payload(command: ManualEnrollmentGrantCommand) -> dict[str, Any]:
    return {
        "operation": MANUAL_GRANT_OPERATION,
        "actor_person_id": str(command.actor_person_id),
        "subject_person_id": str(command.subject_person_id),
        "tenant_id": str(command.tenant_id),
        "program_version_id": str(command.program_version_id),
        "source": command.source,
        "reason": command.reason.strip(),
        "policy": _policy_to_json(command.policy),
    }


def _policy_to_json(policy: EnrollmentPolicyInput) -> dict[str, Any]:
    membership = policy.membership
    program_version = policy.program_version
    result: dict[str, Any] = {
        "membership": {
            "person_id": str(membership.person_id),
            "tenant_id": str(membership.tenant_id),
            "active": membership.active,
            "tenant_active": membership.tenant_active,
            "role": membership.role,
        },
        "program_version": {
            "id": str(program_version.id),
            "tenant_id": str(program_version.tenant_id),
            "published": program_version.published,
            "immutable": program_version.immutable,
            "program_id": (
                str(program_version.program_id) if program_version.program_id is not None else None
            ),
            "scope": program_version.program_scope or program_version.scope,
            "program_tenant_id": (
                str(program_version.program_tenant_id)
                if program_version.program_tenant_id is not None
                else None
            ),
            "program_owner_key": (
                str(program_version.program_owner_key or program_version.owner_key)
                if (program_version.program_owner_key or program_version.owner_key) is not None
                else None
            ),
        },
    }
    if policy.eligibility is not None:
        eligibility = policy.eligibility
        result["eligibility"] = {
            "person_id": str(eligibility.person_id),
            "age_gate_passed": eligibility.age_gate_passed,
            "eligibility_passed": eligibility.eligibility_passed,
            "prerequisites_satisfied": eligibility.prerequisites_satisfied,
            "policy_version": eligibility.policy_version,
            "controlled_gaps": list(eligibility.controlled_gaps),
            "evidence": dict(eligibility.evidence),
        }
    if policy.manual_grant is not None:
        grant = policy.manual_grant
        result["manual_grant"] = {
            "actor_person_id": str(grant.actor_person_id),
            "tenant_id": str(grant.tenant_id),
            "active": grant.active,
            "authorized": grant.authorized,
            "role": grant.role,
        }
    return result


def _controlled_gaps(policy: EnrollmentPolicyInput) -> tuple[str, ...]:
    if policy.eligibility is None:
        return ()
    return tuple(policy.eligibility.controlled_gaps)


def _request_digest(payload: Mapping[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


async def _replay_or_reject(
    repository: EnrollmentRepository,
    command: CommandIdempotency,
    request_digest: str,
) -> EnrollmentResult:
    if command.request_digest != request_digest:
        raise IdempotencyConflictError(
            "the idempotency key is already bound to a different canonical request"
        )
    if command.status == CommandStatus.PENDING.value:
        raise CommandInProgressError("the idempotency key is owned by an unfinished command")
    if command.status != CommandStatus.COMPLETED.value:
        raise IdempotencyStateError("the idempotency row has an unsupported status")
    if (
        command.result_enrollment_id is None
        or command.result_entitlement_id is None
        or command.result_provenance_id is None
    ):
        raise IdempotencyStateError("completed idempotency rows must retain all result identifiers")
    result = await repository.load_command_result(command)
    if result is None:
        raise IdempotencyStateError(
            "completed idempotency result identifiers do not resolve to the bound identity"
        )
    return result


def _audit_event(
    enrollment: Enrollment,
    provenance: EnrollmentProvenance,
    command: CommandIdempotency,
) -> EventEnvelope:
    return EventEnvelope(
        name=provenance.audit_event_name,
        category=EventCategory.AUDIT,
        aggregate_type="enrollment",
        aggregate_id=enrollment.id,
        tenant_id=enrollment.tenant_id,
        payload={
            "enrollment_id": str(enrollment.id),
            "entitlement_source": enrollment.source,
            "provenance_id": str(provenance.id),
            "actor_person_id": str(provenance.actor_person_id),
            "subject_person_id": str(provenance.person_id),
            "program_version_id": str(enrollment.program_version_id),
            "command_idempotency_id": str(command.id),
            "controlled_gaps": list(provenance.controlled_gaps),
        },
    )


def _welcome_intent(
    enrollment: Enrollment,
    entitlement: Entitlement,
    provenance: EnrollmentProvenance,
    command: CommandIdempotency,
) -> OutboxIntent:
    return OutboxIntent(
        name="enrollment.welcome.requested.v1",
        aggregate_type="enrollment",
        aggregate_id=enrollment.id,
        tenant_id=enrollment.tenant_id,
        dedupe_key=f"{command.operation}:{command.id}",
        payload={
            "enrollment_id": str(enrollment.id),
            "entitlement_id": str(entitlement.id),
            "provenance_id": str(provenance.id),
            "person_id": str(enrollment.person_id),
            "program_version_id": str(enrollment.program_version_id),
            "source": enrollment.source,
        },
    )


__all__ = [
    "ActorSubjectMismatchError",
    "AsyncEnrollmentApplication",
    "CommandInProgressError",
    "CONTROLLED_GAP_AGE_ELIGIBILITY",
    "CONTROLLED_POLICY_VERSION",
    "CrossSubjectEnrollmentError",
    "CrossTenantEnrollmentError",
    "DuplicateEnrollmentError",
    "EligibilityPolicyDeniedError",
    "EligibilityPolicyInput",
    "EnrollmentCommandService",
    "EnrollmentError",
    "EnrollmentPersistenceError",
    "EnrollmentPolicyInput",
    "EnrollmentRepository",
    "EnrollmentResult",
    "EnrollmentSourceDeniedError",
    "EnrollmentUnitOfWork",
    "EnrollmentTransactionRequiredError",
    "FREE_ENROLLMENT_OPERATION",
    "FreeEnrollmentCommand",
    "IdempotencyConflictError",
    "IdempotencyStateError",
    "InMemoryEnrollmentRepository",
    "InMemoryEnrollmentUnitOfWork",
    "InMemoryOutboxIntentPort",
    "LEARNER_ROLE",
    "MANUAL_GRANT_OPERATION",
    "ManualEnrollmentGrantCommand",
    "ManualGrantAuthorizationDeniedError",
    "ManualGrantPolicyInput",
    "MembershipPolicyDeniedError",
    "MembershipPolicyInput",
    "OutboxIntent",
    "OutboxIntentPort",
    "ProgramVersionPolicyDeniedError",
    "ProgramVersionPolicyInput",
    "SqlAlchemyEnrollmentRepository",
    "SqlAlchemyEnrollmentUnitOfWork",
    "UniqueConstraintViolation",
    "utc_now",
]
