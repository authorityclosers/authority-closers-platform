"""Disposable PostgreSQL 0018→0019 upgrade and direct-SQL history protection."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import os
import subprocess
import sys
from collections.abc import Coroutine, Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import Engine, create_engine, delete, inspect, select, text, update
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine
from sqlalchemy.orm import Session
from sqlalchemy.schema import CreateSchema, DropSchema

from ac_platform.audit.models import AuditEvent
from ac_platform.audit.service import AuditRepository, verify_audit_chain
from ac_platform.authorization.application import CapabilityApplication
from ac_platform.authorization.models import CapabilityGrant, CapabilityRevocation
from ac_platform.authorization.policy import CapabilityConflict, CapabilityDenied, CapabilityScope
from ac_platform.db.models import model_metadata
from ac_platform.identity.application import AsyncIdentityApplication
from ac_platform.identity.models import Person
from ac_platform.identity.models import Session as IdentitySession
from ac_platform.kernel.authz import ActorContext
from ac_platform.tenancy.models import Membership, Tenant
from tests.database.test_capability_grants import Scope, audit, grant, seed_scope

ROOT = Path(__file__).parents[2]
TEST_PEPPER = b"capability-concurrency-test-pepper-only"


def _test_token(scope: Scope) -> str:
    return f"capability-test-session-{scope.actor.hex}-" + "t" * 43


@pytest.fixture(scope="module")
def postgres_harness() -> Iterator[Engine]:
    raw = os.getenv("AC_CAPABILITY_POSTGRES_TEST_URL") or os.getenv("AC_TEST_DATABASE_URL")
    if not raw:
        pytest.skip("disposable capability PostgreSQL URL is not configured")
    url = make_url(raw)
    if url.get_backend_name() != "postgresql":
        pytest.fail("capability migration integration requires PostgreSQL")
    if (
        url.host not in {None, "127.0.0.1", "localhost", "::1"}
        and os.getenv("AC_ALLOW_REMOTE_TEST_DATABASE") != "1"
    ):
        pytest.skip("refusing to mutate a non-local PostgreSQL database")
    url = url.set(drivername="postgresql+psycopg")
    schema = f"capability_history_{uuid4().hex}"
    admin_engine = create_engine(url, pool_pre_ping=True)
    schema_engine: Engine | None = None
    created = False
    try:
        with admin_engine.begin() as connection:
            connection.execute(CreateSchema(schema))
        created = True
        query = dict(url.query)
        query["options"] = f"-csearch_path={schema}"
        schema_engine = create_engine(url.set(query=query), pool_pre_ping=True)
        environment = os.environ.copy()
        environment.update(
            {
                "AC_DATABASE_URL": url.render_as_string(hide_password=False),
                "AC_DATABASE_MIGRATOR_URL": url.render_as_string(hide_password=False),
                "AC_ENVIRONMENT": "test",
                "PGOPTIONS": f"-csearch_path={schema}",
                "PYTHONPATH": str(ROOT / "packages/python"),
            }
        )

        def migrate(target: str) -> None:
            result = subprocess.run(  # noqa: S603 - fixed local Alembic invocation
                [sys.executable, "-m", "alembic", "-c", "alembic.ini", "upgrade", target],
                cwd=ROOT,
                env=environment,
                capture_output=True,
                text=True,
                timeout=180,
                check=False,
            )
            assert result.returncode == 0, f"isolated PostgreSQL migration to {target} failed"

        migrate("20260904_0018")
        # Seed real existing memberships/catalog before adding the composite
        # program unique constraint and capability tables.
        with Session(schema_engine) as session:
            original = seed_scope(session)
        migrate("20260907_0019")
        with Session(schema_engine) as session:
            member = session.get(Membership, (original.tenant, original.subject))
            assert member is not None and member.role == "learner" and member.revision == 0
            assert session.scalars(select(CapabilityGrant)).all() == []
        yield schema_engine
    finally:
        if schema_engine is not None:
            schema_engine.dispose()
        if created:
            # Only this test-created, random exact schema is removed.
            with admin_engine.begin() as connection:
                connection.execute(DropSchema(schema, cascade=True))
        admin_engine.dispose()


def _history(engine: Engine) -> tuple[UUID, UUID]:
    with Session(engine) as session:
        scope = seed_scope(session)
        original = grant(session, scope)
        session.add(original)
        session.commit()
        grant_id = original.id
        removed = CapabilityRevocation(
            id=uuid4(),
            grant_id=grant_id,
            revoked_by_person_id=scope.actor,
            audit_event_id=audit(session, scope),
            reason="Explicit fixture removal",
        )
        session.add(removed)
        session.commit()
        return grant_id, removed.id


@pytest.mark.parametrize("table_name", ["capability_grants", "capability_revocations"])
@pytest.mark.parametrize("operation", ["update", "delete"])
def test_postgresql_sql_cannot_mutate_history(
    postgres_harness: Engine,
    table_name: str,
    operation: str,
) -> None:
    grant_id, revocation_id = _history(postgres_harness)
    table = model_metadata().tables[table_name]
    target_id = grant_id if table_name == "capability_grants" else revocation_id
    statement = (
        update(table).where(table.c.id == target_id).values(reason="Direct SQL rewrite")
        if operation == "update"
        else delete(table).where(table.c.id == target_id)
    )
    with (
        pytest.raises(DBAPIError, match="capability history is immutable"),
        postgres_harness.begin() as connection,
    ):
        connection.execute(statement)
    with postgres_harness.connect() as connection:
        assert connection.scalar(select(table.c.id).where(table.c.id == target_id)) == target_id


def test_postgresql_program_grant_rejects_cross_tenant_relationship(
    postgres_harness: Engine,
) -> None:
    with Session(postgres_harness) as session:
        scope = seed_scope(session)
        session.add(grant(session, scope, tenant_id=scope.other_tenant))
        with pytest.raises(DBAPIError):
            session.flush()


def test_postgresql_real_service_replay_revocation_and_atomic_audit(
    postgres_harness: Engine,
) -> None:
    with Session(postgres_harness) as db:
        scope = seed_scope(db)

    async def exercise() -> None:
        engine = create_async_engine(postgres_harness.url)
        try:
            actor = await _manager_fixture(engine, scope)
            command_id, revoke_id = uuid4(), uuid4()
            resource = CapabilityScope("program", scope.tenant, scope.program)
            async with AsyncSession(engine) as db, db.begin():
                app = CapabilityApplication(db, operations_tenant_id=scope.other_tenant)
                arguments = {
                    "command_id": command_id,
                    "subject_person_id": scope.subject,
                    "permission": "catalog_publish",
                    "scope": resource,
                    "reason": "Named scoped publication responsibility",
                }
                granted = await app.grant(actor, **arguments)
                assert (await app.grant(actor, **arguments)).id == command_id
                assert (
                    await app.require(scope.subject, "catalog_publish", resource)
                ).id == command_id
                with pytest.raises(CapabilityDenied):
                    await app.require(
                        scope.subject, "catalog_publish", CapabilityScope("tenant", scope.tenant)
                    )
                evidence = await db.get(AuditEvent, granted.audit_event_id)
                assert evidence is not None and evidence.tenant_id == scope.tenant
                assert evidence.actor_person_id == actor.person_id
                assert evidence.session_id == actor.session_id
                assert (await verify_audit_chain(db, scope.tenant)).valid
            async with AsyncSession(engine) as db, db.begin():
                app = CapabilityApplication(db, operations_tenant_id=scope.other_tenant)
                revoked = await app.revoke(
                    actor, command_id=revoke_id, grant_id=command_id, reason="Responsibility ended"
                )
                assert revoked.id == revoke_id
                with pytest.raises(CapabilityDenied):
                    await app.require(scope.subject, "catalog_publish", resource)
                assert (await app.grant(actor, **arguments)).id == command_id
                with pytest.raises(CapabilityDenied):
                    await app.require(scope.subject, "catalog_publish", resource)
                with pytest.raises(CapabilityConflict):
                    await app.grant(actor, **{**arguments, "reason": "Different intent"})
                assert (await verify_audit_chain(db, scope.tenant)).valid
                member = await db.get(Membership, (scope.tenant, scope.subject))
                assert member is not None and member.role == "learner"
            async with AsyncSession(engine) as db, db.begin():
                app = CapabilityApplication(db, operations_tenant_id=scope.other_tenant)
                checkpoint = await db.begin_nested()
                temporary = await app.grant(actor, **{**arguments, "command_id": uuid4()})
                temporary_id, audit_id = temporary.id, temporary.audit_event_id
                await checkpoint.rollback()
                assert await db.get(CapabilityGrant, temporary_id) is None
                assert await db.get(AuditEvent, audit_id) is None
        finally:
            await engine.dispose()

    _run_async(exercise())


def test_postgresql_capability_migration_matches_model_metadata(postgres_harness: Engine) -> None:
    selected_tables = {"capability_grants", "capability_revocations", "programs"}

    def include_object(obj: object, name: str | None, kind: str, *_args: object) -> bool:
        if kind == "table":
            return name in selected_tables
        parent = getattr(obj, "table", None)
        return parent is None or parent.name in selected_tables

    with postgres_harness.connect() as connection:
        context = MigrationContext.configure(
            connection,
            opts={"include_object": include_object, "compare_type": True},
        )
        assert compare_metadata(context, model_metadata()) == []
        unique = inspect(connection).get_unique_constraints("programs")
        assert any(item["column_names"] == ["id", "tenant_id"] for item in unique)


def _run_async[T](coroutine: Coroutine[Any, Any, T]) -> T:
    if sys.platform == "win32":
        with asyncio.Runner(loop_factory=asyncio.SelectorEventLoop) as runner:
            return runner.run(coroutine)
    return asyncio.run(coroutine)


async def _manager_fixture(engine: AsyncEngine, scope: Scope) -> ActorContext:
    """Seed an explicit fixture manager, without relying on a live bootstrap."""
    session_id = uuid4()
    now = datetime.now(UTC)
    async with AsyncSession(engine) as db, db.begin():
        for person_id in (scope.actor, scope.subject):
            person = await db.get(Person, person_id)
            assert person is not None
            person.email_verified_at = now
        db.add(Membership(tenant_id=scope.other_tenant, person_id=scope.actor, role="owner"))
        # Session.selected_tenant_id references this composite membership key.
        # These independently added ORM objects have no relationship edge to
        # order their inserts, so establish the referenced row before session.
        await db.flush()
        db.add(
            IdentitySession(
                id=session_id,
                person_id=scope.actor,
                token_hash=hmac.new(
                    TEST_PEPPER, _test_token(scope).encode(), hashlib.sha256
                ).digest(),
                selected_tenant_id=scope.other_tenant,
                created_at=now,
                expires_at=now + timedelta(hours=1),
            )
        )
        await db.flush()
        command_id = uuid4()
        evidence = await AuditRepository(db).append(
            tenant_id=scope.other_tenant,
            actor_person_id=scope.actor,
            session_id=session_id,
            action="authorization.fixture_manager",
            resource_type="capability_grant",
            resource_id=command_id,
            reason="Disposable database fixture only",
        )
        db.add(
            CapabilityGrant(
                id=command_id,
                subject_person_id=scope.actor,
                permission="platform_access_manage",
                scope_kind="platform",
                tenant_id=None,
                program_id=None,
                granted_by_person_id=scope.actor,
                audit_event_id=evidence.id,
                reason="Disposable database fixture only",
            )
        )
    return ActorContext(scope.actor, session_id, scope.other_tenant)


def test_postgresql_normal_identity_does_not_deadlock_with_management_fence(
    postgres_harness: Engine,
) -> None:
    with Session(postgres_harness) as db:
        scope = seed_scope(db)

    async def exercise() -> None:
        engine = create_async_engine(postgres_harness.url)
        try:
            actor = await _manager_fixture(engine, scope)
            person_locked, governance_locked = asyncio.Event(), asyncio.Event()

            async def normal_identity() -> None:
                async with AsyncSession(engine) as db, db.begin():
                    identity = AsyncIdentityApplication(db, token_pepper=TEST_PEPPER)
                    # Pause at the real Person→Session→Tenant lock boundary.
                    await identity._lock_authenticated_session(
                        _test_token(scope), current_time=datetime.now(UTC)
                    )
                    person_locked.set()
                    await governance_locked.wait()
                    resolved = await identity.resolve_actor(_test_token(scope))
                    assert resolved.actor.tenant_id == scope.other_tenant

            async def management() -> None:
                await person_locked.wait()
                async with AsyncSession(engine) as db, db.begin():
                    service = CapabilityApplication(db, operations_tenant_id=scope.other_tenant)
                    await service._governance()
                    governance_locked.set()
                    await service.grant(
                        actor,
                        command_id=uuid4(),
                        subject_person_id=scope.subject,
                        permission="catalog_read",
                        scope=CapabilityScope("tenant", scope.tenant),
                        reason="Verify concurrent ordinary identity and management",
                    )

            await asyncio.wait_for(asyncio.gather(normal_identity(), management()), timeout=15)
        finally:
            await engine.dispose()

    _run_async(exercise())


@pytest.mark.parametrize("lifecycle", ["tenant", "membership"])
def test_postgresql_resource_lifecycle_waits_for_authorized_action(
    postgres_harness: Engine,
    lifecycle: str,
) -> None:
    with Session(postgres_harness) as db:
        scope = seed_scope(db)

    async def exercise() -> None:
        engine = create_async_engine(postgres_harness.url)
        writer: asyncio.Task[None] | None = None
        try:
            actor = await _manager_fixture(engine, scope)
            async with AsyncSession(engine) as db, db.begin():
                await CapabilityApplication(db, operations_tenant_id=scope.other_tenant).grant(
                    actor,
                    command_id=uuid4(),
                    subject_person_id=scope.subject,
                    permission="catalog_read",
                    scope=CapabilityScope("tenant", scope.tenant),
                    reason="Verify action lifecycle fencing",
                )

            writer_pid: asyncio.Future[int] = asyncio.get_running_loop().create_future()

            async def end_lifecycle() -> None:
                async with AsyncSession(engine) as db, db.begin():
                    writer_pid.set_result(await db.scalar(text("SELECT pg_backend_pid()")))
                    statement = (
                        update(Tenant).where(Tenant.id == scope.tenant).values(status="suspended")
                        if lifecycle == "tenant"
                        else update(Membership)
                        .where(
                            Membership.tenant_id == scope.tenant,
                            Membership.person_id == scope.subject,
                        )
                        .values(status="inactive", ended_at=datetime.now(UTC))
                    )
                    await db.execute(statement)

            async with AsyncSession(engine) as action, action.begin():
                await CapabilityApplication(
                    action, operations_tenant_id=scope.other_tenant
                ).require(scope.subject, "catalog_read", CapabilityScope("tenant", scope.tenant))
                writer = asyncio.create_task(end_lifecycle())
                pid = await asyncio.wait_for(writer_pid, timeout=5)
                # Observe an actual PostgreSQL blocked lock; elapsed time alone
                # is not evidence that lifecycle mutation was fenced.
                async with AsyncSession(engine) as observer:

                    async def observe_block() -> None:
                        while True:
                            blocked = await observer.scalar(
                                text("SELECT cardinality(pg_blocking_pids(:pid)) > 0"), {"pid": pid}
                            )
                            if blocked:
                                return
                            assert not writer.done(), "lifecycle write bypassed action locks"
                            await asyncio.sleep(0.02)

                    await asyncio.wait_for(observe_block(), timeout=5)
            await asyncio.wait_for(writer, timeout=5)
            async with AsyncSession(engine) as db, db.begin():
                with pytest.raises(CapabilityDenied):
                    await CapabilityApplication(
                        db, operations_tenant_id=scope.other_tenant
                    ).require(
                        scope.subject, "catalog_read", CapabilityScope("tenant", scope.tenant)
                    )
        finally:
            if writer is not None and not writer.done():
                writer.cancel()
                await asyncio.gather(writer, return_exceptions=True)
            await engine.dispose()

    _run_async(exercise())
