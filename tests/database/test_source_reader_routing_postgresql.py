"""Fictional source readers follow real references without falling back after release."""

from types import SimpleNamespace
from uuid import UUID

import httpx
import pytest
from fastapi import APIRouter, FastAPI
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from ac_platform.conversation_intelligence.application import (
    AUDIOATLAS_HOSTED_RECIPE,
    AUDIOATLAS_RECIPE,
    ConversationApplication,
    ConversationConflict,
)
from ac_platform.conversation_intelligence.contracts import QuoteAcceptance
from ac_platform.conversation_intelligence.inference import ConversationInference
from ac_platform.conversation_intelligence.inference_worker import ConversationInferenceWorker
from ac_platform.conversation_intelligence.models import ConversationRecording, ConversationRun
from ac_platform.conversation_intelligence.signals import inspect_media
from ac_platform.conversation_intelligence.source_object_models import (
    ConversationSourceReference as Reference,
)
from ac_platform.conversation_intelligence.storage import (
    ObjectKey,
    ObjectKind,
    SourceAudioKey,
    StorageError,
)
from ac_platform.conversation_intelligence.worker import HostedConversationWorker
from ac_platform.http.conversation_playback import install_playback_route
from ac_platform.outbox.models import Job
from tests.database.test_conversation_inference_postgresql import FakeBroker, _provider_quote
from tests.database.test_conversation_postgresql import application, run
from tests.database.test_conversation_reports_postgresql import (
    ReportFixture,
    _import_valid,
    _intent,
    _promote_worker_actor,
)
from tests.database.test_conversation_worker_postgresql import _postgres_harness, _prepare


@pytest.fixture
def postgres_harness():
    yield from _postgres_harness.__wrapped__()


@pytest.mark.parametrize("reader", ["upload", "native", "hosted", "inference", "report", "http"])
@pytest.mark.parametrize("history", ["none", "live", "released"])
def test_source_reader_reference_routing(postgres_harness, tmp_path, monkeypatch, reader, history):
    async def exercise():
        recipe = AUDIOATLAS_HOSTED_RECIPE if reader == "hosted" else AUDIOATLAS_RECIPE
        store_source = ConversationApplication.store_source

        async def legacy_upload(self, actor, recording_id, **kwargs):
            # Model a pre-switch ready recording, without deleting reference history.
            recording = await self.database.get(ConversationRecording, recording_id)
            recording.state = "ready"
            return await store_source(self, actor, recording_id, **kwargs)

        with monkeypatch.context() as setup:
            if history == "none":
                setup.setattr(ConversationApplication, "store_source", legacy_upload)
            prepared = await _prepare(postgres_harness, tmp_path, recipe_revision=recipe)
        engine = create_async_engine(postgres_harness.url)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        state, storage = prepared.state, prepared.storage
        legacy = ObjectKey(
            state.tenant_id, prepared.recording_id, prepared.recording_id, ObjectKind.SOURCE_AUDIO
        )
        shared = SourceAudioKey(state.tenant_id, state.source_sha256)
        worker = prepared.worker
        try:
            if reader in {"report", "inference"}:
                assert await worker.run_once()
            if history != "none":
                async with sessions() as db, db.begin():
                    reference = await db.get(Reference, prepared.recording_id)
                    assert reference is not None
                    if history == "released":
                        storage.put(legacy, [prepared.data], expected_sha256=state.source_sha256)
                        reference.released_at = state.now
                        reference.release_reason = "owner_erasure"
            reads = []
            original = storage.iter_bytes

            def read(key, **kwargs):
                reads.append(key)
                return original(key, **kwargs)

            monkeypatch.setattr(storage, "iter_bytes", read)
            if reader == "upload":
                async with sessions() as db, db.begin():
                    call = application(db, state).store_source(
                        state.actor, prepared.recording_id, chunks=[prepared.data], storage=storage
                    )
                    if history == "released":
                        with pytest.raises(StorageError, match="^storage_object_missing$"):
                            await call
                    else:
                        assert (await call)["state"] == "ready"
            elif reader == "report":
                actor = await _promote_worker_actor(engine, prepared)
                fixture = ReportFixture(prepared, actor, _intent(state.source_sha256))
                if history == "released":
                    with pytest.raises(
                        ConversationConflict, match="^The retained recording is unavailable\\.$"
                    ):
                        await _import_valid(fixture, sessions)
                else:
                    assert (await _import_valid(fixture, sessions))["state"] == "completed"
            elif reader == "http":

                async def require_actor():
                    async with sessions() as db, db.begin():
                        yield SimpleNamespace(
                            database=db, resolved=SimpleNamespace(actor=state.actor)
                        )

                app, router = FastAPI(), APIRouter()
                install_playback_route(router, require_actor, storage)
                app.include_router(router)
                async with httpx.AsyncClient(
                    transport=httpx.ASGITransport(app=app), base_url="https://fictional.test"
                ) as client:
                    for headers in ({}, {"Range": "bytes=2-5"}):
                        response = await client.get(
                            f"/recordings/{prepared.recording_id}/source", headers=headers
                        )
                        if history == "released":
                            assert response.status_code == 409
                            assert response.json() == {
                                "detail": "The retained recording is unavailable."
                            }
                        else:
                            assert response.status_code == (206 if headers else 200)
                            assert response.content == (
                                prepared.data[2:6] if headers else prepared.data
                            )
            else:
                run_id = prepared.run_id
                if reader == "inference":
                    quote_id, quote = await _provider_quote(
                        sessions,
                        state,
                        prepared.recording_id,
                        prepared.scope_id,
                        state.source_sha256,
                    )
                    async with sessions() as db, db.begin():
                        service = ConversationInference(ConversationApplication(db))
                        await service.accept(
                            state.actor,
                            prepared.recording_id,
                            quote_id,
                            QuoteAcceptance(
                                quote_fingerprint=quote.fingerprint,
                                privacy_revision=quote.privacy_revision,
                                accepted=True,
                            ),
                        )
                        requested = await service.request_transcription(
                            state.actor, prepared.recording_id, quote_id, key="shared-reader"
                        )
                        run_id = UUID(requested["id"])
                    broker = FakeBroker(prepared.data)
                    worker = ConversationInferenceWorker(sessions, storage, broker)
                elif reader == "hosted":
                    worker = HostedConversationWorker(
                        sessions,
                        storage=storage,
                        scratch=prepared.scratch,
                        environment="staging",
                        native_runtime=SimpleNamespace(
                            inspect=lambda source, output, **kw: inspect_media(
                                source, output, rate=kw["rate"]
                            )
                        ),
                    )
                if history == "released" and reader != "inference":
                    with pytest.raises(RuntimeError, match="The local conversation job failed"):
                        await worker.run_once()
                else:
                    assert await worker.run_once()
                async with sessions() as db:
                    result = await db.get(ConversationRun, run_id)
                    job = await db.get(Job, result.job_id)
                    if history == "released":
                        code = (
                            "conversation_provider_storage_failed"
                            if reader == "inference"
                            else "conversation_local_phase_failed"
                        )
                        assert job.last_error == code
                        assert job.dispatch_started_at is None
                    else:
                        assert result.state == "completed" and job.status == "succeeded"
                if reader == "inference":
                    assert broker.payloads == ([] if history == "released" else [prepared.data])
            expected_reads = (
                [] if history == "released" else [shared if history == "live" else legacy]
            )
            if reader == "upload" and history == "live":
                expected_reads = []  # Shared publication never re-reads stored bytes.
            if reader == "http":
                expected_reads *= 2
            if reader in {"native", "hosted"} and history != "released":
                expected_reads.append(
                    ObjectKey(
                        state.tenant_id,
                        prepared.recording_id,
                        prepared.run_id,
                        ObjectKind.SIGNAL_FEATURES,
                    )
                )
            assert reads == expected_reads
        finally:
            await engine.dispose()

    run(exercise())
