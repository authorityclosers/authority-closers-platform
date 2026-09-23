"""Fresh-PostgreSQL proof for profile constraints, audit, and phone collisions."""

from __future__ import annotations

import asyncio
import sys
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import inspect, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session

from ac_platform.audit.models import AuditEvent
from ac_platform.audit.service import AuditRepository
from ac_platform.identity.models import Person
from ac_platform.identity.sales_xray_profile import (
    SalesXrayProfileRevisionConflict,
    erase_sales_xray_profile,
    update_sales_xray_profile,
)
from ac_platform.identity.sales_xray_profile_models import SalesXrayProfile
from ac_platform.tenancy.models import Tenant
from tests.integration.test_password_identity_http_postgresql import (
    _Harness,
    _postgres_url,
)
from tests.integration.test_password_identity_http_postgresql import (
    postgres_harness as postgres_harness,  # noqa: F401 - use the isolated migration fixture
)

NOW = datetime(2026, 9, 23, 12, 0, tzinfo=UTC)


def _run_async[T](coroutine) -> T:
    if sys.platform == "win32":
        with asyncio.Runner(loop_factory=asyncio.SelectorEventLoop) as runner:
            return runner.run(coroutine)
    return asyncio.run(coroutine)


@pytest.fixture(scope="module")
def profile_harness(postgres_harness: _Harness) -> _Harness:
    url = _postgres_url()
    if url.host not in {"127.0.0.1", "localhost", "::1"}:
        pytest.fail("profile PostgreSQL acceptance requires a loopback test database")
    return postgres_harness


def test_alembic_schema_matches_the_profile_model(profile_harness: _Harness) -> None:
    inspector = inspect(profile_harness.engine)
    columns = {
        column["name"]
        for column in inspector.get_columns("sales_xray_profiles")
    }
    assert {
        "id",
        "person_id",
        "phone_number_e164",
        "phone_verified_at",
        "admin_collision_review_required",
        "revision",
        "created_at",
        "updated_at",
    } <= columns
    indexes = {index["name"]: index for index in inspector.get_indexes("sales_xray_profiles")}
    verified_index = indexes["uq_sales_xray_profiles_verified_phone"]
    assert verified_index["unique"] is True
    predicate = verified_index["dialect_options"]["postgresql_where"].strip("() ")
    assert predicate == "phone_verified_at IS NOT NULL"
    unique_person = inspector.get_unique_constraints("sales_xray_profiles")
    assert any(item["column_names"] == ["person_id"] for item in unique_person)


def test_postgres_serializes_duplicate_phone_flags_and_preserves_audit(
    profile_harness: _Harness,
) -> None:
    first_id, second_id, tenant_id = uuid4(), uuid4(), uuid4()
    first_session, second_session = None, None
    phone = f"+1{uuid4().int % 10**10:010d}"
    with Session(profile_harness.engine) as database, database.begin():
        database.add_all(
            [
                Tenant(id=tenant_id, slug=f"profile-{tenant_id.hex[:48]}", name="Profile test"),
                Person(
                    id=first_id,
                    email=f"profile-{first_id.hex}@example.test",
                    email_verified_at=NOW,
                    display_name="First Person",
                    status="active",
                ),
                Person(
                    id=second_id,
                    email=f"profile-{second_id.hex}@example.test",
                    email_verified_at=NOW,
                    display_name="Second Person",
                    status="active",
                ),
            ]
        )

    async_engine = create_async_engine(profile_harness.schema_url, pool_size=4, max_overflow=0)
    sessions = async_sessionmaker(async_engine, expire_on_commit=False)

    async def update_person(person_id, session_id, full_name):
        async with sessions() as database, database.begin():
            return await update_sales_xray_profile(
                database,
                person_id=person_id,
                session_id=session_id,
                tenant_id=tenant_id,
                full_name=full_name,
                phone_number_e164=phone,
                expected_revision=0,
            )

    async def scenario() -> None:
        try:
            # Both updates can start before either has committed. The advisory
            # lock on the normalized number serializes the collision check.
            first, second = await asyncio.gather(
                update_person(first_id, first_session, "First Person"),
                update_person(second_id, second_session, "Second Person"),
            )
            assert first.profile_complete and second.profile_complete

            async with sessions() as database, database.begin():
                rows = list(
                    (
                        await database.scalars(
                            select(SalesXrayProfile).where(
                                SalesXrayProfile.person_id.in_((first_id, second_id))
                            )
                        )
                    ).all()
                )
                assert len(rows) == 2
                assert sum(row.admin_collision_review_required for row in rows) == 1

                with pytest.raises(SalesXrayProfileRevisionConflict):
                    await update_sales_xray_profile(
                        database,
                        person_id=first_id,
                        session_id=first_session,
                        tenant_id=tenant_id,
                        full_name="First Person changed",
                        phone_number_e164=phone,
                        expected_revision=0,
                    )

            async with sessions() as database, database.begin():
                first_row = await database.scalar(
                    select(SalesXrayProfile).where(SalesXrayProfile.person_id == first_id)
                )
                second_row = await database.scalar(
                    select(SalesXrayProfile).where(SalesXrayProfile.person_id == second_id)
                )
                assert first_row is not None and second_row is not None
                first_row.phone_verified_at = NOW

            with pytest.raises(IntegrityError):
                async with sessions() as database, database.begin():
                    second_row = await database.scalar(
                        select(SalesXrayProfile).where(SalesXrayProfile.person_id == second_id)
                    )
                    assert second_row is not None
                    second_row.phone_verified_at = NOW
                    await database.flush()

            async with sessions() as database, database.begin():
                events = list(
                    (
                        await database.scalars(
                            select(AuditEvent)
                            .where(
                                AuditEvent.tenant_id == tenant_id,
                                AuditEvent.action == "sales_xray.profile.self_updated.v1",
                            )
                            .order_by(AuditEvent.sequence_no)
                        )
                    ).all()
                )
                assert len(events) == 2
                assert [event.sequence_no for event in events] == [1, 2]
                assert all(
                    set(event.payload)
                    == {"revision", "changed_fields", "admin_collision_review_required"}
                    for event in events
                )
                assert all(phone not in str(event.payload) for event in events)
                report = await AuditRepository(database).verify(tenant_id)
                assert report.valid

                assert await erase_sales_xray_profile(database, person_id=first_id) is True
                assert await erase_sales_xray_profile(database, person_id=second_id) is True
        finally:
            await async_engine.dispose()

    _run_async(scenario())
