"""PostgreSQL coverage for first-tenant bootstrap and sole-tenant selection."""

from __future__ import annotations

import asyncio
import hashlib
import os
import subprocess
import sys
from collections.abc import Coroutine, Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import create_engine, delete, select
from sqlalchemy.engine import URL, Engine, make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session
from sqlalchemy.schema import CreateSchema, DropSchema

from ac_platform.bootstrap import BootstrapApplication
from ac_platform.identity.models import Person, ProviderIdentity
from ac_platform.identity.models import Session as SessionRow
from ac_platform.identity.repositories import AsyncSqlAlchemyIdentityRepository
from ac_platform.tenancy.models import Membership, Tenant

NOW = datetime(2026, 8, 30, 12, tzinfo=UTC)


def _run_async[T](coroutine: Coroutine[Any, Any, T]) -> T:
    if sys.platform == "win32":
        with asyncio.Runner(loop_factory=asyncio.SelectorEventLoop) as runner:
            return runner.run(coroutine)
    return asyncio.run(coroutine)


def _postgres_url() -> URL:
    raw = os.getenv("AC_TEST_DATABASE_URL")
    if not raw:
        pytest.skip("AC_TEST_DATABASE_URL is not configured")
    url = make_url(raw)
    if url.get_backend_name() != "postgresql":
        pytest.fail("AC_TEST_DATABASE_URL must use PostgreSQL")
    return url.set(drivername="postgresql+psycopg")


@pytest.fixture(scope="module")
def postgres_harness() -> Iterator[URL]:
    root = Path(__file__).parents[2]
    base_url = _postgres_url()
    schema = f"bootstrap_{uuid4().hex}"
    admin_engine = create_engine(base_url, pool_pre_ping=True)
    created = False
    try:
        with admin_engine.begin() as connection:
            connection.execute(CreateSchema(schema))
        created = True
        query = dict(base_url.query)
        query["options"] = f"-csearch_path={schema}"
        schema_url = base_url.set(query=query)
        environment = os.environ.copy()
        environment.update(
            {
                "AC_DATABASE_URL": base_url.render_as_string(hide_password=False),
                "AC_DATABASE_MIGRATOR_URL": base_url.render_as_string(hide_password=False),
                "AC_ENVIRONMENT": "test",
                "PGOPTIONS": f"-csearch_path={schema}",
                "PYTHONPATH": os.pathsep.join(
                    part
                    for part in (
                        str(root / "packages" / "python"),
                        environment.get("PYTHONPATH", ""),
                    )
                    if part
                ),
            }
        )
        migration = subprocess.run(
            [sys.executable, "-m", "alembic", "-c", "alembic.ini", "upgrade", "head"],
            cwd=root,
            env=environment,
            capture_output=True,
            text=True,
            timeout=180,
            check=False,
        )
        if migration.returncode != 0:
            pytest.fail("fresh PostgreSQL migration failed")
        yield schema_url
    finally:
        if created:
            with admin_engine.begin() as connection:
                connection.execute(DropSchema(schema, cascade=True))
        admin_engine.dispose()


def _seed_person(
    engine: Engine,
    *,
    email: str | None = None,
    sessions: tuple[tuple[UUID, datetime, datetime | None], ...] = (),
) -> UUID:
    person_id = uuid4()
    email = email or f"bootstrap-{person_id.hex}@example.test"
    with Session(engine) as database:
        database.add(
            Person(
                id=person_id,
                email=email,
                email_verified_at=NOW,
            )
        )
        database.add(
            ProviderIdentity(
                id=uuid4(),
                person_id=person_id,
                issuer="https://accounts.google.com",
                subject=f"subject-{person_id}",
            )
        )
        for session_id, expires_at, revoked_at in sessions:
            database.add(
                SessionRow(
                    id=session_id,
                    person_id=person_id,
                    token_hash=hashlib.sha256(session_id.bytes).digest(),
                    created_at=NOW,
                    expires_at=expires_at,
                    revoked_at=revoked_at,
                    revision=0,
                )
            )
        database.commit()
    return person_id


def _person_email(engine: Engine, person_id: UUID) -> str:
    with Session(engine) as database:
        person = database.get(Person, person_id)
        assert person is not None and person.email is not None
        return person.email


def _cleanup(engine: Engine, *, person_id: UUID, tenant_ids: tuple[UUID, ...] = ()) -> None:
    with engine.begin() as connection:
        connection.execute(delete(SessionRow).where(SessionRow.person_id == person_id))
        connection.execute(delete(ProviderIdentity).where(ProviderIdentity.person_id == person_id))
        connection.execute(delete(Membership).where(Membership.person_id == person_id))
        if tenant_ids:
            connection.execute(delete(Membership).where(Membership.tenant_id.in_(tenant_ids)))
            connection.execute(delete(Tenant).where(Tenant.id.in_(tenant_ids)))
        connection.execute(delete(Person).where(Person.id == person_id))


def test_concurrent_same_bootstrap_is_idempotent(postgres_harness: URL) -> None:
    engine = create_async_engine(postgres_harness, pool_size=4, max_overflow=0)
    sync_engine = create_engine(postgres_harness, pool_pre_ping=True)
    person_id = _seed_person(
        sync_engine,
        email=f"concurrent-{uuid4().hex}@example.test",
    )
    email = _person_email(sync_engine, person_id)
    slug = f"concurrent-{uuid4().hex}"

    async def scenario() -> tuple[Any, Any]:
        sessions = async_sessionmaker(engine, expire_on_commit=False)

        async def once() -> Any:
            async with sessions() as database, database.begin():
                return await BootstrapApplication(database).bootstrap_owner(
                    email=email,
                    tenant_slug=slug,
                    tenant_name="Concurrent Bootstrap",
                    now=NOW,
                )

        return await asyncio.gather(once(), once())

    try:
        first, second = _run_async(scenario())
        assert {first.tenant_created, second.tenant_created} == {True, False}
        assert {first.membership_created, second.membership_created} == {True, False}
        assert first.tenant_id == second.tenant_id
        with Session(sync_engine) as database:
            assert database.scalar(select(Tenant).where(Tenant.slug == slug)) is not None
            assert (
                database.scalar(
                    select(Membership).where(
                        Membership.tenant_id == first.tenant_id,
                        Membership.person_id == person_id,
                    )
                )
                is not None
            )
    finally:
        tenant_id = first.tenant_id if "first" in locals() else None
        _cleanup(
            sync_engine, person_id=person_id, tenant_ids=() if tenant_id is None else (tenant_id,)
        )
        _run_async(engine.dispose())
        sync_engine.dispose()


def test_bootstrap_rolls_back_after_downstream_failure(postgres_harness: URL) -> None:
    engine = create_async_engine(postgres_harness, pool_size=2, max_overflow=0)
    sync_engine = create_engine(postgres_harness, pool_pre_ping=True)
    person_id = _seed_person(sync_engine, email=f"rollback-{uuid4().hex}@example.test")
    email = _person_email(sync_engine, person_id)
    slug = f"rollback-{uuid4().hex}"

    async def scenario() -> None:
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        async with sessions() as database:
            application = BootstrapApplication(database)

            async def fail_after_scope(*_args: Any, **_kwargs: Any) -> int:
                raise RuntimeError("simulated downstream failure")

            application._identity.select_tenant_for_active_sessions = fail_after_scope  # type: ignore[method-assign]
            with pytest.raises(RuntimeError, match="downstream"):
                async with database.begin():
                    await application.bootstrap_owner(
                        email=email,
                        tenant_slug=slug,
                        tenant_name="Rollback Bootstrap",
                        now=NOW,
                    )

    try:
        _run_async(scenario())
        with Session(sync_engine) as database:
            assert database.scalar(select(Tenant).where(Tenant.slug == slug)) is None
            assert (
                database.scalar(select(Membership).where(Membership.person_id == person_id)) is None
            )
    finally:
        _cleanup(sync_engine, person_id=person_id)
        _run_async(engine.dispose())
        sync_engine.dispose()


def test_bootstrap_excludes_revoked_and_expired_sessions(postgres_harness: URL) -> None:
    active_id, revoked_id, expired_id = uuid4(), uuid4(), uuid4()
    engine = create_async_engine(postgres_harness, pool_size=2, max_overflow=0)
    sync_engine = create_engine(postgres_harness, pool_pre_ping=True)
    person_id = _seed_person(
        sync_engine,
        email=f"sessions-{uuid4().hex}@example.test",
        sessions=(
            (active_id, NOW + timedelta(hours=1), None),
            (revoked_id, NOW + timedelta(hours=1), NOW),
            (expired_id, NOW - timedelta(seconds=1), None),
        ),
    )
    email = _person_email(sync_engine, person_id)
    slug = f"sessions-{uuid4().hex}"

    async def scenario() -> Any:
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        async with sessions() as database, database.begin():
            return await BootstrapApplication(database).bootstrap_owner(
                email=email,
                tenant_slug=slug,
                tenant_name="Session Bootstrap",
                now=NOW,
            )

    try:
        result = _run_async(scenario())
        assert result.sessions_updated == 1
        with Session(sync_engine) as database:
            rows = {
                row.id: row
                for row in database.scalars(
                    select(SessionRow).where(SessionRow.person_id == person_id)
                )
            }
            assert rows[active_id].selected_tenant_id == result.tenant_id
            assert rows[active_id].revision == 1
            assert rows[revoked_id].selected_tenant_id is None
            assert rows[expired_id].selected_tenant_id is None
    finally:
        tenant_ids = () if "result" not in locals() else (result.tenant_id,)
        _cleanup(sync_engine, person_id=person_id, tenant_ids=tenant_ids)
        _run_async(engine.dispose())
        sync_engine.dispose()


def test_sole_active_tenant_requires_exactly_one_active_scope(postgres_harness: URL) -> None:
    seeded: list[tuple[UUID, tuple[UUID, ...]]] = []
    engine = create_async_engine(postgres_harness, pool_size=2, max_overflow=0)
    sync_engine = create_engine(postgres_harness, pool_size=2, max_overflow=0)
    try:
        active_tenant = uuid4()
        zero_person = _seed_person(sync_engine)
        sole_person = _seed_person(sync_engine)
        multiple_person = _seed_person(sync_engine)
        inactive_person = _seed_person(sync_engine)
        suspended_person = _seed_person(sync_engine)
        active_two = uuid4()
        active_one = uuid4()
        inactive_tenant = uuid4()
        suspended_tenant = uuid4()
        with Session(sync_engine) as database:
            database.add_all(
                [
                    Tenant(id=active_tenant, slug=f"sole-{uuid4().hex}", name="Sole"),
                    Tenant(id=active_one, slug=f"multiple-a-{uuid4().hex}", name="Multiple A"),
                    Tenant(id=active_two, slug=f"multiple-b-{uuid4().hex}", name="Multiple B"),
                    Tenant(id=inactive_tenant, slug=f"inactive-{uuid4().hex}", name="Inactive"),
                    Tenant(
                        id=suspended_tenant,
                        slug=f"suspended-{uuid4().hex}",
                        name="Suspended",
                        status="suspended",
                    ),
                ]
            )
            database.add_all(
                [
                    Membership(tenant_id=active_tenant, person_id=sole_person, role="owner"),
                    Membership(tenant_id=active_one, person_id=multiple_person, role="owner"),
                    Membership(tenant_id=active_two, person_id=multiple_person, role="admin"),
                    Membership(
                        tenant_id=inactive_tenant,
                        person_id=inactive_person,
                        role="owner",
                        status="inactive",
                        ended_at=NOW,
                    ),
                    Membership(
                        tenant_id=suspended_tenant, person_id=suspended_person, role="owner"
                    ),
                ]
            )
            database.commit()
        seeded = [
            (zero_person, ()),
            (sole_person, (active_tenant,)),
            (multiple_person, (active_one, active_two)),
            (inactive_person, (inactive_tenant,)),
            (suspended_person, (suspended_tenant,)),
        ]

        async def scenario() -> dict[UUID, UUID | None]:
            sessions = async_sessionmaker(engine, expire_on_commit=False)

            async def read(person_id: UUID) -> tuple[UUID, UUID | None]:
                async with sessions() as database, database.begin():
                    tenant_id = await AsyncSqlAlchemyIdentityRepository(
                        database
                    ).get_sole_active_tenant_id(person_id)
                    return person_id, tenant_id

            return dict(await asyncio.gather(*(read(person_id) for person_id, _ in seeded)))

        resolved = _run_async(scenario())
        assert resolved[zero_person] is None
        assert resolved[sole_person] == active_tenant
        assert resolved[multiple_person] is None
        assert resolved[inactive_person] is None
        assert resolved[suspended_person] is None
    finally:
        tenant_ids = tuple(tenant_id for _, ids in seeded for tenant_id in ids)
        for person_id, _ in seeded:
            _cleanup(sync_engine, person_id=person_id)
        with sync_engine.begin() as connection:
            connection.execute(delete(Membership).where(Membership.tenant_id.in_(tenant_ids)))
            connection.execute(delete(Tenant).where(Tenant.id.in_(tenant_ids)))
        _run_async(engine.dispose())
        sync_engine.dispose()
