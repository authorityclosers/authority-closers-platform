"""New-course retries on real PostgreSQL locks in a fresh migrated test schema."""

import asyncio

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from ac_platform.audit.models import AuditEvent
from ac_platform.audit.service import AuditRepository, verify_audit_chain_sync
from ac_platform.authorization.models import CapabilityGrant
from ac_platform.catalog.models import CatalogAuthoringCommand, Program, ProgramVersion
from ac_platform.catalog.services import AsyncCatalogApplication, CatalogConflictError
from tests.integration.test_media_delivery_renewal_postgresql import (
    _run_async,
    _transaction_timeouts,
    postgres_harness,  # noqa: F401 - isolated migrated schema only
)
from tests.integration.test_studio_draft_authoring_postgresql import seed


@pytest.mark.parametrize("scenario", ["same_key", "different_key", "different_intent"])
def test_real_actor_lock_serializes_course_creation_and_receipts(postgres_harness, scenario):  # noqa: F811
    async def run():
        engine = create_async_engine(
            postgres_harness.schema_url, pool_size=4, max_overflow=0, hide_parameters=True
        )
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        try:
            state = await seed(sessions)
            actor = state.actors[0]
            async with sessions() as database, database.begin():
                for permission in ("catalog_read", "catalog_write"):
                    audit = await AuditRepository(database).append_for_actor(
                        actor, action="test.course_creator", resource_type="capability_grant"
                    )
                    database.add(
                        CapabilityGrant(
                            subject_person_id=actor.person_id,
                            permission=permission,
                            scope_kind="tenant",
                            tenant_id=state.tenant_id,
                            program_id=None,
                            granted_by_person_id=actor.person_id,
                            audit_event_id=audit.id,
                            reason="Isolated test fixture",
                        )
                    )
                    await database.flush()
            written, started, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
            pids = {}

            async def create(database, *, second=False):
                return await AsyncCatalogApplication(database).create_program_draft(
                    actor=actor,
                    tenant_id=state.tenant_id,
                    title="Changed title"
                    if second and scenario == "different_intent"
                    else "Synthetic new course",
                    idempotency_key="second" if second and scenario == "different_key" else "same",
                )

            async def first():
                async with sessions() as database, database.begin():
                    pids["first"] = await _transaction_timeouts(database)
                    result = await create(database)
                    written.set()
                    await asyncio.wait_for(release.wait(), 8)
                    return result

            async def second():
                await asyncio.wait_for(written.wait(), 8)
                async with sessions() as database, database.begin():
                    pids["second"] = await _transaction_timeouts(database)
                    started.set()
                    return await create(database, second=True)

            tasks = [asyncio.create_task(first()), asyncio.create_task(second())]
            try:
                await asyncio.wait_for(started.wait(), 8)
                async with sessions() as observer, asyncio.timeout(5):
                    while pids["first"] not in await observer.scalar(
                        select(func.pg_blocking_pids(pids["second"]))
                    ):
                        if tasks[1].done():
                            pytest.fail(
                                "second command did not wait on the original actor transaction"
                            )
                        await asyncio.sleep(0.01)
                    assert (
                        await observer.scalar(
                            select(func.count())
                            .select_from(CatalogAuthoringCommand)
                            .where(CatalogAuthoringCommand.tenant_id == state.tenant_id)
                        )
                        == 0
                    )
                release.set()
                a, b = await asyncio.wait_for(asyncio.gather(*tasks, return_exceptions=True), 8)
            finally:
                release.set()
                for task in tasks:
                    if not task.done():
                        task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
            assert not isinstance(a, BaseException)
            if scenario == "different_intent":
                assert isinstance(b, CatalogConflictError)
            else:
                assert not isinstance(b, BaseException)
                assert b.replayed == (scenario == "same_key")
                assert (a.program_id == b.program_id) == (scenario == "same_key")
            expected = 2 if scenario == "different_key" else 1
            async with sessions() as database, database.begin():
                assert (
                    await database.scalar(
                        select(func.count())
                        .select_from(Program)
                        .where(Program.tenant_id == state.tenant_id)
                    )
                    == 1 + expected
                )
                assert (
                    await database.scalar(
                        select(func.count())
                        .select_from(ProgramVersion)
                        .where(ProgramVersion.tenant_id == state.tenant_id)
                    )
                    == 1 + expected
                )
                assert (
                    await database.scalar(
                        select(func.count())
                        .select_from(CatalogAuthoringCommand)
                        .where(CatalogAuthoringCommand.tenant_id == state.tenant_id)
                    )
                    == expected
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
                    == expected
                )
                assert (
                    await database.run_sync(
                        lambda sync: verify_audit_chain_sync(sync, state.tenant_id)
                    )
                ).valid
        finally:
            await engine.dispose()

    _run_async(run())
