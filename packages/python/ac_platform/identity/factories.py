"""Identity composition roots.

Production composition is async-only and operates inside one caller-owned
``AsyncSession`` transaction.  The synchronous store factory is explicitly
test-only and cannot be mistaken for the production application boundary.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session as DbSession

from ac_platform.identity.application import AsyncIdentityApplication
from ac_platform.identity.repositories import (
    AsyncSqlAlchemyIdentityRepository,
    SqlAlchemyIdentityStore,
)


@dataclass(frozen=True, slots=True)
class IdentityServices:
    """Production identity services bound to one caller-owned transaction."""

    application: AsyncIdentityApplication
    repository: AsyncSqlAlchemyIdentityRepository


def create_identity_repository(session: AsyncSession) -> AsyncSqlAlchemyIdentityRepository:
    """Build the durable async repository for one caller-owned transaction."""

    return AsyncSqlAlchemyIdentityRepository(session)


def create_production_identity_services(
    session: AsyncSession,
    *,
    token_pepper: bytes | str,
    session_ttl: timedelta = timedelta(days=30),
) -> IdentityServices:
    """Compose the only production identity application boundary."""

    application = AsyncIdentityApplication(
        session,
        token_pepper=token_pepper,
        session_ttl=session_ttl,
    )
    return IdentityServices(
        application=application,
        repository=application.repository,
    )


def create_sync_identity_store_for_tests(session: DbSession) -> SqlAlchemyIdentityStore:
    """Build the synchronous adapter used only by focused domain/database tests."""

    return SqlAlchemyIdentityStore(session)


create_identity_services = create_production_identity_services
build_production_identity_services = create_production_identity_services
create_production_identity_repository = create_identity_repository


__all__ = [
    "IdentityServices",
    "build_production_identity_services",
    "create_identity_repository",
    "create_identity_services",
    "create_production_identity_repository",
    "create_production_identity_services",
    "create_sync_identity_store_for_tests",
]
