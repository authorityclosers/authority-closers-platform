"""Fictional PostgreSQL proof for unused shared-source schema and permanent history."""

import asyncio
import hashlib
import threading
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, select, update
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session

from ac_platform.conversation_intelligence.models import (
    ConversationPermission,
    ConversationRecording,
)
from ac_platform.conversation_intelligence.source_object_models import (
    ConversationSourceObject as Object,
)
from ac_platform.conversation_intelligence.source_object_models import (
    ConversationSourceReference as Reference,
)
from ac_platform.conversation_intelligence.storage import (
    ObjectKey,
    ObjectKind,
    PrivateLocalRecordingStorage,
    SourceAudioKey,
    StorageError,
)
from ac_platform.conversation_intelligence.worker import _FencedExecutor
from tests.database.test_conversation_postgresql import (
    application,
    run,
    seed,
)
from tests.database.test_conversation_postgresql import (
    postgres_harness as _postgres_harness,
)
from tests.database.test_conversation_worker_postgresql import OfflineConversationWorker, _reconcile


@pytest.fixture
def postgres_harness() -> Any:
    yield from cast(Any, _postgres_harness).__wrapped__()


def test_source_history_constraints(postgres_harness: Any) -> None:
    async def recording() -> Any:
        engine = create_async_engine(postgres_harness.url)
        try:
            state = await seed(engine)
            other = await seed(engine)
            async with AsyncSession(engine) as database, database.begin():
                result = await application(database, state).register(
                    state.actor, state.recording_intent, key="source-proof"
                )
            return state, other, UUID(result["id"])
        finally:
            await engine.dispose()

    state, other, recording_id = run(recording())
    now = datetime.now(UTC)
    with Session(postgres_harness) as db, db.begin():

        def add_object(tenant: Any) -> Object:
            obj = Object(
                id=uuid4(), tenant_id=tenant, source_sha256=state.source_sha256, created_at=now
            )
            db.add(obj)
            db.flush()
            return obj

        first = add_object(state.tenant_id)
        with pytest.raises(IntegrityError), db.begin_nested():
            add_object(state.tenant_id)
        foreign = add_object(other.tenant_id)
        ref = dict(
            recording_id=recording_id,
            tenant_id=state.tenant_id,
            person_id=state.person_id,
            created_at=now,
        )
        with pytest.raises(IntegrityError), db.begin_nested():
            db.add(Reference(**ref, source_object_id=foreign.id))
            db.flush()
        db.add(Reference(**ref, source_object_id=first.id))
        db.flush()
        with pytest.raises(IntegrityError), db.begin_nested():
            db.add(Reference(**ref, source_object_id=first.id))
            db.flush()
        db.execute(update(Reference).values(released_at=now, release_reason="owner_erasure"))
        for statement in (delete(Reference), update(Reference).values(release_reason="rewrite")):
            with pytest.raises(IntegrityError), db.begin_nested():
                db.execute(statement)
        assert db.scalar(select(Reference.release_reason)) == "owner_erasure"
        first.deleted_at = now
        db.flush()
        assert add_object(state.tenant_id).id != first.id
        assert db.get(Object, first.id).deleted_at == now


def test_last_release_fences_upload_and_recovers_unlink_rollback(
    postgres_harness: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def exercise() -> None:
        engine = create_async_engine(postgres_harness.url)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        storage = PrivateLocalRecordingStorage(tmp_path / "objects")
        worker = OfflineConversationWorker(
            sessions,
            storage=storage,
            scratch=PrivateLocalRecordingStorage(tmp_path / "scratch"),
            environment="test",
        )
        data = b"fictional source audio"
        digest = hashlib.sha256(data).hexdigest()
        started, release = threading.Event(), threading.Event()
        upload_task = erase_task = None

        async def prepare(tenant: UUID | None = None) -> tuple[Any, UUID]:
            state = replace(await seed(engine, tenant_id=tenant), source_sha256=digest)
            async with sessions() as db, db.begin():
                permission = await db.get(ConversationPermission, state.permission_id)
                permission.source_sha256 = digest
                result = await application(db, state).register(
                    state.actor,
                    state.recording_intent.model_copy(update={"source_bytes": len(data)}),
                    key="register-shared-proof",
                )
            return state, UUID(result["id"])

        async def upload(state: Any, recording_id: UUID) -> None:
            async with _FencedExecutor(storage.root), sessions() as db, db.begin():
                await application(db, state).store_source(
                    state.actor,
                    recording_id,
                    chunks=[data],
                    storage=storage,
                )

        async def delete_recording(state: Any, recording_id: UUID) -> Any:
            async with sessions() as db, db.begin():
                await application(db, state).request_deletion(
                    state.actor,
                    recording_id,
                    key=f"delete-{recording_id}",
                )
            work = await worker.claim()
            assert work is not None
            return work

        try:
            owner, recording_id = await prepare()
            foreign, foreign_id = await prepare()
            later, later_id = await prepare(owner.tenant_id)
            await _reconcile(sessions, owner)
            await upload(owner, recording_id)
            await upload(foreign, foreign_id)
            async with sessions() as db:
                first_id = (await db.get(Reference, recording_id)).source_object_id
                assert (await db.get(Reference, foreign_id)).source_object_id != first_id
            key = SourceAudioKey(owner.tenant_id, digest)
            original_delete = storage.delete
            fail_once = True

            def held_delete(item: Any) -> bool:
                nonlocal fail_once
                result = original_delete(item)
                if item == key:
                    if fail_once:
                        fail_once = False
                        raise StorageError("synthetic_crash_after_unlink")
                    started.set()
                    assert release.wait(10), "storage-fence fixture timed out"
                return result

            monkeypatch.setattr(storage, "delete", held_delete)
            work = await delete_recording(owner, recording_id)
            with pytest.raises(StorageError, match="synthetic_crash_after_unlink"):
                await worker._erase_job(work)
            async with sessions() as db:
                assert (await db.get(Reference, recording_id)).released_at is None
                assert (await db.get(Object, first_id)).deleted_at is None
            erase_task = asyncio.create_task(worker._erase_job(work))
            assert await asyncio.to_thread(started.wait, 5)
            async with sessions() as db, db.begin():
                with pytest.raises(DBAPIError):
                    await db.get(Object, first_id, with_for_update={"nowait": True})
            upload_task = asyncio.create_task(upload(later, later_id))
            await asyncio.sleep(0.05)
            assert not upload_task.done()
            async with sessions() as db:
                assert await db.get(Reference, later_id) is None
            release.set()
            await asyncio.gather(erase_task, upload_task)
            async with sessions() as db:
                assert (await db.get(Object, first_id)).deleted_at
                assert (await db.get(Reference, recording_id)).released_at
                assert (await db.get(Reference, later_id)).source_object_id != first_id
            for tenant in (owner.tenant_id, foreign.tenant_id):
                assert (
                    b"".join(
                        storage.iter_bytes(SourceAudioKey(tenant, digest), expected_sha256=digest)
                    )
                    == data
                )
            legacy, legacy_id = await prepare(owner.tenant_id)
            legacy_key = ObjectKey(owner.tenant_id, legacy_id, legacy_id, ObjectKind.SOURCE_AUDIO)
            storage.put(legacy_key, [data], expected_sha256=digest)
            async with sessions() as db, db.begin():
                (await db.get(ConversationRecording, legacy_id)).state = "ready"
            await worker._erase_job(await delete_recording(legacy, legacy_id))
            assert storage.list_recording(owner.tenant_id, legacy_id) == ()
            assert b"".join(storage.iter_bytes(key, expected_sha256=digest)) == data
        finally:
            release.set()
            await asyncio.gather(
                *(t for t in (erase_task, upload_task) if t), return_exceptions=True
            )
            await engine.dispose()

    run(exercise())
