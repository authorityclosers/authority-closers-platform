"""Transactional first-tenant and owner bootstrap application service."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import SessionTransactionOrigin

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


__all__ = ["BootstrapApplication", "BootstrapError", "BootstrapResult"]
