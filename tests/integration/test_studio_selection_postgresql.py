"""Actual migrated PG locks and full-app opaque-session Studio selection proof.

Only random disposable schema data is created. No live account, media bytes,
delivery entitlement or external provider is activated by these tests.
"""

import asyncio
import importlib
import logging
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import func, insert, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from ac_platform.audit.models import AuditEvent
from ac_platform.audit.service import verify_audit_chain_sync
from ac_platform.catalog.models import ProgramVersion
from ac_platform.catalog.services import CatalogService, SqlAlchemyCatalogStore
from ac_platform.identity.application import AsyncIdentityApplication
from ac_platform.identity.models import Person
from ac_platform.media.errors import MediaConflict
from ac_platform.media.models import (
    ActivityMediaBinding,
    MediaAsset,
    MediaUploadIntent,
    MediaVersion,
)
from ac_platform.media.service import MediaService
from ac_platform.media.signing import MediaSigner
from ac_platform.media.storage import InMemoryPrivateObjectStorage
from ac_platform.media.studio_contract import StudioVideoSelectionRequest
from ac_platform.media.studio_selection import StudioVideoSelection
from tests.integration.test_media_delivery_renewal_postgresql import (
    _run_async,
    _transaction_timeouts,
)
from tests.integration.test_studio_draft_authoring_postgresql import seed
from tests.integration.test_studio_library_postgresql import (
    postgres_harness as postgres_harness,  # noqa: F401 - dynamically resolved after preflight
)
from tests.integration.test_studio_library_postgresql import (
    studio_postgres_harness as studio_postgres_harness,
)
from tests.unit.http.test_admin_learning_routes import _settings


async def seed_selection(sessions):
    state = await seed(sessions)
    state.videos = []
    async with sessions() as db, db.begin():
        # The shared concurrency fixture has no email. Real identity flows require
        # a verified address as well as the existing verification timestamp.
        for actor in state.actors:
            person = await db.get(Person, actor.person_id)
            person.email = f"studio-{actor.person_id.hex}@example.test"

        def publish(sync):
            catalog = CatalogService(SqlAlchemyCatalogStore(sync))
            activity = catalog.add_activity(
                state.module_id,
                tenant_id=state.tenant_id,
                kind="VIDEO",
                title="Isolated instructional video",
            )
            version = catalog.get_version(state.version_id, tenant_id=state.tenant_id)
            sync.get(
                ProgramVersion, state.version_id
            ).content_digest = catalog._canonical_content_digest(version)  # noqa: SLF001
            sync.flush()
            catalog.publish_version(state.version_id, tenant_id=state.tenant_id)
            return activity.id

        state.activity_id = await db.run_sync(publish)
        for actor in state.actors:
            asset = MediaAsset(
                id=uuid4(),
                tenant_id=state.tenant_id,
                owner_person_id=actor.person_id,
                purpose="video",
                state="expected",
            )
            db.add(asset)
            await db.flush()
            version = MediaVersion(
                id=uuid4(),
                tenant_id=state.tenant_id,
                asset_id=asset.id,
                version_number=1,
                purpose="video",
                state="ready",
                content_type="video/mp4",
                declared_bytes=1000,
                actual_bytes=1000,
                object_key=f"private-test/{uuid4()}",
                duration_seconds=10,
                width=1920,
                height=1080,
            )
            db.add(version)
            await db.flush()
            asset.current_version_id, asset.state = version.id, "ready"
            await db.flush()
            db.add(
                MediaUploadIntent(
                    tenant_id=state.tenant_id,
                    actor_person_id=actor.person_id,
                    asset_id=asset.id,
                    version_id=version.id,
                    filename="Approved instruction.mp4",
                    object_key=version.object_key,
                    content_type="video/mp4",
                    declared_bytes=1000,
                    max_bytes=1000,
                    state="ready",
                    request_fingerprint="b" * 64,
                    expires_at=datetime.now(UTC) + timedelta(hours=1),
                )
            )
            state.videos.append((asset.id, version.id))
    return state


def request_body(state, index=0, expected=None):
    asset, version = state.videos[index]
    return StudioVideoSelectionRequest(
        asset_id=asset,
        version_id=version,
        expected_binding_id=expected,
        approval_reference="Explicit isolated content review",
    )


def media_service():
    signer = MediaSigner("studio-selection-synthetic-signing-key-32bytes")
    return MediaService(
        storage=InMemoryPrivateObjectStorage(signer),
        signer=signer,
        webhook_secret="studio-selection-synthetic-webhook-32bytes",  # noqa: S106
    )


@pytest.mark.parametrize("same_key", [False, True])
def test_actual_pg_conflicting_writers_and_same_key_retry(studio_postgres_harness, same_key):
    async def scenario():
        engine = create_async_engine(
            studio_postgres_harness.schema_url, pool_size=4, max_overflow=0, hide_parameters=True
        )
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        task = None
        try:
            state, service = await seed_selection(sessions), media_service()
            key, started, pids = uuid4().hex, asyncio.Event(), {}

            async def second():
                async with sessions() as db, db.begin():
                    pids["second"] = await _transaction_timeouts(db)
                    started.set()
                    index = 0 if same_key else 1
                    return await StudioVideoSelection(db, service).select(
                        state.actors[index],
                        program_id=state.program_id,
                        activity_id=state.activity_id,
                        body=request_body(state, index),
                        idempotency_key=key if same_key else uuid4().hex,
                    )

            async with sessions() as db, db.begin():
                pids["first"] = await _transaction_timeouts(db)
                first = await StudioVideoSelection(db, service).select(
                    state.actors[0],
                    program_id=state.program_id,
                    activity_id=state.activity_id,
                    body=request_body(state),
                    idempotency_key=key,
                )
                task = asyncio.create_task(second())
                await asyncio.wait_for(started.wait(), 8)
                async with sessions() as observer, asyncio.timeout(5):
                    while pids["first"] not in await observer.scalar(
                        select(func.pg_blocking_pids(pids["second"]))
                    ):
                        if task.done():
                            pytest.fail("second approval did not wait for the first transaction")
                        await asyncio.sleep(0.01)
            if same_key:
                retry = await asyncio.wait_for(task, 8)
                assert retry.binding_id == first.binding_id and retry.replayed
            else:
                with pytest.raises(MediaConflict):
                    await asyncio.wait_for(task, 8)
            async with sessions() as db, db.begin():
                assert (
                    await db.scalar(
                        select(func.count())
                        .select_from(ActivityMediaBinding)
                        .where(ActivityMediaBinding.tenant_id == state.tenant_id)
                    )
                    == 1
                )
                assert (
                    await db.scalar(
                        select(func.count())
                        .select_from(AuditEvent)
                        .where(
                            AuditEvent.tenant_id == state.tenant_id,
                            AuditEvent.action == "media.activity_binding_approved",
                        )
                    )
                    == 1
                )
                assert (
                    await db.run_sync(lambda sync: verify_audit_chain_sync(sync, state.tenant_id))
                ).valid
        finally:
            if task is not None:
                if not task.done():
                    task.cancel()
                await asyncio.gather(task, return_exceptions=True)
            await engine.dispose()

    _run_async(scenario())


def test_full_app_cookie_context_selection_and_committed_approval(
    studio_postgres_harness, monkeypatch, caplog
):
    caplog.set_level(logging.WARNING, logger="httpx")

    async def scenario():
        engine = create_async_engine(studio_postgres_harness.schema_url, hide_parameters=True)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        try:
            state = await seed_selection(sessions)
            settings = _settings()
            app_module = importlib.import_module("ac_platform.http.app")
            with monkeypatch.context() as patched:
                patched.setattr(app_module, "settings", settings)
                patched.setattr(app_module, "session_factory", sessions)
                app = app_module.create_app()
            assert not app.dependency_overrides
            origin = "http://coach.localhost:3102"
            prefix = f"/v1/admin/studio/programs/{state.program_id}"
            path = f"{prefix}/activities/{state.activity_id}/video"
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
                base_url=origin,
                headers={"Origin": origin},
            ) as client:
                assert (await client.get(path)).status_code == 401
                async with sessions() as db, db.begin():
                    issued = await AsyncIdentityApplication(
                        db, token_pepper=settings.session_token_pepper.get_secret_value()
                    ).issue_authenticated_session(state.actors[0].person_id)
                client.cookies.set(
                    settings.session_cookie_name, issued.token, domain="coach.localhost", path="/"
                )
                context = await client.post("/v1/context", json={"tenant_id": str(state.tenant_id)})
                assert context.status_code == 200
                assert context.json()["membership_role"] == "learner"
                page = await client.get(f"{prefix}/videos")
                assert page.status_code == 200
                assert len(page.json()["items"]) == 1
                key = uuid4().hex
                saved = await client.post(
                    path,
                    json=request_body(state).model_dump(mode="json"),
                    headers={"Idempotency-Key": key},
                )
                assert saved.status_code == 200
                assert saved.json()["replayed"] is False
                async with sessions() as db, db.begin():
                    binding = await db.get(ActivityMediaBinding, UUID(saved.json()["binding_id"]))
                    assert (
                        binding is not None
                        and binding.approved_by_person_id == state.actors[0].person_id
                    )
                retry = await client.post(
                    path,
                    json=request_body(state).model_dump(mode="json"),
                    headers={"Idempotency-Key": key},
                )
                assert retry.status_code == 200 and retry.json()["replayed"] is True
                current = await client.get(path)
                assert current.json()["binding"]["binding_id"] == saved.json()["binding_id"]
                # A program assignment does not expose the generic legacy admin media API on Coach.
                assert (
                    await client.post("/v1/media/activity-bindings", json={})
                ).status_code == 403
        finally:
            await engine.dispose()

    _run_async(scenario())


def test_latest_intent_uses_scoped_index_with_representative_history(studio_postgres_harness):
    async def scenario():
        engine = create_async_engine(studio_postgres_harness.schema_url, hide_parameters=True)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        try:
            state = await seed_selection(sessions)
            asset_id, version_id = state.videos[0]
            now = datetime.now(UTC)
            async with sessions() as db, db.begin():
                # Synthetic rows in the disposable schema only. This models repeated
                # upload intents, not an operational upload or metadata rewrite.
                await db.execute(
                    insert(MediaUploadIntent),
                    [
                        {
                            "id": uuid4(),
                            "tenant_id": state.tenant_id,
                            "actor_person_id": state.actors[0].person_id,
                            "asset_id": asset_id,
                            "version_id": version_id,
                            "filename": f"Historical intent {index}.mp4",
                            "object_key": f"isolated/{uuid4()}",
                            "content_type": "video/mp4",
                            "declared_bytes": 1000,
                            "max_bytes": 1000,
                            "state": "ready",
                            "request_fingerprint": "c" * 64,
                            "created_at": now - timedelta(seconds=index + 1),
                            "expires_at": now + timedelta(hours=1),
                        }
                        for index in range(2500)
                    ],
                )
                await db.execute(text("ANALYZE media_upload_intents"))
                plan = await db.scalar(
                    text(
                        "EXPLAIN (FORMAT JSON) SELECT filename FROM media_upload_intents "
                        "WHERE tenant_id = :tenant AND asset_id = :asset AND version_id = :version "
                        "ORDER BY created_at DESC, id DESC LIMIT 1"
                    ),
                    {"tenant": state.tenant_id, "asset": asset_id, "version": version_id},
                )

                def nodes(node):
                    yield node
                    for child in node.get("Plans", []):
                        yield from nodes(child)

                assert any(
                    node.get("Index Name") == "ix_media_upload_intents_scope_latest"
                    for node in nodes(plan[0]["Plan"])
                )
        finally:
            await engine.dispose()

    _run_async(scenario())
