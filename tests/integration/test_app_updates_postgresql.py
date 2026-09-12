"""Real PostgreSQL isolation for durable learner app-update read receipts."""

from __future__ import annotations

import asyncio
import hashlib
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from ac_platform.app_updates.application import AppUpdatesApplication
from ac_platform.app_updates.models import AppUpdateReadReceipt
from ac_platform.identity.models import Person
from ac_platform.identity.models import Session as IdentitySession
from ac_platform.kernel.authz import ActorContext
from ac_platform.tenancy.models import Membership, Tenant
from tests.integration.test_media_delivery_renewal_postgresql import _run_async
from tests.integration.test_media_delivery_renewal_postgresql import (
    postgres_harness as postgres_harness,  # noqa: F401 - disposable migrated schema fixture
)

NOW = datetime(2026, 9, 10, 12, tzinfo=UTC)


class ScalarBarrierDatabase:
    """Hold the first receipt lookup until both real transactions saw no row."""

    def __init__(self, database: AsyncSession, barrier: asyncio.Barrier) -> None:
        self.database = database
        self.barrier = barrier
        self.first_scalar = True

    def __getattr__(self, name: str) -> Any:
        return getattr(self.database, name)

    async def scalar(self, statement: Any) -> Any:
        result = await self.database.scalar(statement)
        if self.first_scalar:
            self.first_scalar = False
            assert result is None
            await asyncio.wait_for(self.barrier.wait(), timeout=5)
        return result


def test_read_receipt_persists_across_sessions_without_cross_account_or_tenant_leak(
    postgres_harness: Any,
) -> None:  # noqa: F811
    async def run() -> None:
        engine = create_async_engine(postgres_harness.schema_url, hide_parameters=True)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        try:
            tenant_id, other_tenant_id = uuid4(), uuid4()
            person_id, other_person_id = uuid4(), uuid4()
            first_session, second_session, other_session, other_tenant_session = (
                uuid4(),
                uuid4(),
                uuid4(),
                uuid4(),
            )
            async with sessions() as database, database.begin():
                database.add_all(
                    [
                        Tenant(id=tenant_id, slug=f"updates-{tenant_id.hex}", name="Updates A"),
                        Tenant(
                            id=other_tenant_id,
                            slug=f"updates-{other_tenant_id.hex}",
                            name="Updates B",
                        ),
                        Person(
                            id=person_id,
                            email=f"updates-{person_id.hex}@example.test",
                            email_verified_at=NOW,
                        ),
                        Person(
                            id=other_person_id,
                            email=f"updates-{other_person_id.hex}@example.test",
                            email_verified_at=NOW,
                        ),
                    ]
                )
                await database.flush()
                database.add_all(
                    [
                        Membership(tenant_id=tenant_id, person_id=person_id, role="learner"),
                        Membership(
                            tenant_id=tenant_id,
                            person_id=other_person_id,
                            role="learner",
                        ),
                        Membership(
                            tenant_id=other_tenant_id,
                            person_id=person_id,
                            role="learner",
                        ),
                    ]
                )
                await database.flush()
                for session_id, member_id, selected_tenant in (
                    (first_session, person_id, tenant_id),
                    (second_session, person_id, tenant_id),
                    (other_session, other_person_id, tenant_id),
                    (other_tenant_session, person_id, other_tenant_id),
                ):
                    database.add(
                        IdentitySession(
                            id=session_id,
                            person_id=member_id,
                            selected_tenant_id=selected_tenant,
                            token_hash=hashlib.sha256(session_id.bytes).digest(),
                            created_at=NOW,
                            expires_at=NOW + timedelta(hours=1),
                        )
                    )

            first = ActorContext(person_id, first_session, tenant_id)
            async with sessions() as database, database.begin():
                marked = await AppUpdatesApplication(database, clock=lambda: NOW).mark_read(
                    first,
                    "app-updates-v0-2-alpha",
                )
                assert marked["unread_count"] == 0

            cases = (
                (ActorContext(person_id, second_session, tenant_id), True),
                (ActorContext(other_person_id, other_session, tenant_id), False),
                (ActorContext(person_id, other_tenant_session, other_tenant_id), False),
            )
            for current, expected_read in cases:
                async with sessions() as database, database.begin():
                    result = await AppUpdatesApplication(
                        database,
                        clock=lambda: NOW,
                    ).list_updates(current)
                    assert result["items"][0]["read"] is expected_read
                    assert result["unread_count"] == (0 if expected_read else 1)

            async with sessions() as database, database.begin():
                retried = await AppUpdatesApplication(database, clock=lambda: NOW).mark_read(
                    ActorContext(person_id, second_session, tenant_id),
                    "app-updates-v0-2-alpha",
                )
                assert retried["unread_count"] == 0
        finally:
            await engine.dispose()

    _run_async(run())


def test_concurrent_read_retries_return_one_durable_receipt(postgres_harness: Any) -> None:
    async def run() -> None:
        engine = create_async_engine(
            postgres_harness.schema_url,
            pool_size=2,
            max_overflow=0,
            hide_parameters=True,
        )
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        try:
            tenant_id, person_id = uuid4(), uuid4()
            session_ids = (uuid4(), uuid4())
            async with sessions() as database, database.begin():
                database.add_all(
                    [
                        Tenant(id=tenant_id, slug=f"race-{tenant_id.hex}", name="Updates race"),
                        Person(
                            id=person_id,
                            email=f"race-{person_id.hex}@example.test",
                            email_verified_at=NOW,
                        ),
                    ]
                )
                await database.flush()
                database.add(Membership(tenant_id=tenant_id, person_id=person_id, role="learner"))
                await database.flush()
                for session_id in session_ids:
                    database.add(
                        IdentitySession(
                            id=session_id,
                            person_id=person_id,
                            selected_tenant_id=tenant_id,
                            token_hash=hashlib.sha256(session_id.bytes).digest(),
                            created_at=NOW,
                            expires_at=NOW + timedelta(hours=1),
                        )
                    )

            barrier = asyncio.Barrier(2)

            async def mark(session_id: UUID) -> dict[str, Any]:
                async with sessions() as database, database.begin():
                    guarded = ScalarBarrierDatabase(database, barrier)
                    return await AppUpdatesApplication(  # type: ignore[arg-type]
                        guarded,
                        clock=lambda: NOW,
                    ).mark_read(
                        ActorContext(person_id, session_id, tenant_id),
                        "app-updates-v0-2-alpha",
                    )

            results = await asyncio.wait_for(
                asyncio.gather(*(mark(session_id) for session_id in session_ids)),
                timeout=10,
            )
            assert [result["unread_count"] for result in results] == [0, 0]
            assert all(result["items"][0]["read"] is True for result in results)
            async with sessions() as database:
                count = await database.scalar(
                    select(func.count())
                    .select_from(AppUpdateReadReceipt)
                    .where(
                        AppUpdateReadReceipt.tenant_id == tenant_id,
                        AppUpdateReadReceipt.person_id == person_id,
                        AppUpdateReadReceipt.release_id == "app-updates-v0-2-alpha",
                    )
                )
                assert count == 1
        finally:
            await engine.dispose()

    _run_async(run())
