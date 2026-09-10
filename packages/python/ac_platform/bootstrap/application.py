"""Transactional first-tenant and owner bootstrap application service."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import BigInteger, func, literal, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import SessionTransactionOrigin

from ac_platform.audit.models import AuditEvent
from ac_platform.audit.service import AuditRepository
from ac_platform.identity.models import PersonStatus
from ac_platform.identity.repositories import AsyncSqlAlchemyIdentityRepository
from ac_platform.identity.services import normalize_email
from ac_platform.tenancy.models import MembershipRole, MembershipStatus, TenantStatus
from ac_platform.tenancy.repositories import AsyncSqlAlchemyTenantRepository
from ac_platform.tenancy.services import (
    MembershipAlreadyExistsError,
    MembershipSnapshot,
    TenantServiceError,
    TenantSnapshot,
)


class BootstrapError(Exception):
    """Expected fail-closed bootstrap refusal."""


@dataclass(frozen=True, slots=True)
class BootstrapResult:
    """Safe summary of one committed bootstrap operation."""

    person_id: UUID
    tenant_id: UUID
    tenant_created: bool
    membership_created: bool
    sessions_updated: int


@dataclass(frozen=True, slots=True)
class PublicLearnerTenantBootstrapResult:
    """Safe result for the exact shared self-directed learner context."""

    tenant_id: UUID
    tenant_created: bool


@dataclass(frozen=True, slots=True)
class OperationsTenantBootstrapResult:
    """Committed tenant-only bootstrap summary; never an identity credential."""

    tenant_id: UUID
    tenant_created: bool
    replayed: bool


_OPERATIONS_BOOTSTRAP_ACTION = "tenancy.operations_tenant_bootstrapped"
_OPERATIONS_BOOTSTRAP_LOCK = int.from_bytes(
    hashlib.sha256(b"ac.operations-tenant-bootstrap:v1").digest()[:8],
    byteorder="big",
    signed=True,
)


def _required_text(value: str, field_name: str, maximum: int) -> str:
    normalized = value.strip()
    if not normalized:
        raise BootstrapError(f"{field_name} must not be blank")
    if len(normalized) > maximum:
        raise BootstrapError(f"{field_name} must be at most {maximum} characters")
    return normalized


def _validate_tenant(tenant: TenantSnapshot, *, slug: str, name: str) -> None:
    if tenant.slug != slug or tenant.name != name:
        raise BootstrapError("tenant slug exists with a different name")
    if tenant.status != TenantStatus.ACTIVE.value:
        raise BootstrapError("tenant exists but is not active")


def _validate_owner_membership(membership: MembershipSnapshot) -> None:
    if (
        membership.role != MembershipRole.OWNER.value
        or membership.status != MembershipStatus.ACTIVE.value
        or membership.ended_at is not None
    ):
        raise BootstrapError("existing membership is not an active owner membership")


class BootstrapApplication:
    """Create exactly one explicit tenant/owner scope without identity invention."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._identity = AsyncSqlAlchemyIdentityRepository(session)
        self._tenancy = AsyncSqlAlchemyTenantRepository(session)

    def _require_transaction(self) -> None:
        transaction = self._session.get_transaction()
        sync_transaction = None if transaction is None else transaction.sync_transaction
        if (
            sync_transaction is None
            or sync_transaction.origin is not SessionTransactionOrigin.BEGIN
        ):
            raise BootstrapError(
                "bootstrap requires an explicit caller-owned AsyncSession transaction"
            )

    async def bootstrap_operations_tenant(
        self,
        *,
        command_id: UUID,
        operator_reference: str,
        reason: str,
        tenant_slug: str,
        tenant_name: str,
        operations_tenant_id: UUID | None = None,
    ) -> OperationsTenantBootstrapResult:
        """Create only the control tenant, once, under an immutable operator intent.

        This operator-only boundary breaks the empty-environment tenant cycle.
        It never registers a person or changes identity, membership, capability,
        session, consent or enrollment state. References/reasons must contain
        reviewed, non-secret operator/change references, not credentials.
        """

        self._require_transaction()
        if not isinstance(command_id, UUID):
            raise BootstrapError("command_id must be an explicit UUID")
        slug = _required_text(tenant_slug, "tenant_slug", 63)
        name = _required_text(tenant_name, "tenant_name", 200)
        operator = _required_text(operator_reference, "operator_reference", 160)
        normalized_reason = _required_text(reason, "reason", 500)
        if any(
            ord(character) < 32 or ord(character) == 127
            for text in (slug, name, operator, normalized_reason)
            for character in text
        ):
            raise BootstrapError("operations bootstrap intent must not contain control characters")
        payload = {
            "schema_version": 1,
            "command_id": str(command_id),
            "operator_reference": operator,
            "tenant_slug": slug,
            "tenant_name": name,
        }
        # The target row does not exist yet. Fence the *whole* operator intent
        # before checking history, so concurrent empty-environment calls cannot
        # create different control tenants or acknowledge before the winner commits.
        if self._session.get_bind().dialect.name == "postgresql":
            await self._session.execute(
                select(func.pg_advisory_xact_lock(literal(_OPERATIONS_BOOTSTRAP_LOCK, BigInteger)))
            )
        prior = await self._session.get(AuditEvent, command_id)
        history_id = await self._session.scalar(
            select(AuditEvent.id).where(AuditEvent.action == _OPERATIONS_BOOTSTRAP_ACTION).limit(1)
        )
        if prior is not None:
            if (
                history_id != command_id
                or prior.action != _OPERATIONS_BOOTSTRAP_ACTION
                or prior.actor_type != "operator_bootstrap"
                or prior.actor_person_id is not None
                or prior.session_id is not None
                or prior.resource_type != "tenant"
                or prior.resource_id != str(prior.tenant_id)
                or prior.payload != payload
                or prior.reason != normalized_reason
            ):
                raise BootstrapError("operations bootstrap command conflicts with immutable intent")
            tenant = await self._tenancy.get_tenant_by_slug_for_update(slug)
            if tenant is None or tenant.id != prior.tenant_id:
                raise BootstrapError("the original operations tenant is unavailable")
            _validate_tenant(tenant, slug=slug, name=name)
            if operations_tenant_id is not None and operations_tenant_id != tenant.id:
                raise BootstrapError("configured operations tenant does not match the command")
            return OperationsTenantBootstrapResult(tenant.id, False, True)
        if history_id is not None:
            raise BootstrapError("operations bootstrap history exists; replay the original command")

        tenant = await self._tenancy.get_tenant_by_slug_for_update(slug)
        if operations_tenant_id is not None and (
            tenant is None or tenant.id != operations_tenant_id
        ):
            raise BootstrapError("configured operations tenant does not match the command")
        created = tenant is None
        if tenant is None:
            candidate = TenantSnapshot(id=uuid4(), slug=slug, name=name)
            try:
                await self._tenancy.save_tenant(candidate)
            except TenantServiceError:
                # Existing owner/public-learner commands retain their own locks.
                # If one wins this slug, revalidate it without repairing state.
                tenant = await self._tenancy.get_tenant_by_slug_for_update(slug)
                if tenant is None:
                    raise BootstrapError(
                        "operations tenant creation could not be resolved"
                    ) from None
                created = False
            else:
                tenant = candidate
        _validate_tenant(tenant, slug=slug, name=name)
        await AuditRepository(self._session).append(
            event_id=command_id,
            tenant_id=tenant.id,
            actor_person_id=None,
            actor_type="operator_bootstrap",
            action=_OPERATIONS_BOOTSTRAP_ACTION,
            resource_type="tenant",
            resource_id=tenant.id,
            payload=payload,
            reason=normalized_reason,
        )
        return OperationsTenantBootstrapResult(tenant.id, created, False)

    async def bootstrap_owner(
        self,
        *,
        email: str,
        tenant_slug: str,
        tenant_name: str,
        now: datetime | None = None,
    ) -> BootstrapResult:
        """Bootstrap one already OAuth-verified canonical person transactionally.

        The caller must wrap this command in ``async with session.begin()``.  No
        provider person or provider identity is created by this boundary.
        """

        self._require_transaction()
        normalized_email = normalize_email(email, "email")
        normalized_slug = _required_text(tenant_slug, "tenant_slug", 63)
        normalized_name = _required_text(tenant_name, "tenant_name", 200)
        current_time = now or datetime.now(UTC)
        current_time = (
            current_time.replace(tzinfo=UTC)
            if current_time.tzinfo is None
            else current_time.astimezone(UTC)
        )

        people = await self._identity.find_people_by_exact_email_for_update(normalized_email)
        if not people:
            raise BootstrapError("no canonical person matches the exact normalized email")
        if len(people) != 1:
            raise BootstrapError("exact normalized email matches multiple canonical persons")
        person = people[0]
        if person.status != PersonStatus.ACTIVE.value:
            raise BootstrapError("canonical person is not active")
        if person.email_verified_at is None:
            raise BootstrapError("canonical person email is not verified")
        if not await self._identity.has_provider_identity(person.id):
            raise BootstrapError("canonical person has no existing OAuth provider identity")

        tenant = await self._tenancy.get_tenant_by_slug_for_update(normalized_slug)
        tenant_created = tenant is None
        if tenant is None:
            candidate = TenantSnapshot(
                id=uuid4(),
                slug=normalized_slug,
                name=normalized_name,
                status=TenantStatus.ACTIVE.value,
            )
            try:
                await self._tenancy.save_tenant(candidate)
            except TenantServiceError:
                # A different bootstrap may have won the unique-slug race.
                tenant = await self._tenancy.get_tenant_by_slug_for_update(normalized_slug)
                if tenant is None:
                    raise BootstrapError(
                        "tenant creation raced and canonical tenant is unavailable"
                    ) from None
                tenant_created = False
            else:
                tenant = candidate
        if tenant is None:  # pragma: no cover - defensive narrowing for type checkers
            raise BootstrapError("tenant was not resolved")
        _validate_tenant(tenant, slug=normalized_slug, name=normalized_name)

        membership = await self._tenancy.get_membership_for_update(tenant.id, person.id)
        membership_created = membership is None
        if membership is None:
            candidate_membership = MembershipSnapshot(
                tenant_id=tenant.id,
                person_id=person.id,
                role=MembershipRole.OWNER.value,
                status=MembershipStatus.ACTIVE.value,
            )
            try:
                await self._tenancy.save_membership(candidate_membership)
            except MembershipAlreadyExistsError:
                membership = await self._tenancy.get_membership_for_update(tenant.id, person.id)
                if membership is None:
                    raise BootstrapError(
                        "membership creation raced and canonical membership is unavailable"
                    ) from None
                membership_created = False
            else:
                membership = candidate_membership
        if membership is None:  # pragma: no cover - defensive narrowing for type checkers
            raise BootstrapError("membership was not resolved")
        _validate_owner_membership(membership)

        sessions_updated = await self._identity.select_tenant_for_active_sessions(
            person.id,
            tenant.id,
            now=current_time,
        )
        return BootstrapResult(
            person_id=person.id,
            tenant_id=tenant.id,
            tenant_created=tenant_created,
            membership_created=membership_created,
            sessions_updated=sessions_updated,
        )

    async def bootstrap_public_learner_tenant(
        self,
        *,
        tenant_slug: str,
        tenant_name: str,
        operations_tenant_id: UUID | None = None,
    ) -> PublicLearnerTenantBootstrapResult:
        """Create or validate the dedicated self-directed learner context.

        This operation deliberately creates no person or membership. Runtime
        registration remains the only path that can add an active learner
        membership after verified, versioned consent. Keeping this context
        separate prevents an operations owner role from replacing the
        learner role required by self-enrollment.
        """

        self._require_transaction()
        if operations_tenant_id is None:
            raise BootstrapError(
                "operations tenant id is required to prove public learner tenant isolation"
            )
        operations_tenant = await self._tenancy.get_tenant(operations_tenant_id)
        if operations_tenant is None:
            raise BootstrapError(
                "configured operations control tenant is unavailable; "
                "public learner tenant isolation cannot be proven"
            )
        if operations_tenant.status != TenantStatus.ACTIVE.value:
            raise BootstrapError(
                "configured operations control tenant is not active; "
                "public learner tenant isolation cannot be proven"
            )
        normalized_slug = _required_text(tenant_slug, "tenant_slug", 63)
        normalized_name = _required_text(tenant_name, "tenant_name", 200)
        tenant = await self._tenancy.get_tenant_by_slug_for_update(normalized_slug)
        tenant_created = tenant is None
        if tenant is None:
            candidate = TenantSnapshot(
                id=uuid4(),
                slug=normalized_slug,
                name=normalized_name,
                status=TenantStatus.ACTIVE.value,
            )
            try:
                await self._tenancy.save_tenant(candidate)
            except TenantServiceError:
                tenant = await self._tenancy.get_tenant_by_slug_for_update(normalized_slug)
                if tenant is None:
                    raise BootstrapError(
                        "public learner tenant creation raced and canonical tenant is unavailable"
                    ) from None
                tenant_created = False
            else:
                tenant = candidate
        if tenant is None:  # pragma: no cover - defensive narrowing
            raise BootstrapError("public learner tenant was not resolved")
        _validate_tenant(tenant, slug=normalized_slug, name=normalized_name)
        if tenant.id == operations_tenant_id:
            raise BootstrapError(
                "public learner tenant must be different from the operations control tenant"
            )
        return PublicLearnerTenantBootstrapResult(
            tenant_id=tenant.id,
            tenant_created=tenant_created,
        )


__all__ = [
    "BootstrapApplication",
    "BootstrapError",
    "BootstrapResult",
    "OperationsTenantBootstrapResult",
    "PublicLearnerTenantBootstrapResult",
]
