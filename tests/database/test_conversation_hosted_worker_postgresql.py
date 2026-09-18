"""Durable 48k/16k cache separation; native adapter here is a local test double.

This is not a Docker/confinement receipt. The real database path and unchanged
native extractor are exercised against synthetic audio only.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Literal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from ac_platform.conversation_intelligence.application import (
    AUDIOATLAS_HOSTED_RECIPE,
    AUDIOATLAS_RECIPE,
)
from ac_platform.conversation_intelligence.contracts import RunIntent
from ac_platform.conversation_intelligence.inference import ConversationInference
from ac_platform.conversation_intelligence.models import (
    ConversationCheckpoint,
    ConversationRecording,
)
from ac_platform.conversation_intelligence.signals import inspect_media
from ac_platform.conversation_intelligence.worker import HostedConversationWorker
from tests.database.test_conversation_postgresql import application as build_application
from tests.database.test_conversation_postgresql import run
from tests.database.test_conversation_worker_postgresql import (
    _add_quote,
    _assert_scratch_empty,
    _db_run,
    _prepare,
)
from tests.database.test_conversation_worker_postgresql import (
    postgres_harness as _postgres_harness,
)


@pytest.fixture
def postgres_harness() -> Any:
    yield from _postgres_harness.__wrapped__()


def test_hosted_c1_uses_16k_and_reuses_it_without_reusing_local_48k(
    postgres_harness: Any, tmp_path: Path
) -> None:
    async def exercise() -> None:
        prepared = await _prepare(postgres_harness, tmp_path)
        engine = create_async_engine(postgres_harness.url)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        calls: list[tuple[UUID, int]] = []

        class LocalNativeDouble:
            def inspect(
                self, source: Path, outdir: Path, *, job_id: UUID, rate: Literal[16000]
            ) -> dict[str, Any]:
                assert rate == 16000
                calls.append((job_id, rate))
                return inspect_media(source, outdir, rate=rate)

        try:
            assert await prepared.worker.run_once()
            async with sessions() as database:
                recording = await database.get(ConversationRecording, prepared.recording_id)
                assert recording is not None
                local_plan = await ConversationInference(
                    build_application(database, prepared.state)
                ).plan_transcription(recording)
            hosted = HostedConversationWorker(
                sessions,
                storage=prepared.storage,
                scratch=prepared.scratch,
                environment="staging",
                native_runtime=LocalNativeDouble(),
            )
            for _ in range(2):
                quote = await _add_quote(
                    sessions,
                    prepared.state,
                    prepared.recording_id,
                    prepared.scope_id,
                    hashlib.sha256(prepared.data).hexdigest(),
                    recipe_revision=AUDIOATLAS_HOSTED_RECIPE,
                )
                async with sessions() as database, database.begin():
                    requested = await build_application(database, prepared.state).request_run(
                        prepared.state.actor,
                        RunIntent(
                            recording_id=prepared.recording_id,
                            source_revision="1",
                            quote_id=quote,
                            recipe_revision=AUDIOATLAS_HOSTED_RECIPE,
                        ),
                        key=f"hosted-profile-run-{uuid4().hex}",
                    )
                assert await hosted.run_once()
                completed = await _db_run(sessions, UUID(requested["id"]))
                assert completed.state == "completed"
            assert len(calls) == 1
            async with sessions() as database:
                checkpoints = (
                    await database.scalars(
                        select(ConversationCheckpoint).where(
                            ConversationCheckpoint.recording_id == prepared.recording_id,
                            ConversationCheckpoint.stage == "C1",
                        )
                    )
                ).all()
                assert len(checkpoints) == 2
                assert {c.payload["timebase"]["rate"] for c in checkpoints} == {16000, 48000}
                recording = await database.get(ConversationRecording, prepared.recording_id)
                assert recording is not None
                hosted_plan = await ConversationInference(
                    build_application(database, prepared.state)
                ).plan_transcription(recording)
                hosted_signal = next(
                    c for c in checkpoints if c.payload["timebase"]["rate"] == 16000
                )
                assert hosted_plan.signal_id == hosted_signal.id
                assert hosted_plan.checkpoint.cache_key == local_plan.checkpoint.cache_key
                original_run_plan = await ConversationInference(
                    build_application(database, prepared.state)
                ).plan_transcription(recording, signal_recipe=AUDIOATLAS_RECIPE)
                assert original_run_plan.signal_id == local_plan.signal_id
                assert original_run_plan.signal_id != hosted_plan.signal_id
            _assert_scratch_empty(prepared.scratch)
        finally:
            await engine.dispose()

    run(exercise())


def test_hosted_worker_rejects_48k_quote_before_native_execution(
    postgres_harness: Any, tmp_path: Path
) -> None:
    async def exercise() -> None:
        prepared = await _prepare(postgres_harness, tmp_path)
        engine = create_async_engine(postgres_harness.url)
        sessions = async_sessionmaker(engine, expire_on_commit=False)

        class MustNotRun:
            def inspect(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
                pytest.fail("Hosted worker reinterpreted a 48k quote as 16k")

        try:
            hosted = HostedConversationWorker(
                sessions,
                storage=prepared.storage,
                scratch=prepared.scratch,
                environment="staging",
                native_runtime=MustNotRun(),
            )
            with pytest.raises(RuntimeError, match="conversation job failed"):
                await hosted.run_once()
            async with sessions() as database:
                assert not list(
                    await database.scalars(
                        select(ConversationCheckpoint).where(
                            ConversationCheckpoint.recording_id == prepared.recording_id,
                        )
                    )
                )
            _assert_scratch_empty(prepared.scratch)
        finally:
            await engine.dispose()

    run(exercise())
