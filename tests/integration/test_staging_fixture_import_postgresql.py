"""Real AsyncSession/locking acceptance in a disposable migrated PG schema.

Uses the existing staging-seed AC_TEST_DATABASE_URL target guard and isolated
schema fixture. No configured URL means an explicit skip, never a SQLite pass.
The small package substitution is a pytest-only manifest fixture, not a CLI
input or runtime validation bypass.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import event, func, select
from sqlalchemy.engine import URL
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from ac_platform.audit import AuditRepository
from ac_platform.audit.models import AuditEvent
from ac_platform.identity.models import Person
from ac_platform.kernel.authz import ActorContext
from ac_platform.media.errors import MediaConflict, MediaForbidden
from ac_platform.media.models import (
    ActivityMediaBinding,
    MediaAsset,
    MediaCaptionTrack,
    MediaRendition,
    MediaVersion,
)
from ac_platform.media.service import MediaService
from ac_platform.media.staging_fixture_import import (
    StagingFixtureImportApplication,
    _TenantStagingSeedApplication,
)
from ac_platform.media.staging_fixture_manifest import load_verified_staging_fixture_pack
from ac_platform.seed.technical_media_fixture_v2 import technical_media_seed
from ac_platform.tenancy.models import Membership, Tenant
from tests.integration.test_staging_seed_postgresql import _run_async
from tests.integration.test_staging_seed_postgresql import postgres_harness as postgres_harness
from tests.unit.media.test_staging_fixture_import import RELEASE
from tests.unit.media.test_staging_fixture_import import artifact_factory as artifact_factory


@asynccontextmanager
async def scenario(schema_url: URL, artifact):
    query = dict(schema_url.query)
    query["options"] = str(query.get("options", "")) + " -cstatement_timeout=15000"
    engine = create_async_engine(schema_url.set(query=query), pool_size=4, max_overflow=0)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    actor_id, other_actor = uuid4(), uuid4()
    pack = load_verified_staging_fixture_pack(
        environment="test",
        release_id=RELEASE,
        tenant_id=artifact.tenant_id,
        root=artifact.root,
        expected_manifest_sha256=artifact.digest,
    )
    try:
        async with sessions() as database, database.begin():
            database.add_all(
                [
                    Person(id=actor_id),
                    Person(id=other_actor),
                    Tenant(
                        id=pack.tenant_id, slug=f"film-pg-{pack.tenant_id.hex}", name="PG film test"
                    ),
                ]
            )
            await database.flush()
            database.add_all(
                [
                    Membership(tenant_id=pack.tenant_id, person_id=actor_id, role="owner"),
                    Membership(tenant_id=pack.tenant_id, person_id=other_actor, role="admin"),
                ]
            )
        async with sessions() as database:
            published = await _TenantStagingSeedApplication(
                database,
                environment="test",
                release_id=RELEASE,
                tenant_id=pack.tenant_id,
            ).apply_technical_validation(
                technical_media_seed(RELEASE),
                actor=ActorContext(actor_id, uuid4(), None),
            )
        yield SimpleNamespace(
            engine=engine,
            sessions=sessions,
            actor_id=actor_id,
            other_actor=other_actor,
            pack=pack,
            catalog_version_id=published.program_version_id,
        )
    finally:
        await engine.dispose()


async def import_once(h, actor_id=None):
    async with h.sessions() as database:
        return await StagingFixtureImportApplication(
            database,
            environment="test",
            release_id=RELEASE,
            pack=h.pack,
        ).apply(
            actor_person_id=actor_id or h.actor_id, expected_catalog_version_id=h.catalog_version_id
        )


async def concurrent_results(*operations):
    """Bound the race and close all sibling transactions on any failure."""
    tasks = [asyncio.create_task(operation) for operation in operations]
    try:
        return await asyncio.wait_for(asyncio.gather(*tasks), timeout=30)
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


async def assert_imported_once(h, expected_actor, expected_ids):
    async with h.sessions() as database, database.begin():
        for model, expected_count in (
            (MediaAsset, 2),
            (MediaVersion, 2),
            (MediaRendition, 4),
            (MediaCaptionTrack, 2),
            (ActivityMediaBinding, 2),
            (AuditEvent, 1),
        ):
            assert (
                await database.scalar(
                    select(func.count())
                    .select_from(model)
                    .where(
                        model.tenant_id == h.pack.tenant_id,
                    )
                )
                == expected_count
            )
        versions = (
            await database.scalars(
                select(MediaVersion).where(
                    MediaVersion.tenant_id == h.pack.tenant_id,
                )
            )
        ).all()
        assert all(row.state == "ready" and row.duration_seconds == 12.032 for row in versions)
        bindings = (
            await database.scalars(
                select(ActivityMediaBinding).where(
                    ActivityMediaBinding.tenant_id == h.pack.tenant_id,
                )
            )
        ).all()
        assert {row.id for row in bindings} == set(expected_ids)
        assert all(row.state == "approved" for row in bindings)
        audit = await database.scalar(
            select(AuditEvent).where(
                AuditEvent.tenant_id == h.pack.tenant_id,
            )
        )
        assert audit is not None and audit.actor_person_id == expected_actor
        assert audit.session_id is None
        assert (await AuditRepository(database).verify(h.pack.tenant_id)).valid


async def assert_no_import(h):
    async with h.sessions() as database, database.begin():
        for model in (
            MediaAsset,
            MediaVersion,
            MediaRendition,
            MediaCaptionTrack,
            ActivityMediaBinding,
            AuditEvent,
        ):
            assert (
                await database.scalar(
                    select(func.count())
                    .select_from(model)
                    .where(
                        model.tenant_id == h.pack.tenant_id,
                    )
                )
                == 0
            )


def test_postgres_real_async_import_and_same_actor_replay(postgres_harness, artifact_factory):
    artifact = artifact_factory()

    async def run():
        async with scenario(postgres_harness, artifact) as h:
            first = await import_once(h)
            replay = await import_once(h)
            assert first.status == "imported" and replay.status == "already_imported"
            assert first.binding_ids == replay.binding_ids
            assert first.media_version_ids == replay.media_version_ids
            await assert_imported_once(h, h.actor_id, first.binding_ids)

    _run_async(run())


def test_postgres_concurrent_same_actor_import_has_one_audit_and_binding_pair(
    postgres_harness,
    artifact_factory,
):
    artifact = artifact_factory()

    async def run():
        async with scenario(postgres_harness, artifact) as h:
            ready = asyncio.Barrier(3)

            async def concurrent():
                await ready.wait()
                return await import_once(h)

            results = await concurrent_results(concurrent(), concurrent(), concurrent())
            assert sorted(row.status for row in results) == [
                "already_imported",
                "already_imported",
                "imported",
            ]
            assert all(row.binding_ids == results[0].binding_ids for row in results)
            await assert_imported_once(h, h.actor_id, results[0].binding_ids)

    _run_async(run())


def test_postgres_concurrent_distinct_admins_do_not_reassign_approval_or_audit(
    postgres_harness,
    artifact_factory,
):
    artifact = artifact_factory()

    async def run():
        async with scenario(postgres_harness, artifact) as h:
            ready = asyncio.Barrier(2)

            async def concurrent(actor_id):
                await ready.wait()
                try:
                    return actor_id, await import_once(h, actor_id)
                except MediaConflict as error:
                    return actor_id, error

            results = await concurrent_results(concurrent(h.actor_id), concurrent(h.other_actor))
            successes = [
                (actor, value) for actor, value in results if not isinstance(value, Exception)
            ]
            failures = [value for _, value in results if isinstance(value, Exception)]
            assert len(successes) == len(failures) == 1
            actor, result = successes[0]
            assert result.status == "imported" and isinstance(failures[0], MediaConflict)
            await assert_imported_once(h, actor, result.binding_ids)

    _run_async(run())


def test_postgres_exact_tenant_advisory_lock_blocks_until_owner_transaction_finishes(
    postgres_harness,
    artifact_factory,
):
    artifact = artifact_factory()

    async def run():
        async with scenario(postgres_harness, artifact) as h:
            lock_key = int.from_bytes(h.pack.tenant_id.bytes[:8], "big", signed=True)
            attempted = asyncio.Event()

            def observe(_connection, _cursor, statement, _parameters, _context, _many):
                if "pg_advisory_xact_lock" in statement:
                    attempted.set()

            task = None
            listening = False
            try:
                async with h.sessions() as blocker, blocker.begin():
                    await blocker.execute(select(func.pg_advisory_xact_lock(lock_key)))
                    event.listen(h.engine.sync_engine, "before_cursor_execute", observe)
                    listening = True
                    task = asyncio.create_task(import_once(h))
                    await asyncio.wait_for(attempted.wait(), timeout=10)
                    # The second real connection reached the lock statement,
                    # but cannot finish while the first transaction owns it.
                    assert not task.done()
                    async with h.sessions() as observer, observer.begin():
                        assert not await observer.scalar(
                            select(func.pg_try_advisory_xact_lock(lock_key))
                        )
                result = await asyncio.wait_for(task, timeout=20)
                assert result.status == "imported"
                await assert_imported_once(h, h.actor_id, result.binding_ids)
            finally:
                if listening:
                    event.remove(h.engine.sync_engine, "before_cursor_execute", observe)
                if task is not None and not task.done():
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)

    _run_async(run())


@pytest.mark.parametrize("failure", ["second_processing", "second_binding", "audit"])
def test_postgres_failure_rolls_back_both_films_bindings_and_audit(
    postgres_harness,
    artifact_factory,
    monkeypatch,
    failure,
):
    artifact = artifact_factory()

    async def run():
        async with scenario(postgres_harness, artifact) as h:
            if failure == "second_processing":
                original = MediaService.process_version

                def fail_second(self, database, actor, version_id):
                    if version_id == h.pack.clips[1].version_id:
                        raise MediaConflict("test second-film processing refusal")
                    return original(self, database, actor, version_id)

                monkeypatch.setattr(MediaService, "process_version", fail_second)
            elif failure == "second_binding":
                original_binding = MediaService.bind_activity_media

                def fail_binding(self, database, actor, request, *, idempotency_key):
                    if request.version_id == h.pack.clips[1].version_id:
                        raise MediaConflict("test second-film binding refusal")
                    return original_binding(
                        self, database, actor, request, idempotency_key=idempotency_key
                    )

                monkeypatch.setattr(MediaService, "bind_activity_media", fail_binding)
            else:

                async def fail_audit(self, **kwargs):
                    raise MediaConflict("test final audit refusal")

                monkeypatch.setattr(AuditRepository, "append", fail_audit)
            with pytest.raises(MediaConflict):
                await import_once(h)
            await assert_no_import(h)

    _run_async(run())


@pytest.mark.parametrize("change", ["learner", "other_tenant_only", "ended", "person", "tenant"])
def test_postgres_persisted_role_and_exact_tenant_are_required(
    postgres_harness,
    artifact_factory,
    change,
):
    artifact = artifact_factory()

    async def run():
        async with scenario(postgres_harness, artifact) as h:
            async with h.sessions() as database, database.begin():
                member = await database.get(Membership, (h.pack.tenant_id, h.actor_id))
                assert member is not None
                if change == "learner":
                    member.role = "learner"
                elif change == "other_tenant_only":
                    member.role = "learner"
                    other_tenant = Tenant(id=uuid4(), slug=f"other-{uuid4().hex}", name="Other")
                    database.add(other_tenant)
                    await database.flush()
                    database.add(
                        Membership(tenant_id=other_tenant.id, person_id=h.actor_id, role="owner")
                    )
                elif change == "ended":
                    member.status = "inactive"
                    member.ended_at = datetime.now(UTC)
                elif change == "person":
                    person = await database.get(Person, h.actor_id)
                    person.status = "suspended"
                else:
                    tenant = await database.get(Tenant, h.pack.tenant_id)
                    tenant.status = "suspended"
            with pytest.raises(MediaForbidden):
                await import_once(h)
            await assert_no_import(h)

    _run_async(run())
