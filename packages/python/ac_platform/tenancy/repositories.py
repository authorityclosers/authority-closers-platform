"""Durable SQLAlchemy adapters for tenant and membership state."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session as DbSession

from ac_platform.identity.models import Person
from ac_platform.tenancy.models import Membership, Tenant
from ac_platform.tenancy.services import (
    MembershipAlreadyExistsError,
    MembershipNotFoundError,
    MembershipSnapshot,
    TenantConcurrencyError,
    TenantServiceError,
    TenantSnapshot,
    TenantStore,
)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _tenant_snapshot(row: Tenant) -> TenantSnapshot:
    return TenantSnapshot(
        id=row.id,
        slug=row.slug,
        name=row.name,
        status=row.status,
        revision=row.revision,
    )


def _membership_snapshot(row: Membership) -> MembershipSnapshot:
    ended_at = None if row.ended_at is None else _as_utc(row.ended_at)
    return MembershipSnapshot(
        tenant_id=row.tenant_id,
        person_id=row.person_id,
        role=row.role,
        status=row.status,
        ended_at=ended_at,
        revision=row.revision,
    )


class SqlAlchemyTenantStore(TenantStore):
    """Synchronous SQLAlchemy implementation of :class:`TenantStore`."""

    def __init__(self, session: DbSession) -> None:
        self._session = session

    def get_tenant(self, tenant_id: UUID) -> TenantSnapshot | None:
        row = cast(
            Tenant | None,
            self._session.scalar(
                select(Tenant)
                .where(Tenant.id == tenant_id)
                .execution_options(populate_existing=True)
            ),
        )
        return None if row is None else _tenant_snapshot(row)

    def get_person_status(self, person_id: UUID) -> str | None:
        return self._session.scalar(select(Person.status).where(Person.id == person_id))

    def get_tenant_by_slug(self, slug: str) -> TenantSnapshot | None:
        row = cast(
            Tenant | None,
            self._session.scalar(
                select(Tenant)
                .where(Tenant.slug == slug)
                .order_by(Tenant.id)
                .execution_options(populate_existing=True)
            ),
        )
        return None if row is None else _tenant_snapshot(row)

    def get_membership(self, tenant_id: UUID, person_id: UUID) -> MembershipSnapshot | None:
        row = cast(
            Membership | None,
            self._session.scalar(
                select(Membership)
                .where(Membership.tenant_id == tenant_id, Membership.person_id == person_id)
                .execution_options(populate_existing=True)
            ),
        )
        return None if row is None else _membership_snapshot(row)

    def save_tenant(self, tenant: TenantSnapshot) -> None:
        row = cast(
            Tenant | None,
            self._session.scalar(
                select(Tenant)
                .where(Tenant.id == tenant.id)
                .execution_options(populate_existing=True)
            ),
        )
        if row is None:
            if tenant.revision != 0:
                raise TenantConcurrencyError("new tenants must start at revision zero")
            try:
                with self._session.begin_nested():
                    self._session.add(
                        Tenant(
                            id=tenant.id,
                            slug=tenant.slug,
                            name=tenant.name,
                            status=tenant.status,
                            revision=tenant.revision,
                        )
                    )
                    self._session.flush()
            except IntegrityError as exc:
                raise TenantServiceError(
                    "tenant insert violated a uniqueness or scope constraint"
                ) from exc
            return
        if tenant.revision != row.revision + 1:
            raise TenantConcurrencyError("tenant revision is stale")
        try:
            with self._session.begin_nested():
                result = cast(
                    CursorResult[Any],
                    self._session.execute(
                        update(Tenant)
                        .where(Tenant.id == tenant.id, Tenant.revision == row.revision)
                        .values(
                            slug=tenant.slug,
                            name=tenant.name,
                            status=tenant.status,
                            revision=tenant.revision,
                            updated_at=datetime.now(UTC),
                        )
                    ),
                )
                if result.rowcount != 1:
                    raise TenantConcurrencyError("tenant revision is stale")
                self._session.flush()
        except TenantConcurrencyError:
            raise
        except IntegrityError as exc:
            raise TenantServiceError("tenant slug already exists") from exc

    def save_membership(self, membership: MembershipSnapshot) -> None:
        if self.get_membership(membership.tenant_id, membership.person_id) is not None:
            raise MembershipAlreadyExistsError("membership composite key already exists")
        if membership.revision != 0:
            raise TenantConcurrencyError("new memberships must start at revision zero")
        try:
            with self._session.begin_nested():
                self._session.add(
                    Membership(
                        tenant_id=membership.tenant_id,
                        person_id=membership.person_id,
                        role=membership.role,
                        status=membership.status,
                        ended_at=membership.ended_at,
                        revision=membership.revision,
                    )
                )
                self._session.flush()
        except IntegrityError as exc:
            raise MembershipAlreadyExistsError(
                "membership composite key already exists or its foreign key is invalid"
            ) from exc

    def replace_membership(self, membership: MembershipSnapshot) -> None:
        row = self.get_membership(membership.tenant_id, membership.person_id)
        if row is None:
            raise MembershipNotFoundError("membership does not exist")
        if membership.revision != row.revision + 1:
            raise TenantConcurrencyError("membership revision is stale")
        try:
            with self._session.begin_nested():
                result = cast(
                    CursorResult[Any],
                    self._session.execute(
                        update(Membership)
                        .where(
                            Membership.tenant_id == membership.tenant_id,
                            Membership.person_id == membership.person_id,
                            Membership.revision == row.revision,
                        )
                        .values(
                            role=membership.role,
                            status=membership.status,
                            ended_at=membership.ended_at,
                            revision=membership.revision,
                            updated_at=datetime.now(UTC),
                        )
                    ),
                )
                if result.rowcount != 1:
                    raise TenantConcurrencyError("membership revision is stale")
                self._session.flush()
        except TenantConcurrencyError:
            raise
        except IntegrityError as exc:
            raise TenantServiceError("membership update violated a scope constraint") from exc

    def list_memberships(self, person_id: UUID) -> Sequence[MembershipSnapshot]:
        rows = self._session.scalars(
            select(Membership)
            .where(Membership.person_id == person_id)
            .order_by(Membership.tenant_id)
            .execution_options(populate_existing=True)
        )
        return tuple(_membership_snapshot(row) for row in rows)


class AsyncSqlAlchemyTenantRepository:
    """Async SQLAlchemy tenant repository used by production composition."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_tenant(self, tenant_id: UUID) -> TenantSnapshot | None:
        row = cast(
            Tenant | None,
            await self._session.scalar(
                select(Tenant)
                .where(Tenant.id == tenant_id)
                .execution_options(populate_existing=True)
            ),
        )
        return None if row is None else _tenant_snapshot(row)

    async def get_person_status(self, person_id: UUID) -> str | None:
        return cast(
            str | None,
            await self._session.scalar(select(Person.status).where(Person.id == person_id)),
        )

    async def get_tenant_by_slug(self, slug: str) -> TenantSnapshot | None:
        row = cast(
            Tenant | None,
            await self._session.scalar(
                select(Tenant)
                .where(Tenant.slug == slug)
                .order_by(Tenant.id)
                .execution_options(populate_existing=True)
            ),
        )
        return None if row is None else _tenant_snapshot(row)

    async def get_membership(self, tenant_id: UUID, person_id: UUID) -> MembershipSnapshot | None:
        row = cast(
            Membership | None,
            await self._session.scalar(
                select(Membership)
                .where(Membership.tenant_id == tenant_id, Membership.person_id == person_id)
                .execution_options(populate_existing=True)
            ),
        )
        return None if row is None else _membership_snapshot(row)

    async def save_tenant(self, tenant: TenantSnapshot) -> None:
        row = cast(
            Tenant | None,
            await self._session.scalar(
                select(Tenant)
                .where(Tenant.id == tenant.id)
                .execution_options(populate_existing=True)
            ),
        )
        if row is None:
            if tenant.revision != 0:
                raise TenantConcurrencyError("new tenants must start at revision zero")
            try:
                async with self._session.begin_nested():
                    self._session.add(
                        Tenant(
                            id=tenant.id,
                            slug=tenant.slug,
                            name=tenant.name,
                            status=tenant.status,
                            revision=tenant.revision,
                        )
                    )
                    await self._session.flush()
            except IntegrityError as exc:
                raise TenantServiceError(
                    "tenant insert violated a uniqueness or scope constraint"
                ) from exc
            return
        if tenant.revision != row.revision + 1:
            raise TenantConcurrencyError("tenant revision is stale")
        try:
            async with self._session.begin_nested():
                result = cast(
                    CursorResult[Any],
                    await self._session.execute(
                        update(Tenant)
                        .where(Tenant.id == tenant.id, Tenant.revision == row.revision)
                        .values(
                            slug=tenant.slug,
                            name=tenant.name,
                            status=tenant.status,
                            revision=tenant.revision,
                            updated_at=datetime.now(UTC),
                        )
                    ),
                )
                if result.rowcount != 1:
                    raise TenantConcurrencyError("tenant revision is stale")
                await self._session.flush()
        except TenantConcurrencyError:
            raise
        except IntegrityError as exc:
            raise TenantServiceError("tenant slug already exists") from exc

    async def save_membership(self, membership: MembershipSnapshot) -> None:
        if await self.get_membership(membership.tenant_id, membership.person_id) is not None:
            raise MembershipAlreadyExistsError("membership composite key already exists")
        if membership.revision != 0:
            raise TenantConcurrencyError("new memberships must start at revision zero")
        try:
            async with self._session.begin_nested():
                self._session.add(
                    Membership(
                        tenant_id=membership.tenant_id,
                        person_id=membership.person_id,
                        role=membership.role,
                        status=membership.status,
                        ended_at=membership.ended_at,
                        revision=membership.revision,
                    )
                )
                await self._session.flush()
        except IntegrityError as exc:
            raise MembershipAlreadyExistsError(
                "membership composite key already exists or its foreign key is invalid"
            ) from exc

    async def replace_membership(self, membership: MembershipSnapshot) -> None:
        row = await self.get_membership(membership.tenant_id, membership.person_id)
        if row is None:
            raise MembershipNotFoundError("membership does not exist")
        if membership.revision != row.revision + 1:
            raise TenantConcurrencyError("membership revision is stale")
        try:
            async with self._session.begin_nested():
                result = cast(
                    CursorResult[Any],
                    await self._session.execute(
                        update(Membership)
                        .where(
                            Membership.tenant_id == membership.tenant_id,
                            Membership.person_id == membership.person_id,
                            Membership.revision == row.revision,
                        )
                        .values(
                            role=membership.role,
                            status=membership.status,
                            ended_at=membership.ended_at,
                            revision=membership.revision,
                            updated_at=datetime.now(UTC),
                        )
                    ),
                )
                if result.rowcount != 1:
                    raise TenantConcurrencyError("membership revision is stale")
                await self._session.flush()
        except TenantConcurrencyError:
            raise
        except IntegrityError as exc:
            raise TenantServiceError("membership update violated a scope constraint") from exc

    async def list_memberships(self, person_id: UUID) -> Sequence[MembershipSnapshot]:
        rows = await self._session.scalars(
            select(Membership)
            .where(Membership.person_id == person_id)
            .order_by(Membership.tenant_id)
            .execution_options(populate_existing=True)
        )
        return tuple(_membership_snapshot(row) for row in rows)


SqlAlchemyTenantRepository = AsyncSqlAlchemyTenantRepository


__all__ = [
    "AsyncSqlAlchemyTenantRepository",
    "SqlAlchemyTenantRepository",
    "SqlAlchemyTenantStore",
]
