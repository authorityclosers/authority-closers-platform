"""Tenant, membership, and explicit tenant-context domain contracts.

Models are loaded eagerly. Composition and service symbols are resolved lazily
so direct model imports cannot re-enter the opposite package root.
"""

from importlib import import_module

from ac_platform.tenancy.models import (
    Membership,
    MembershipRole,
    MembershipStatus,
    Tenant,
    TenantStatus,
)

_LAZY_PUBLIC_IMPORTS = {
    "AsyncLearnerProvisioningApplication": (
        "ac_platform.tenancy.learner_provisioning",
        "AsyncLearnerProvisioningApplication",
    ),
    "LearnerProvisioningError": (
        "ac_platform.tenancy.learner_provisioning",
        "LearnerProvisioningError",
    ),
    "LearnerProvisioningResult": (
        "ac_platform.tenancy.learner_provisioning",
        "LearnerProvisioningResult",
    ),
    "create_production_tenant_context_service": (
        "ac_platform.tenancy.factories",
        "create_production_tenant_context_service",
    ),
    "create_production_tenant_repository": (
        "ac_platform.tenancy.factories",
        "create_production_tenant_repository",
    ),
    "create_production_tenant_store": (
        "ac_platform.tenancy.factories",
        "create_production_tenant_store",
    ),
    "create_tenant_context_service": (
        "ac_platform.tenancy.factories",
        "create_tenant_context_service",
    ),
    "create_tenant_repository": ("ac_platform.tenancy.factories", "create_tenant_repository"),
    "create_tenant_store": ("ac_platform.tenancy.factories", "create_tenant_store"),
    "AsyncSqlAlchemyTenantRepository": (
        "ac_platform.tenancy.repositories",
        "AsyncSqlAlchemyTenantRepository",
    ),
    "SqlAlchemyTenantRepository": (
        "ac_platform.tenancy.repositories",
        "SqlAlchemyTenantRepository",
    ),
    "SqlAlchemyTenantStore": ("ac_platform.tenancy.repositories", "SqlAlchemyTenantStore"),
}

for _name in (
    "InMemoryTenantStore",
    "MembershipAlreadyExistsError",
    "MembershipNotFoundError",
    "MembershipService",
    "MembershipSnapshot",
    "TenantAccessDeniedError",
    "TenantConcurrencyError",
    "TenantContext",
    "TenantContextRequiredError",
    "TenantContextService",
    "TenantNotFoundError",
    "TenantService",
    "TenantServiceError",
    "TenantSnapshot",
    "TenantStore",
    "TrustedTenantContextPort",
    "UnsupportedMembershipRoleError",
):
    _LAZY_PUBLIC_IMPORTS[_name] = ("ac_platform.tenancy.services", _name)


def __getattr__(name: str) -> object:
    """Resolve non-model public names only when a caller asks for them."""

    target = _LAZY_PUBLIC_IMPORTS.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name, attribute_name = target
    value = getattr(import_module(module_name), attribute_name)
    globals()[name] = value
    return value


__all__ = [
    "AsyncLearnerProvisioningApplication",
    "InMemoryTenantStore",
    "AsyncSqlAlchemyTenantRepository",
    "SqlAlchemyTenantRepository",
    "SqlAlchemyTenantStore",
    "Membership",
    "MembershipAlreadyExistsError",
    "MembershipNotFoundError",
    "MembershipRole",
    "MembershipService",
    "MembershipSnapshot",
    "MembershipStatus",
    "LearnerProvisioningError",
    "LearnerProvisioningResult",
    "Tenant",
    "TenantAccessDeniedError",
    "TenantContext",
    "TenantContextRequiredError",
    "TenantContextService",
    "TenantConcurrencyError",
    "TenantNotFoundError",
    "TenantService",
    "TenantServiceError",
    "TenantSnapshot",
    "TenantStatus",
    "TenantStore",
    "TrustedTenantContextPort",
    "UnsupportedMembershipRoleError",
    "create_production_tenant_context_service",
    "create_production_tenant_repository",
    "create_production_tenant_store",
    "create_tenant_context_service",
    "create_tenant_repository",
    "create_tenant_store",
]
