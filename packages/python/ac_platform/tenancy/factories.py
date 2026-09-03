"""Production tenancy composition.

These factories require a caller-owned SQLAlchemy session.  They intentionally
do not fall back to the in-memory test store.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session as DbSession

from ac_platform.tenancy.repositories import (
    AsyncSqlAlchemyTenantRepository,
    SqlAlchemyTenantStore,
)
from ac_platform.tenancy.services import TenantContextService


def create_tenant_store(session: DbSession) -> SqlAlchemyTenantStore:
    """Build the durable synchronous tenant store for one transaction."""

    return SqlAlchemyTenantStore(session)


def create_tenant_context_service(session: DbSession) -> TenantContextService:
    """Build the trusted live context service for one transaction."""

    return TenantContextService(create_tenant_store(session))


def create_tenant_repository(session: AsyncSession) -> AsyncSqlAlchemyTenantRepository:
    """Build the durable async tenant repository for one transaction."""

    return AsyncSqlAlchemyTenantRepository(session)


create_production_tenant_store = create_tenant_store
create_production_tenant_context_service = create_tenant_context_service
create_production_tenant_repository = create_tenant_repository


__all__ = [
    "create_production_tenant_context_service",
    "create_production_tenant_repository",
    "create_production_tenant_store",
    "create_tenant_context_service",
    "create_tenant_repository",
    "create_tenant_store",
]
