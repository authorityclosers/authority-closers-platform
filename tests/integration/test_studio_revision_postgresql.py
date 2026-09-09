"""Real PostgreSQL revision races in a fresh migrated schema, never runtime tables."""

import asyncio
import os
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.schema import CreateSchema, DropSchema

from ac_platform.audit.models import AuditEvent
from ac_platform.audit.service import verify_audit_chain_sync
from ac_platform.catalog.models import CatalogAuthoringCommand, Module, ProgramVersion
from ac_platform.catalog.services import (
    AsyncCatalogApplication,
    CatalogService,
    SqlAlchemyCatalogStore,
)
from tests.integration.test_catalog_publication_migration_postgresql import _run_migration
from tests.integration.test_media_delivery_renewal_postgresql import (
    _postgres_url,
    _run_async,
    _transaction_timeouts,
    postgres_harness,  # noqa: F401 - fresh schema only
)
from tests.integration.test_studio_draft_authoring_postgresql import append, seed


async def published_fixture(sessions):
    state = await seed(sessions)
    async with sessions() as database, database.begin():
        await AsyncCatalogApplication(database).publish_version(
            state.version_id,
            actor=state.actors[0],
            tenant_id=state.tenant_id,
            expected_etag=state.expected_etag,
        )

        def source_etag(sync):
            catalog = CatalogService(SqlAlchemyCatalogStore(sync))
            source = catalog.get_version(state.version_id, tenant_id=state.tenant_id)
            return catalog.publication_etag(source)

        state.expected_etag = await database.run_sync(source_etag)
    return state


async def revise(database, state, *, actor_index=0, key="first"):
    return await AsyncCatalogApplication(database).revise_published_version(
        actor=state.actors[actor_index],
        tenant_id=state.tenant_id,
        program_version_id=state.version_id,
        expected_etag=state.expected_etag,
        idempotency_key=key,
    )


@pytest.mark.parametrize("scenario", ["different_actors", "same_actor_new_key", "same_key"])
def test_real_revision_lock_serializes_numbering_and_exact_retry(postgres_harness, scenario):  # noqa: F811
    async def run():
        engine = create_async_engine(
            postgres_harness.schema_url, pool_size=4, max_overflow=0, hide_parameters=True
        )
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        try:
            state = await published_fixture(sessions)
            first_done, second_started, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
            pids = {}

            async def first():
                async with sessions() as database, database.begin():
                    pids["first"] = await _transaction_timeouts(database)
                    result = await revise(database, state)
                    first_done.set()
                    await asyncio.wait_for(release.wait(), 8)
                    return result

            async def second():
                await asyncio.wait_for(first_done.wait(), 8)
                async with sessions() as database, database.begin():
                    pids["second"] = await _transaction_timeouts(database)
                    second_started.set()
                    return await revise(
                        database,
                        state,
                        actor_index=1 if scenario == "different_actors" else 0,
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
                            pytest.fail("second revision did not wait for the first transaction")
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
                first_result, second_result = await asyncio.wait_for(asyncio.gather(*tasks), 8)
            finally:
                release.set()
                for task in tasks:
                    if not task.done():
                        task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
            assert first_result.replayed is False
            expected_writes = 1 if scenario == "same_key" else 2
            assert second_result.replayed is (scenario == "same_key")
            assert (first_result.resource_id == second_result.resource_id) is (
                scenario == "same_key"
            )
            async with sessions() as database:
                versions = tuple(
                    await database.scalars(
                        select(ProgramVersion)
                        .where(ProgramVersion.program_id == state.program_id)
                        .order_by(ProgramVersion.version_number)
                    )
                )
                assert [version.version_number for version in versions] == list(
                    range(1, expected_writes + 2)
                )
                assert versions[0].id == state.version_id and versions[0].status == "published"
                for version in versions[1:]:
                    assert (
                        version.status == "draft"
                        and version.supersedes_version_id == state.version_id
                    )
                    assert version.content_reviewed_by is None and version.content_digest is None
                    assert (
                        await database.scalar(
                            select(func.count())
                            .select_from(Module)
                            .where(Module.program_version_id == version.id)
                        )
                        == 1
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


def test_revision_rollback_and_receipt_trigger_survive_forward_migration(postgres_harness):  # noqa: F811
    async def run():
        engine = create_async_engine(postgres_harness.schema_url, hide_parameters=True)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        try:
            state = await published_fixture(sessions)
            with pytest.raises(RuntimeError, match="rollback revision fixture"):
                async with sessions() as database, database.begin():
                    await revise(database, state)
                    raise RuntimeError("rollback revision fixture")
            async with sessions() as database, database.begin():
                assert (
                    await database.scalar(
                        select(func.count())
                        .select_from(ProgramVersion)
                        .where(ProgramVersion.program_id == state.program_id)
                    )
                    == 1
                )
                assert (
                    await database.scalar(
                        select(func.count())
                        .select_from(CatalogAuthoringCommand)
                        .where(CatalogAuthoringCommand.tenant_id == state.tenant_id)
                    )
                    == 0
                )
                result = await revise(database, state)
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
            async with sessions() as database:
                assert (
                    await database.run_sync(
                        lambda sync: verify_audit_chain_sync(sync, state.tenant_id)
                    )
                ).valid
        finally:
            await engine.dispose()

    _run_async(run())


def test_populated_0022_upgrade_preserves_receipts_and_admits_only_new_operation():
    base_url = _postgres_url()
    schema = f"studio_revision_migration_{uuid4().hex}"
    owner = create_engine(base_url, hide_parameters=True)
    created = False
    try:
        with owner.begin() as connection:
            connection.execute(CreateSchema(schema))
        created = True
        schema_url = base_url.set(query={**base_url.query, "options": f"-csearch_path={schema}"})
        environment = {
            **os.environ,
            "AC_DATABASE_URL": base_url.render_as_string(hide_password=False),
            "AC_DATABASE_MIGRATOR_URL": base_url.render_as_string(hide_password=False),
            "AC_ENVIRONMENT": "test",
            "PGOPTIONS": f"-csearch_path={schema}",
            "PYTHONPATH": str(Path(__file__).parents[2] / "packages" / "python"),
        }
        assert _run_migration(environment, "20260908_0022").returncode == 0, (
            "isolated0022 migration failed"
        )

        async def before_upgrade():
            engine = create_async_engine(schema_url, hide_parameters=True)
            sessions = async_sessionmaker(engine, expire_on_commit=False)
            try:
                old_state = await seed(sessions)
                async with sessions() as database, database.begin():
                    old_result = await append(database, old_state)
                revision_state = await published_fixture(sessions)
                with pytest.raises(IntegrityError):
                    async with sessions() as database, database.begin():
                        await revise(database, revision_state)
                async with sessions() as database:
                    rows = tuple(
                        (await database.execute(select(CatalogAuthoringCommand.__table__))).all()
                    )
                    assert len(rows) == 1 and rows[0].resource_id == old_result.resource_id
                    assert (
                        await database.scalar(
                            select(func.count())
                            .select_from(ProgramVersion)
                            .where(ProgramVersion.program_id == revision_state.program_id)
                        )
                        == 1
                    )
                return old_state, old_result, revision_state, rows
            finally:
                await engine.dispose()

        old_state, old_result, revision_state, old_rows = _run_async(before_upgrade())
        assert _run_migration(environment, "20260909_0023").returncode == 0, (
            "isolated0023 migration failed"
        )

        async def after_upgrade():
            engine = create_async_engine(schema_url, hide_parameters=True)
            sessions = async_sessionmaker(engine, expire_on_commit=False)
            try:
                async with sessions() as database, database.begin():
                    rows = tuple(
                        (await database.execute(select(CatalogAuthoringCommand.__table__))).all()
                    )
                    assert rows == old_rows
                    replay = await append(database, old_state)
                    assert replay.replayed is True and replay.resource_id == old_result.resource_id
                    revised = await revise(database, revision_state)
                    assert revised.replayed is False
                async with sessions() as database:
                    assert (
                        await database.run_sync(
                            lambda sync: verify_audit_chain_sync(sync, old_state.tenant_id)
                        )
                    ).valid
                    assert (
                        await database.run_sync(
                            lambda sync: verify_audit_chain_sync(sync, revision_state.tenant_id)
                        )
                    ).valid
                    receipt_id = await database.scalar(
                        select(CatalogAuthoringCommand.id).where(
                            CatalogAuthoringCommand.resource_id == revised.resource_id
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

        _run_async(after_upgrade())
    finally:
        if created:
            with owner.begin() as connection:
                connection.execute(DropSchema(schema, cascade=True))
        owner.dispose()
