"""Real blocked transactions in an isolated migrated PostgreSQL schema.

Reuses the loopback-only schema harness and its AC_MEDIA_DELIVERY_RENEWAL_POSTGRES_TEST_URL
configuration. This test never migrates or writes the runtime/public schema.
"""

import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from ac_platform.audit.models import AuditEvent
from ac_platform.audit.service import AuditRepository, verify_audit_chain_sync
from ac_platform.authorization.models import CapabilityGrant
from ac_platform.catalog.models import CatalogAuthoringCommand, Module, ProgramVersion
from ac_platform.catalog.services import (
    AsyncCatalogApplication,
    CatalogDraftPreconditionError,
    CatalogPublicationPreconditionError,
    CatalogService,
    PublishedVersionImmutableError,
    SqlAlchemyCatalogStore,
)
from ac_platform.identity.models import Person
from ac_platform.identity.models import Session as IdentitySession
from ac_platform.kernel.authz import ActorContext
from ac_platform.tenancy.models import Membership, Tenant
from tests.integration.test_media_delivery_renewal_postgresql import (
    _run_async,
    _transaction_timeouts,
    postgres_harness,  # noqa: F401 - shared isolated fixture
)


async def seed(sessions):
    now, tenant_id = datetime.now(UTC), uuid4()
    actors = tuple(ActorContext(uuid4(), uuid4(), tenant_id) for _ in range(2))
    async with sessions() as database, database.begin():
        database.add(Tenant(id=tenant_id, slug=tenant_id.hex, name="Isolated Studio academy"))
        for actor in actors:
            database.add(Person(id=actor.person_id, email_verified_at=now))
        await database.flush()
        for actor in actors:
            database.add(Membership(tenant_id=tenant_id, person_id=actor.person_id, role="learner"))
        await database.flush()
        for actor in actors:
            database.add(
                IdentitySession(
                    id=actor.session_id,
                    person_id=actor.person_id,
                    selected_tenant_id=tenant_id,
                    token_hash=actor.session_id.bytes * 2,
                    created_at=now,
                    expires_at=now + timedelta(hours=1),
                )
            )
        await database.flush()

        def catalog_fixture(sync):
            catalog = CatalogService(SqlAlchemyCatalogStore(sync))
            program = catalog.create_program(
                tenant_id=tenant_id, slug=uuid4().hex, title="Isolated authoring fixture"
            )
            version = catalog.create_version(program.id, tenant_id=tenant_id)
            module = catalog.add_module(version.id, tenant_id=tenant_id, title="Original")
            row = sync.get(ProgramVersion, version.id)
            row.content_digest = catalog._canonical_content_digest(version)  # noqa: SLF001
            row.content_source_ref = "test:studio-authoring-concurrency"
            row.content_reviewed_by = "Explicit isolated test review"
            row.content_reviewed_at = now
            row.release_id = "d" * 40
            row.content_seed_kind = "reviewed"
            sync.flush()
            version = catalog.get_version(version.id, tenant_id=tenant_id)
            return SimpleNamespace(
                program_id=program.id,
                version_id=version.id,
                module_id=module.id,
                expected_etag=catalog.publication_etag(version),
            )

        state = await database.run_sync(catalog_fixture)
        for actor in actors:
            for permission in ("catalog_read", "catalog_write", "catalog_publish"):
                audit = await AuditRepository(database).append_for_actor(
                    actor, action="test.studio_fixture", resource_type="capability_grant"
                )
                database.add(
                    CapabilityGrant(
                        subject_person_id=actor.person_id,
                        permission=permission,
                        scope_kind="program",
                        tenant_id=tenant_id,
                        program_id=state.program_id,
                        granted_by_person_id=actor.person_id,
                        audit_event_id=audit.id,
                        reason="Isolated fixture only",
                    )
                )
                await database.flush()
    state.actors, state.tenant_id = actors, tenant_id
    return state


async def append(database, state, *, actor_index=0, key="first", title="Appended"):
    return await AsyncCatalogApplication(database).author_draft(
        actor=state.actors[actor_index],
        tenant_id=state.tenant_id,
        program_version_id=state.version_id,
        operation="module_add",
        target_id=None,
        title=title,
        expected_etag=state.expected_etag,
        idempotency_key=key,
    )


@pytest.mark.parametrize("scenario", ["stale_writer", "same_key", "publish_first", "author_first"])
def test_real_program_lock_serializes_authoring_and_publication(postgres_harness, scenario):  # noqa: F811
    async def run():
        engine = create_async_engine(
            postgres_harness.schema_url, pool_size=4, max_overflow=0, hide_parameters=True
        )
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        try:
            state = await seed(sessions)
            first_done, second_started, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
            pids = {}

            async def publish(database, actor_index):
                return await AsyncCatalogApplication(database).publish_version(
                    state.version_id,
                    actor=state.actors[actor_index],
                    tenant_id=state.tenant_id,
                    expected_etag=state.expected_etag,
                )

            async def first():
                async with sessions() as database, database.begin():
                    pids["first"] = await _transaction_timeouts(database)
                    result = (
                        await publish(database, 0)
                        if scenario == "publish_first"
                        else await append(database, state)
                    )
                    first_done.set()
                    await asyncio.wait_for(release.wait(), 8)
                    return result

            async def second():
                await asyncio.wait_for(first_done.wait(), 8)
                async with sessions() as database, database.begin():
                    pids["second"] = await _transaction_timeouts(database)
                    second_started.set()
                    if scenario == "author_first":
                        return await publish(database, 1)
                    return await append(
                        database,
                        state,
                        actor_index=0 if scenario == "same_key" else 1,
                        key="first" if scenario == "same_key" else "second",
                    )

            tasks = [asyncio.create_task(first()), asyncio.create_task(second())]
            try:
                await asyncio.wait_for(second_started.wait(), 8)
                async with sessions() as observer, asyncio.timeout(5):
                    while pids["first"] not in await observer.scalar(
                        select(func.pg_blocking_pids(pids["second"]))
                    ):
                        if tasks[1].done():
                            pytest.fail("second command never waited on the first transaction")
                        await asyncio.sleep(0.01)
                    assert not tasks[1].done()
                    assert (
                        await observer.scalar(
                            select(func.count())
                            .select_from(CatalogAuthoringCommand)
                            .where(CatalogAuthoringCommand.tenant_id == state.tenant_id)
                        )
                        == 0
                    )
                release.set()
                first_result, second_result = await asyncio.wait_for(
                    asyncio.gather(*tasks, return_exceptions=True), 8
                )
            finally:
                release.set()
                for task in tasks:
                    if not task.done():
                        task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
            assert not isinstance(first_result, Exception)
            if scenario == "same_key":
                assert second_result.replayed is True
                assert second_result.resource_id == first_result.resource_id
            else:
                expected_error = {
                    "stale_writer": CatalogDraftPreconditionError,
                    "publish_first": PublishedVersionImmutableError,
                    "author_first": CatalogPublicationPreconditionError,
                }[scenario]
                assert isinstance(second_result, expected_error), type(second_result)
            async with sessions() as database:
                expected_writes = 0 if scenario == "publish_first" else 1
                assert (
                    await database.scalar(
                        select(func.count())
                        .select_from(Module)
                        .where(Module.program_version_id == state.version_id)
                    )
                    == 1 + expected_writes
                )
                assert (
                    await database.scalar(
                        select(func.count())
                        .select_from(CatalogAuthoringCommand)
                        .where(CatalogAuthoringCommand.tenant_id == state.tenant_id)
                    )
                    == expected_writes
                )
                assert (
                    await database.scalar(
                        select(func.count())
                        .select_from(AuditEvent)
                        .where(
                            AuditEvent.tenant_id == state.tenant_id,
                            AuditEvent.action == "audit.catalog.draft.authored.v1",
                        )
                    )
                    == expected_writes
                )
                assert (
                    await database.run_sync(
                        lambda sync: verify_audit_chain_sync(sync, state.tenant_id)
                    )
                ).valid
        finally:
            await engine.dispose()

    _run_async(run())


def test_real_rollback_and_database_receipt_immutability(postgres_harness):  # noqa: F811
    async def run():
        engine = create_async_engine(postgres_harness.schema_url, hide_parameters=True)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        try:
            state = await seed(sessions)
            with pytest.raises(RuntimeError, match="rollback fixture"):
                async with sessions() as database, database.begin():
                    await append(database, state)
                    raise RuntimeError("rollback fixture")
            async with sessions() as database, database.begin():
                assert (
                    await database.scalar(
                        select(func.count())
                        .select_from(CatalogAuthoringCommand)
                        .where(CatalogAuthoringCommand.tenant_id == state.tenant_id)
                    )
                    == 0
                )
                result = await append(database, state)
                receipt_id = await database.scalar(
                    select(CatalogAuthoringCommand.id).where(
                        CatalogAuthoringCommand.resource_id == result.resource_id
                    )
                )
            for sql in (
                "UPDATE catalog_authoring_commands SET operation='module_update' WHERE id=:id",
                "DELETE FROM catalog_authoring_commands WHERE id=:id",
            ):
                with pytest.raises(IntegrityError):
                    async with sessions() as database, database.begin():
                        await database.execute(text(sql), {"id": receipt_id})
        finally:
            await engine.dispose()

    _run_async(run())
