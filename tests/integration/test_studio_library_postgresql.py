"""Actual picker SQL and lifecycle-lock evidence in a disposable migrated schema.

Uses the established loopback-only harness. Never migrates the runtime/public
schema and never claims this service test proves HTTP authentication or playback.
"""

import asyncio
import os
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.engine import URL, make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from ac_platform.authorization.policy import CapabilityDenied
from ac_platform.catalog.models import ProgramVersion
from ac_platform.catalog.services import CatalogService, SqlAlchemyCatalogStore
from ac_platform.media.models import (
    ActivityMediaBinding,
    MediaAsset,
    MediaUploadIntent,
    MediaVersion,
)
from ac_platform.media.studio_library import StudioVideoLibrary, StudioVideoLibraryQuery
from ac_platform.tenancy.models import Membership
from tests.integration.test_media_delivery_renewal_postgresql import (
    _postgres_url,
    _run_async,
    _transaction_timeouts,
)
from tests.integration.test_media_delivery_renewal_postgresql import (
    postgres_harness as postgres_harness,  # noqa: F401 - dynamically requested after preflight
)
from tests.integration.test_studio_draft_authoring_postgresql import seed


def _validate_studio_postgres_target(url: URL, environment: Mapping[str, str]) -> None:
    """Fail before any inherited fixture connection or migration can run.

    The shared harness currently supplies migration isolation through PGOPTIONS.
    Connection query options can override it, and libpq endpoint/service options
    can redirect an apparently loopback URL. Accept a plain explicit local URL
    only. Never include connection details in a failure message.
    """

    if (
        url.get_backend_name() != "postgresql"
        or url.host not in {"127.0.0.1", "localhost", "::1"}
        or not url.database
        or url.query
        or any(
            environment.get(key)
            for key in ("PGHOSTADDR", "PGSERVICE", "PGSERVICEFILE", "PGOPTIONS")
        )
    ):
        raise ValueError("Studio PostgreSQL proof requires a plain explicit loopback test URL.")


@pytest.fixture(scope="module")
def studio_postgres_harness(request):
    # Dynamic dependency is intentional: validate BEFORE shared fixture setup.
    _validate_studio_postgres_target(_postgres_url(), os.environ)
    return request.getfixturevalue("postgres_harness")


@pytest.mark.parametrize(
    "raw",
    [
        "postgresql://127.0.0.1/test?options=+",
        "postgresql://127.0.0.1/test?options=-csearch_path%3Dpublic",
        "postgresql://127.0.0.1/test?host=remote.invalid",
        "postgresql://127.0.0.1/test?hostaddr=192.0.2.1",
        "postgresql://127.0.0.1/test?service=remote",
        "postgresql://127.0.0.1/test?sslmode=disable",
        "postgresql://remote.invalid/test",
        "postgresql:///test",
        "postgresql://127.0.0.1",
        "sqlite:///test",
    ],
)
def test_preflight_rejects_ambiguous_or_redirected_connections(raw):
    with pytest.raises(ValueError, match="plain explicit loopback"):
        _validate_studio_postgres_target(make_url(raw), {})


@pytest.mark.parametrize("key", ["PGHOSTADDR", "PGSERVICE", "PGSERVICEFILE", "PGOPTIONS"])
def test_preflight_rejects_inherited_connection_overrides(key):
    with pytest.raises(ValueError, match="plain explicit loopback"):
        _validate_studio_postgres_target(
            make_url("postgresql://127.0.0.1/test"), {key: "synthetic-override"}
        )


@pytest.mark.parametrize("host", ["127.0.0.1", "localhost", "[::1]"])
def test_preflight_accepts_plain_explicit_loopback_target(host):
    _validate_studio_postgres_target(make_url(f"postgresql://{host}/test"), {})


def test_invalid_target_is_rejected_before_resolving_shared_fixture(monkeypatch):
    monkeypatch.setenv(
        "AC_MEDIA_DELIVERY_RENEWAL_POSTGRES_TEST_URL",
        "postgresql://127.0.0.1/test?options=+",
    )

    class RequestWithoutDatabase:
        def getfixturevalue(self, _name):
            pytest.fail("shared database fixture must not run for an unsafe target")

    with pytest.raises(ValueError, match="plain explicit loopback"):
        studio_postgres_harness.__wrapped__(RequestWithoutDatabase())


def test_picker_uses_real_scoped_sql_and_serializes_membership_end(studio_postgres_harness):
    postgres_harness = studio_postgres_harness

    async def scenario():
        engine = create_async_engine(postgres_harness.schema_url, pool_size=4, max_overflow=0)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        end_task = None
        try:
            state = await seed(sessions)
            actor = state.actors[0]
            async with sessions() as database, database.begin():
                media = {}
                for number, owner in (
                    (100, actor),
                    (101, actor),
                    (102, actor),
                    (200, state.actors[1]),
                    (201, state.actors[1]),
                ):
                    asset_id, version_id = UUID(int=number), uuid4()
                    asset = MediaAsset(
                        id=asset_id,
                        tenant_id=state.tenant_id,
                        owner_person_id=owner.person_id,
                        purpose="video",
                        state="expected",
                        current_version_id=None,
                    )
                    database.add(asset)
                    await database.flush()
                    version = MediaVersion(
                        id=version_id,
                        tenant_id=state.tenant_id,
                        asset_id=asset_id,
                        version_number=1,
                        purpose="video",
                        state="ready",
                        content_type="video/mp4",
                        object_key=f"test-private/{version_id}",
                        declared_bytes=1000,
                        actual_bytes=1000,
                        duration_seconds=10,
                        width=1920,
                        height=1080,
                    )
                    database.add(version)
                    await database.flush()
                    asset.current_version_id = version_id
                    asset.state = "ready"
                    await database.flush()
                    database.add(
                        MediaUploadIntent(
                            tenant_id=state.tenant_id,
                            actor_person_id=owner.person_id,
                            asset_id=asset_id,
                            version_id=version_id,
                            filename=f"Lesson {number}.mp4",
                            object_key=f"test-private/{version_id}",
                            content_type="video/mp4",
                            declared_bytes=1000,
                            max_bytes=1000,
                            state="ready",
                            request_fingerprint="a" * 64,
                            expires_at=datetime.now(UTC) + timedelta(hours=1),
                        )
                    )
                    media[number] = (asset_id, version_id)

                def published_activity(sync):
                    catalog = CatalogService(SqlAlchemyCatalogStore(sync))
                    activity = catalog.add_activity(
                        state.module_id,
                        tenant_id=state.tenant_id,
                        kind="VIDEO",
                        title="Isolated approved media fixture",
                    )
                    version = catalog.get_version(state.version_id, tenant_id=state.tenant_id)
                    row = sync.get(ProgramVersion, state.version_id)
                    row.content_digest = catalog._canonical_content_digest(version)  # noqa: SLF001
                    sync.flush()
                    catalog.publish_version(state.version_id, tenant_id=state.tenant_id)
                    return activity.id

                activity_id = await database.run_sync(published_activity)
                database.add(
                    ActivityMediaBinding(
                        tenant_id=state.tenant_id,
                        activity_id=activity_id,
                        module_id=state.module_id,
                        program_version_id=state.version_id,
                        program_id=state.program_id,
                        program_scope="tenant",
                        program_owner_key=state.tenant_id,
                        activity_version=f"activity:{activity_id}",
                        asset_id=media[200][0],
                        version_id=media[200][1],
                        state="approved",
                        approval_reference="Isolated relational approval fixture",
                        approved_by_person_id=state.actors[1].person_id,
                        idempotency_key=uuid4().hex,
                        request_fingerprint="a" * 64,
                    )
                )

            async with sessions() as database, database.begin():
                library = StudioVideoLibrary(database)
                first = await library.list_choices(
                    actor,
                    program_id=state.program_id,
                    query=StudioVideoLibraryQuery(limit=2),
                )
                assert [item.asset_id for item in first.items] == [UUID(int=100), UUID(int=101)]
                assert first.next_cursor == UUID(int=101)
                second = await library.list_choices(
                    actor,
                    program_id=state.program_id,
                    query=StudioVideoLibraryQuery(limit=2, after=first.next_cursor),
                )
                assert [item.asset_id for item in second.items] == [UUID(int=102), UUID(int=200)]
                assert [item.label for item in second.items] == ["Lesson 102.mp4", "Lesson 200.mp4"]
                assert second.next_cursor is None
                assert "test-private" not in second.model_dump_json()
                with pytest.raises(CapabilityDenied):
                    await library.list_choices(actor, program_id=uuid4())

            started = asyncio.Event()
            pids = {}

            async def end_membership():
                async with sessions() as writer, writer.begin():
                    pids["writer"] = await _transaction_timeouts(writer)
                    membership = await writer.get(Membership, (state.tenant_id, actor.person_id))
                    membership.status = "inactive"
                    membership.ended_at = datetime.now(UTC)
                    started.set()
                    await writer.flush()

            async with sessions() as reader, reader.begin():
                pids["reader"] = await _transaction_timeouts(reader)
                assert (
                    await StudioVideoLibrary(reader).list_choices(
                        actor,
                        program_id=state.program_id,
                    )
                ).items
                end_task = asyncio.create_task(end_membership())
                await asyncio.wait_for(started.wait(), 8)
                async with sessions() as observer, asyncio.timeout(5):
                    while pids["reader"] not in await observer.scalar(
                        select(func.pg_blocking_pids(pids["writer"]))
                    ):
                        if end_task.done():
                            pytest.fail("membership update did not wait for the authorized read")
                        await asyncio.sleep(0.01)
            await asyncio.wait_for(end_task, 8)
            async with sessions() as database, database.begin():
                with pytest.raises(CapabilityDenied):
                    await StudioVideoLibrary(database).list_choices(
                        actor,
                        program_id=state.program_id,
                        query=StudioVideoLibraryQuery(after=first.next_cursor),
                    )
        finally:
            if end_task is not None:
                if not end_task.done():
                    end_task.cancel()
                await asyncio.gather(end_task, return_exceptions=True)
            await engine.dispose()

    _run_async(scenario())
