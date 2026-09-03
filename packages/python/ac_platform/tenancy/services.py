"""Pure tenant and membership application services."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID, uuid4

from ac_platform.identity.models import PersonStatus
from ac_platform.tenancy.models import MembershipRole, MembershipStatus, TenantStatus


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _now(value: datetime | None) -> datetime:
    return _as_utc(value or datetime.now(UTC))


def _required_text(value: str, field_name: str, maximum: int) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} must not be blank")
    if len(normalized) > maximum:
        raise ValueError(f"{field_name} must be at most {maximum} characters")
    return normalized


class TenantServiceError(Exception):
    """Base exception for expected tenancy-domain failures."""


class TenantAccessDeniedError(TenantServiceError):
    """The actor has no active, supported membership in the requested tenant."""


class TenantContextRequiredError(TenantAccessDeniedError):
    """A tenant-owned operation was attempted without an explicit context."""


class UnsupportedMembershipRoleError(TenantAccessDeniedError):
    """The membership role is not part of the first-slice supported policy."""


class TenantNotFoundError(TenantAccessDeniedError):
    """The requested tenant does not exist in the tenancy port."""


class MembershipAlreadyExistsError(TenantServiceError):
    """The composite tenant/person membership key is already present."""


class MembershipNotFoundError(TenantServiceError):
    """The requested composite tenant/person membership does not exist."""


class TenantConcurrencyError(TenantServiceError):
    """A tenant or membership compare-and-swap write lost a race."""


@dataclass(frozen=True, slots=True)
class TenantSnapshot:
    id: UUID
    slug: str
    name: str
    status: str = TenantStatus.ACTIVE.value
    revision: int = 0


@dataclass(frozen=True, slots=True)
class MembershipSnapshot:
    tenant_id: UUID
    person_id: UUID
    role: str
    status: str = MembershipStatus.ACTIVE.value
    ended_at: datetime | None = None
    revision: int = 0

    @property
    def is_active(self) -> bool:
        return self.status == MembershipStatus.ACTIVE.value and self.ended_at is None


@dataclass(frozen=True, slots=True)
class TenantContext:
    """Explicit actor/tenant/role context returned after policy checks."""

    person_id: UUID
    tenant_id: UUID
    membership_role: str


class TenantStore(Protocol):
    """Persistence port needed by tenant-context policy."""

    def get_tenant(self, tenant_id: UUID) -> TenantSnapshot | None: ...

    def get_tenant_by_slug(self, slug: str) -> TenantSnapshot | None: ...

    def get_membership(self, tenant_id: UUID, person_id: UUID) -> MembershipSnapshot | None: ...

    def save_tenant(self, tenant: TenantSnapshot) -> None: ...

    def save_membership(self, membership: MembershipSnapshot) -> None: ...

    def list_memberships(self, person_id: UUID) -> Sequence[MembershipSnapshot]: ...

    def get_person_status(self, person_id: UUID) -> str | None: ...


class TrustedTenantContextPort(Protocol):
    """Trusted, server-side port for live tenant authorization checks."""

    def select(self, actor_person_id: UUID, tenant_id: UUID | None) -> TenantContext: ...

    def validate(
        self,
        context: TenantContext,
        actor_person_id: UUID,
        requested_tenant_id: UUID | None,
    ) -> TenantContext: ...


class InMemoryTenantStore:
    """Deterministic tenant port for pure application tests."""

    def __init__(
        self,
        tenants: Iterable[TenantSnapshot] = (),
        memberships: Iterable[MembershipSnapshot] = (),
        person_statuses: dict[UUID, str] | None = None,
    ) -> None:
        self.tenants: dict[UUID, TenantSnapshot] = {tenant.id: tenant for tenant in tenants}
        self.memberships: dict[tuple[UUID, UUID], MembershipSnapshot] = {
            (membership.tenant_id, membership.person_id): membership for membership in memberships
        }
        self.person_statuses = dict(person_statuses or {})

    def get_tenant(self, tenant_id: UUID) -> TenantSnapshot | None:
        return self.tenants.get(tenant_id)

    def get_tenant_by_slug(self, slug: str) -> TenantSnapshot | None:
        return next((tenant for tenant in self.tenants.values() if tenant.slug == slug), None)

    def get_membership(self, tenant_id: UUID, person_id: UUID) -> MembershipSnapshot | None:
        return self.memberships.get((tenant_id, person_id))

    def save_tenant(self, tenant: TenantSnapshot) -> None:
        self.tenants[tenant.id] = tenant

    def save_membership(self, membership: MembershipSnapshot) -> None:
        key = (membership.tenant_id, membership.person_id)
        if key in self.memberships:
            raise MembershipAlreadyExistsError("membership composite key already exists")
        self.memberships[key] = membership

    def replace_membership(self, membership: MembershipSnapshot) -> None:
        self.memberships[(membership.tenant_id, membership.person_id)] = membership

    def list_memberships(self, person_id: UUID) -> Sequence[MembershipSnapshot]:
        return tuple(
            membership
            for membership in self.memberships.values()
            if membership.person_id == person_id
        )

    def get_person_status(self, person_id: UUID) -> str | None:
        """Return the known lifecycle state for the context actor."""

        if person_id in self.person_statuses:
            return self.person_statuses[person_id]
        if any(membership.person_id == person_id for membership in self.memberships.values()):
            return "active"
        return None


SUPPORTED_CONTEXT_ROLES: frozenset[str] = frozenset(role.value for role in MembershipRole)


class TenantContextService:
    """Select and validate one explicit active tenant context for an actor."""

    def __init__(self, store: TenantStore) -> None:
        self._store = store

    def select(
        self,
        actor_person_id: UUID,
        tenant_id: UUID | None,
    ) -> TenantContext:
        if tenant_id is None:
            raise TenantContextRequiredError("tenant context must be selected explicitly")
        if self._store.get_person_status(actor_person_id) != PersonStatus.ACTIVE.value:
            raise TenantAccessDeniedError("person account is unavailable")
        tenant = self._store.get_tenant(tenant_id)
        if tenant is None:
            raise TenantNotFoundError("tenant does not exist")
        if tenant.status != TenantStatus.ACTIVE.value:
            raise TenantAccessDeniedError("tenant is not active")
        membership = self._store.get_membership(tenant_id, actor_person_id)
        if membership is None or not membership.is_active:
            raise TenantAccessDeniedError("person has no active membership in this tenant")
        if membership.role not in SUPPORTED_CONTEXT_ROLES:
            raise UnsupportedMembershipRoleError("membership role cannot select tenant context")
        return TenantContext(
            person_id=actor_person_id,
            tenant_id=tenant_id,
            membership_role=membership.role,
        )

    def validate(
        self,
        context: TenantContext,
        actor_person_id: UUID,
        requested_tenant_id: UUID | None,
    ) -> TenantContext:
        """Re-check a previously selected context at a tenant boundary."""

        if requested_tenant_id is None:
            raise TenantContextRequiredError("tenant context must be explicit")
        if context.person_id != actor_person_id or context.tenant_id != requested_tenant_id:
            raise TenantAccessDeniedError("tenant context does not belong to this actor/request")
        return self.select(actor_person_id, requested_tenant_id)

    def has_active_membership(self, person_id: UUID, tenant_id: UUID) -> bool:
        tenant = self._store.get_tenant(tenant_id)
        membership = self._store.get_membership(tenant_id, person_id)
        return (
            self._store.get_person_status(person_id) == PersonStatus.ACTIVE.value
            and tenant is not None
            and tenant.status == TenantStatus.ACTIVE.value
            and membership is not None
            and membership.is_active
            and membership.role in SUPPORTED_CONTEXT_ROLES
        )

    def revalidate(self, person_id: UUID, tenant_id: UUID) -> TenantContext:
        """Re-read and validate live tenant state for authentication."""

        return self.select(person_id, tenant_id)


class TenantService:
    """Create and update the small tenant aggregate used by context policy."""

    def __init__(self, store: TenantStore) -> None:
        self._store = store

    def create(
        self,
        *,
        slug: str,
        name: str,
        tenant_id: UUID | None = None,
    ) -> TenantSnapshot:
        normalized_slug = _required_text(slug, "slug", 63)
        normalized_name = _required_text(name, "name", 200)
        if self._store.get_tenant_by_slug(normalized_slug) is not None:
            raise TenantServiceError("tenant slug already exists")
        tenant = TenantSnapshot(
            id=tenant_id or uuid4(),
            slug=normalized_slug,
            name=normalized_name,
        )
        self._store.save_tenant(tenant)
        return tenant


class MembershipService:
    """Add memberships using the composite ``(tenant_id, person_id)`` boundary."""

    def __init__(self, store: TenantStore) -> None:
        self._store = store

    def add(
        self,
        *,
        tenant_id: UUID,
        person_id: UUID,
        role: MembershipRole | str,
        now: datetime | None = None,
    ) -> MembershipSnapshot:
        tenant = self._store.get_tenant(tenant_id)
        if tenant is None:
            raise TenantNotFoundError("tenant does not exist")
        if tenant.status != TenantStatus.ACTIVE.value:
            raise TenantAccessDeniedError("membership cannot be added to an inactive tenant")
        if self._store.get_person_status(person_id) != PersonStatus.ACTIVE.value:
            raise TenantAccessDeniedError("membership cannot be added for an unavailable person")
        existing = self._store.get_membership(tenant_id, person_id)
        if existing is not None:
            raise MembershipAlreadyExistsError("membership composite key already exists")
        role_value = role.value if isinstance(role, MembershipRole) else role.strip()
        if role_value not in SUPPORTED_CONTEXT_ROLES:
            raise UnsupportedMembershipRoleError("membership role is not supported")
        del now  # MembershipSnapshot intentionally carries no creation timestamp.
        membership = MembershipSnapshot(
            tenant_id=tenant_id,
            person_id=person_id,
            role=role_value,
        )
        self._store.save_membership(membership)
        return membership


__all__ = [
    "InMemoryTenantStore",
    "MembershipAlreadyExistsError",
    "MembershipNotFoundError",
    "MembershipService",
    "MembershipSnapshot",
    "SUPPORTED_CONTEXT_ROLES",
    "TenantAccessDeniedError",
    "TenantContext",
    "TenantContextRequiredError",
    "TenantContextService",
    "TenantConcurrencyError",
    "TenantNotFoundError",
    "TenantService",
    "TenantServiceError",
    "TenantSnapshot",
    "TenantStore",
    "TrustedTenantContextPort",
    "UnsupportedMembershipRoleError",
]
