from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from ac_platform.tenancy.models import MembershipRole, MembershipStatus, TenantStatus
from ac_platform.tenancy.services import (
    InMemoryTenantStore,
    MembershipAlreadyExistsError,
    MembershipService,
    MembershipSnapshot,
    TenantAccessDeniedError,
    TenantContextRequiredError,
    TenantContextService,
    TenantService,
    TenantSnapshot,
    UnsupportedMembershipRoleError,
)


def test_authz_04_allows_explicit_context_for_active_supported_membership() -> None:
    person_id = uuid4()
    tenant_id = uuid4()
    store = InMemoryTenantStore(
        tenants=[TenantSnapshot(id=tenant_id, slug="ac", name="Authority Closers")],
        memberships=[
            MembershipSnapshot(
                tenant_id=tenant_id,
                person_id=person_id,
                role=MembershipRole.LEARNER.value,
            )
        ],
    )

    context = TenantContextService(store).select(person_id, tenant_id)

    assert context.person_id == person_id
    assert context.tenant_id == tenant_id
    assert context.membership_role == MembershipRole.LEARNER.value


def test_authz_04_denies_omitted_unrelated_inactive_and_unsupported_contexts() -> None:
    person_id = uuid4()
    other_person_id = uuid4()
    active_tenant_id = uuid4()
    unrelated_tenant_id = uuid4()
    inactive_tenant_id = uuid4()
    unsupported_tenant_id = uuid4()
    store = InMemoryTenantStore(
        tenants=[
            TenantSnapshot(id=active_tenant_id, slug="active", name="Active"),
            TenantSnapshot(id=unrelated_tenant_id, slug="other", name="Other"),
            TenantSnapshot(id=inactive_tenant_id, slug="inactive", name="Inactive"),
            TenantSnapshot(id=unsupported_tenant_id, slug="future", name="Future"),
        ],
        memberships=[
            MembershipSnapshot(
                tenant_id=active_tenant_id,
                person_id=other_person_id,
                role=MembershipRole.LEARNER.value,
            ),
            MembershipSnapshot(
                tenant_id=inactive_tenant_id,
                person_id=person_id,
                role=MembershipRole.LEARNER.value,
                status=MembershipStatus.INACTIVE.value,
                ended_at=datetime.now(UTC),
            ),
            MembershipSnapshot(
                tenant_id=unsupported_tenant_id,
                person_id=person_id,
                role="future-role",
            ),
        ],
    )
    service = TenantContextService(store)

    with pytest.raises(TenantContextRequiredError):
        service.select(person_id, None)
    with pytest.raises(TenantAccessDeniedError):
        service.select(person_id, unrelated_tenant_id)
    with pytest.raises(TenantAccessDeniedError):
        service.select(person_id, inactive_tenant_id)
    with pytest.raises(UnsupportedMembershipRoleError):
        service.select(person_id, unsupported_tenant_id)


def test_ten_neg_context_cannot_be_reused_by_another_person_or_tenant() -> None:
    person_id = uuid4()
    other_person_id = uuid4()
    tenant_id = uuid4()
    other_tenant_id = uuid4()
    store = InMemoryTenantStore(
        tenants=[
            TenantSnapshot(id=tenant_id, slug="one", name="One"),
            TenantSnapshot(id=other_tenant_id, slug="two", name="Two"),
        ],
        memberships=[
            MembershipSnapshot(
                tenant_id=tenant_id,
                person_id=person_id,
                role=MembershipRole.ADMIN.value,
            ),
            MembershipSnapshot(
                tenant_id=other_tenant_id,
                person_id=other_person_id,
                role=MembershipRole.ADMIN.value,
            ),
        ],
    )
    service = TenantContextService(store)
    context = service.select(person_id, tenant_id)

    with pytest.raises(TenantAccessDeniedError):
        service.validate(context, other_person_id, tenant_id)
    with pytest.raises(TenantAccessDeniedError):
        service.validate(context, person_id, other_tenant_id)
    assert not service.has_active_membership(person_id, other_tenant_id)


def test_tenant_and_membership_services_preserve_composite_boundary() -> None:
    person_id = uuid4()
    store = InMemoryTenantStore(person_statuses={person_id: "active"})
    tenant = TenantService(store).create(slug="ac", name="Authority Closers", tenant_id=uuid4())
    membership = MembershipService(store).add(
        tenant_id=tenant.id,
        person_id=person_id,
        role=MembershipRole.SUPPORT,
    )

    assert membership.tenant_id == tenant.id
    assert store.get_membership(tenant.id, person_id) == membership
    with pytest.raises(MembershipAlreadyExistsError):
        MembershipService(store).add(
            tenant_id=tenant.id,
            person_id=person_id,
            role=MembershipRole.SUPPORT,
        )


def test_inactive_tenant_denies_context_even_with_active_membership() -> None:
    person_id = uuid4()
    tenant_id = uuid4()
    store = InMemoryTenantStore(
        tenants=[
            TenantSnapshot(
                id=tenant_id,
                slug="suspended",
                name="Suspended",
                status=TenantStatus.SUSPENDED.value,
            )
        ],
        memberships=[
            MembershipSnapshot(
                tenant_id=tenant_id,
                person_id=person_id,
                role=MembershipRole.OWNER.value,
            )
        ],
    )

    with pytest.raises(TenantAccessDeniedError):
        TenantContextService(store).select(person_id, tenant_id)


@pytest.mark.parametrize("status", ["suspended", "deleted"])
def test_person_lifecycle_denies_context_even_with_active_membership(status: str) -> None:
    person_id = uuid4()
    tenant_id = uuid4()
    store = InMemoryTenantStore(
        tenants=[TenantSnapshot(id=tenant_id, slug="ac", name="Authority Closers")],
        memberships=[
            MembershipSnapshot(
                tenant_id=tenant_id,
                person_id=person_id,
                role=MembershipRole.LEARNER.value,
            )
        ],
        person_statuses={person_id: status},
    )

    with pytest.raises(TenantAccessDeniedError, match="person account"):
        TenantContextService(store).select(person_id, tenant_id)
    assert not TenantContextService(store).has_active_membership(person_id, tenant_id)
    with pytest.raises(TenantAccessDeniedError, match="unavailable person"):
        MembershipService(store).add(
            tenant_id=tenant_id,
            person_id=person_id,
            role=MembershipRole.LEARNER,
        )
