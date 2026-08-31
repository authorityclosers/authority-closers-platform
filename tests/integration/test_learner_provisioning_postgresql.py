"""PostgreSQL invariants for exact-tenant public learner provisioning."""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from collections.abc import Coroutine, Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.engine import URL, make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session as SQLAlchemySession
from sqlalchemy.schema import CreateSchema, DropSchema

from ac_platform.identity.application import AsyncIdentityApplication
from ac_platform.identity.models import Person, PersonStatus
from ac_platform.identity.models import Session as SessionRow
from ac_platform.tenancy.learner_provisioning import (
    AsyncLearnerProvisioningApplication,
    LearnerProvisioningError,
)
from ac_platform.tenancy.models import (
    Membership,
    MembershipRole,
    MembershipStatus,
    Tenant,
    TenantStatus,
)

NOW = datetime(2026, 8, 31, 12, tzinfo=UTC)
CONSENT_VERSION = "learner-consent-2026-08-31-v1"
TOKEN_PEPPER = b"learner-provisioning-postgres-pepper"


class Session(SQLAlchemySession):
    """Keep seeded ORM identifiers available after setup commits."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        kwargs.setdefault("expire_on_commit", False)
        super().__init__(*args, **kwargs)


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
    if (
        url.host not in {None, "127.0.0.1", "localhost", "::1"}
        and os.getenv("AC_ALLOW_REMOTE_TEST_DATABASE") != "1"
    ):
        pytest.skip("refusing to mutate a non-local PostgreSQL database")
    return url.set(drivername="postgresql+psycopg")


@pytest.fixture(scope="module")
def postgres_harness() -> Iterator[URL]:
    root = Path(__file__).parents[2]
    base_url = _postgres_url()
    schema = f"learner_provisioning_{uuid4().hex}"
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
        migration = subprocess.run(  # noqa: S603 - fixed interpreter and repository inputs
            [sys.executable, "-m", "alembic", "-c", "alembic.ini", "upgrade", "head"],
            cwd=root,
            env=environment,
            capture_output=True,
            text=True,
            timeout=180,
            check=False,
        )
        if migration.returncode != 0:
            pytest.fail(
                "fresh PostgreSQL migration failed\n"
                f"stdout:\n{migration.stdout}\n"
                f"stderr:\n{migration.stderr}"
            )
        yield schema_url
    finally:
        if created:
            with admin_engine.begin() as connection:
                connection.execute(DropSchema(schema, cascade=True))
        admin_engine.dispose()


def _tenant(*, status: str = TenantStatus.ACTIVE.value) -> Tenant:
    identifier = uuid4()
    return Tenant(
        id=identifier,
        slug=f"public-learner-{identifier.hex}",
        name="Authority Closers public learner",
        status=status,
    )


def _person(
    *,
    status: str = PersonStatus.ACTIVE.value,
    email_verified_at: datetime | None = NOW,
    consent_version: str | None = CONSENT_VERSION,
    consented_at: datetime | None = NOW,
) -> Person:
    identifier = uuid4()
    return Person(
        id=identifier,
        email=f"learner-{identifier.hex}@example.test",
        status=status,
        email_verified_at=email_verified_at,
        consent_version=consent_version,
        consented_at=consented_at,
    )


async def _ensure(
    sessions: async_sessionmaker[Any],
    *,
    person_id: UUID,
    tenant_id: UUID,
    required_consent_version: str = CONSENT_VERSION,
) -> Any:
    async with sessions() as database, database.begin():
        return await AsyncLearnerProvisioningApplication(database).ensure(
            person_id=person_id,
            tenant_id=tenant_id,
            required_consent_version=required_consent_version,
        )


def test_concurrent_same_person_insert_is_idempotent(postgres_harness: URL) -> None:
    async_engine = create_async_engine(postgres_harness, pool_size=4, max_overflow=0)
    sync_engine = create_engine(postgres_harness, pool_pre_ping=True)
    tenant = _tenant()
    person = _person()
    with Session(sync_engine) as database, database.begin():
        database.add_all([tenant, person])

    async def scenario() -> tuple[Any, Any]:
        sessions = async_sessionmaker(async_engine, expire_on_commit=False)
        first, second = await asyncio.gather(
            _ensure(sessions, person_id=person.id, tenant_id=tenant.id),
            _ensure(sessions, person_id=person.id, tenant_id=tenant.id),
        )
        return first, second

    try:
        first, second = _run_async(scenario())
        assert {first.created, second.created} == {True, False}
        assert first.tenant_id == second.tenant_id == tenant.id
        assert first.person_id == second.person_id == person.id
        with Session(sync_engine) as database:
            assert (
                database.scalar(
                    select(func.count())
                    .select_from(Membership)
                    .where(Membership.tenant_id == tenant.id, Membership.person_id == person.id)
                )
                == 1
            )
    finally:
        _run_async(async_engine.dispose())
        sync_engine.dispose()


def test_different_learners_do_not_serialize_on_the_tenant_row(
    postgres_harness: URL,
) -> None:
    async_engine = create_async_engine(postgres_harness, pool_size=4, max_overflow=0)
    sync_engine = create_engine(postgres_harness, pool_pre_ping=True)
    tenant = _tenant()
    first_person = _person()
    second_person = _person()
    with Session(sync_engine) as database, database.begin():
        database.add_all([tenant, first_person, second_person])

    async def scenario() -> tuple[Any, Any]:
        sessions = async_sessionmaker(async_engine, expire_on_commit=False)
        first_holds_transaction = asyncio.Event()
        release_first = asyncio.Event()

        async def first() -> Any:
            async with sessions() as database, database.begin():
                result = await AsyncLearnerProvisioningApplication(database).ensure(
                    person_id=first_person.id,
                    tenant_id=tenant.id,
                    required_consent_version=CONSENT_VERSION,
                )
                first_holds_transaction.set()
                await release_first.wait()
                return result

        async def second() -> Any:
            await first_holds_transaction.wait()
            return await _ensure(
                sessions,
                person_id=second_person.id,
                tenant_id=tenant.id,
            )

        first_task = asyncio.create_task(first())
        second_task = asyncio.create_task(second())
        try:
            second_result = await asyncio.wait_for(asyncio.shield(second_task), timeout=10)
        finally:
            release_first.set()
        first_result = await first_task
        return first_result, second_result

    try:
        first_result, second_result = _run_async(scenario())
        assert first_result.created is True
        assert second_result.created is True
        with Session(sync_engine) as database:
            assert (
                database.scalar(
                    select(func.count())
                    .select_from(Membership)
                    .where(Membership.tenant_id == tenant.id)
                )
                == 2
            )
    finally:
        _run_async(async_engine.dispose())
        sync_engine.dispose()


def test_concurrent_complete_provision_and_tenant_selection_does_not_deadlock(
    postgres_harness: URL,
) -> None:
    async_engine = create_async_engine(postgres_harness, pool_size=4, max_overflow=0)
    sync_engine = create_engine(postgres_harness, pool_pre_ping=True)
    tenant = _tenant()
    people = (_person(), _person())
    with Session(sync_engine) as database, database.begin():
        database.add_all([tenant, *people])

    async def scenario() -> tuple[tuple[UUID, UUID], tuple[UUID, UUID]]:
        sessions = async_sessionmaker(async_engine, expire_on_commit=False)
        ready = (asyncio.Event(), asyncio.Event())
        release = asyncio.Event()

        async def complete_flow(index: int, person_id: UUID) -> tuple[UUID, UUID]:
            async with sessions() as database, database.begin():
                await AsyncLearnerProvisioningApplication(database).ensure(
                    person_id=person_id,
                    tenant_id=tenant.id,
                    required_consent_version=CONSENT_VERSION,
                )
                identity = AsyncIdentityApplication(database, token_pepper=TOKEN_PEPPER)
                issued = await identity.issue_authenticated_session(person_id, now=NOW)
                resolved = await identity.select_tenant(issued.token, tenant.id, now=NOW)
                assert resolved.actor.person_id == person_id
                assert resolved.actor.tenant_id == tenant.id
                assert resolved.session_revision == 1
                ready[index].set()
                await release.wait()
                return person_id, issued.metadata.id

        tasks = tuple(
            asyncio.create_task(complete_flow(index, person.id))
            for index, person in enumerate(people)
        )
        try:
            await asyncio.wait_for(
                asyncio.gather(*(event.wait() for event in ready)),
                timeout=10,
            )
            assert all(not task.done() for task in tasks)
            release.set()
            first, second = await asyncio.wait_for(asyncio.gather(*tasks), timeout=10)
            return first, second
        finally:
            release.set()
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    try:
        first, second = _run_async(scenario())
        assert {first[0], second[0]} == {person.id for person in people}
        with Session(sync_engine) as database:
            sessions = tuple(
                database.scalars(
                    select(SessionRow)
                    .where(SessionRow.id.in_((first[1], second[1])))
                    .order_by(SessionRow.id)
                )
            )
            assert len(sessions) == 2
            assert {session.person_id for session in sessions} == {person.id for person in people}
            assert all(session.selected_tenant_id == tenant.id for session in sessions)
            assert (
                database.scalar(
                    select(func.count())
                    .select_from(Membership)
                    .where(
                        Membership.tenant_id == tenant.id,
                        Membership.person_id.in_(tuple(person.id for person in people)),
                    )
                )
                == 2
            )
    finally:
        _run_async(async_engine.dispose())
        sync_engine.dispose()


@pytest.mark.parametrize(
    "role",
    [MembershipRole.OWNER.value, MembershipRole.ADMIN.value, MembershipRole.SUPPORT.value],
)
def test_existing_privileged_role_is_preserved(postgres_harness: URL, role: str) -> None:
    async_engine = create_async_engine(postgres_harness, pool_pre_ping=True)
    sync_engine = create_engine(postgres_harness, pool_pre_ping=True)
    tenant = _tenant()
    person = _person()
    with Session(sync_engine) as database, database.begin():
        database.add_all(
            [
                tenant,
                person,
                Membership(tenant_id=tenant.id, person_id=person.id, role=role),
            ]
        )

    try:
        sessions = async_sessionmaker(async_engine, expire_on_commit=False)
        result = _run_async(_ensure(sessions, person_id=person.id, tenant_id=tenant.id))
        assert result.created is False
        assert result.role == role
        with Session(sync_engine) as database:
            membership = database.get(Membership, (tenant.id, person.id))
            assert membership is not None
            assert membership.role == role
            assert membership.status == MembershipStatus.ACTIVE.value
    finally:
        _run_async(async_engine.dispose())
        sync_engine.dispose()


def test_inactive_membership_is_never_reactivated(postgres_harness: URL) -> None:
    async_engine = create_async_engine(postgres_harness, pool_pre_ping=True)
    sync_engine = create_engine(postgres_harness, pool_pre_ping=True)
    tenant = _tenant()
    person = _person()
    with Session(sync_engine) as database, database.begin():
        database.add_all(
            [
                tenant,
                person,
                Membership(
                    tenant_id=tenant.id,
                    person_id=person.id,
                    role=MembershipRole.ADMIN.value,
                    status=MembershipStatus.INACTIVE.value,
                    ended_at=NOW,
                ),
            ]
        )

    try:
        sessions = async_sessionmaker(async_engine, expire_on_commit=False)
        with pytest.raises(LearnerProvisioningError, match="inactive membership"):
            _run_async(_ensure(sessions, person_id=person.id, tenant_id=tenant.id))
        with Session(sync_engine) as database:
            membership = database.get(Membership, (tenant.id, person.id))
            assert membership is not None
            assert membership.role == MembershipRole.ADMIN.value
            assert membership.status == MembershipStatus.INACTIVE.value
            assert membership.ended_at == NOW
    finally:
        _run_async(async_engine.dispose())
        sync_engine.dispose()


@pytest.mark.parametrize(
    "tenant_status",
    [TenantStatus.SUSPENDED.value, TenantStatus.DELETED.value],
)
def test_inactive_tenant_is_rejected(postgres_harness: URL, tenant_status: str) -> None:
    async_engine = create_async_engine(postgres_harness, pool_pre_ping=True)
    sync_engine = create_engine(postgres_harness, pool_pre_ping=True)
    tenant = _tenant(status=tenant_status)
    person = _person()
    with Session(sync_engine) as database, database.begin():
        database.add_all([tenant, person])

    try:
        sessions = async_sessionmaker(async_engine, expire_on_commit=False)
        with pytest.raises(LearnerProvisioningError, match="tenant is unavailable"):
            _run_async(_ensure(sessions, person_id=person.id, tenant_id=tenant.id))
        with Session(sync_engine) as database:
            assert database.get(Membership, (tenant.id, person.id)) is None
    finally:
        _run_async(async_engine.dispose())
        sync_engine.dispose()


@pytest.mark.parametrize(
    ("person_status", "verified_at"),
    [
        (PersonStatus.SUSPENDED.value, NOW),
        (PersonStatus.DELETED.value, NOW),
        (PersonStatus.ACTIVE.value, None),
    ],
)
def test_inactive_or_unverified_person_is_rejected(
    postgres_harness: URL,
    person_status: str,
    verified_at: datetime | None,
) -> None:
    async_engine = create_async_engine(postgres_harness, pool_pre_ping=True)
    sync_engine = create_engine(postgres_harness, pool_pre_ping=True)
    tenant = _tenant()
    person = _person(status=person_status, email_verified_at=verified_at)
    with Session(sync_engine) as database, database.begin():
        database.add_all([tenant, person])

    try:
        sessions = async_sessionmaker(async_engine, expire_on_commit=False)
        with pytest.raises(LearnerProvisioningError, match="active email-verified person"):
            _run_async(_ensure(sessions, person_id=person.id, tenant_id=tenant.id))
        with Session(sync_engine) as database:
            assert database.get(Membership, (tenant.id, person.id)) is None
    finally:
        _run_async(async_engine.dispose())
        sync_engine.dispose()


@pytest.mark.parametrize(
    ("recorded_version", "consented_at", "required_version"),
    [
        ("older-consent-v1", NOW, CONSENT_VERSION),
        (CONSENT_VERSION, None, CONSENT_VERSION),
        (CONSENT_VERSION, NOW, f"{CONSENT_VERSION} "),
    ],
)
def test_exact_consent_version_and_timestamp_are_required(
    postgres_harness: URL,
    recorded_version: str,
    consented_at: datetime | None,
    required_version: str,
) -> None:
    async_engine = create_async_engine(postgres_harness, pool_pre_ping=True)
    sync_engine = create_engine(postgres_harness, pool_pre_ping=True)
    tenant = _tenant()
    person = _person(consent_version=recorded_version, consented_at=consented_at)
    with Session(sync_engine) as database, database.begin():
        database.add_all([tenant, person])

    try:
        sessions = async_sessionmaker(async_engine, expire_on_commit=False)
        with pytest.raises(LearnerProvisioningError, match="exact required learner consent"):
            _run_async(
                _ensure(
                    sessions,
                    person_id=person.id,
                    tenant_id=tenant.id,
                    required_consent_version=required_version,
                )
            )
        with Session(sync_engine) as database:
            assert database.get(Membership, (tenant.id, person.id)) is None
    finally:
        _run_async(async_engine.dispose())
        sync_engine.dispose()


def test_missing_tenant_and_outer_rollback_leave_no_partial_writes(
    postgres_harness: URL,
) -> None:
    async_engine = create_async_engine(postgres_harness, pool_pre_ping=True)
    sync_engine = create_engine(postgres_harness, pool_pre_ping=True)
    tenant = _tenant()
    person = _person()
    with Session(sync_engine) as database:
        tenant_count_before = database.scalar(select(func.count()).select_from(Tenant))
        person_count_before = database.scalar(select(func.count()).select_from(Person))
    assert tenant_count_before is not None
    assert person_count_before is not None
    with Session(sync_engine) as database, database.begin():
        database.add_all([tenant, person])

    async def scenario() -> None:
        sessions = async_sessionmaker(async_engine, expire_on_commit=False)
        with pytest.raises(LearnerProvisioningError, match="tenant is unavailable"):
            await _ensure(sessions, person_id=person.id, tenant_id=uuid4())

        with pytest.raises(RuntimeError, match="downstream failure"):
            async with sessions() as database, database.begin():
                result = await AsyncLearnerProvisioningApplication(database).ensure(
                    person_id=person.id,
                    tenant_id=tenant.id,
                    required_consent_version=CONSENT_VERSION,
                )
                assert result.created is True
                raise RuntimeError("simulated downstream failure")

    try:
        _run_async(scenario())
        with Session(sync_engine) as database:
            assert database.get(Membership, (tenant.id, person.id)) is None
            assert (
                database.scalar(select(func.count()).select_from(Tenant)) == tenant_count_before + 1
            )
            assert (
                database.scalar(select(func.count()).select_from(Person)) == person_count_before + 1
            )
    finally:
        _run_async(async_engine.dispose())
        sync_engine.dispose()
