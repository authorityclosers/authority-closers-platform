"""Twenty-five seconds follows real local C0/C1 decoding and publication."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal
from uuid import UUID

import pytest
from sqlalchemy import select

from ac_platform.audit.models import AuditEvent
from ac_platform.conversation_intelligence.application import (
    AUDIOATLAS_HOSTED_RECIPE,
    AUDIOATLAS_RECIPE,
)
from ac_platform.conversation_intelligence.models import ConversationCheckpoint, ConversationRun
from ac_platform.conversation_intelligence.native_runtime import NativeRuntimeError
from ac_platform.conversation_intelligence.signals import inspect_media
from ac_platform.conversation_intelligence.worker import HostedConversationWorker
from tests.database.test_conversation_postgresql import run
from tests.database.test_conversation_worker_postgresql import _postgres_harness, _prepare


@pytest.fixture
def postgres_harness() -> Any:
    yield from _postgres_harness.__wrapped__()


@pytest.mark.parametrize("rate", [48000, 16000], ids=["offline-48k", "hosted-16k"])
def test_twenty_five_second_call_publishes_c1(
    postgres_harness: Any, tmp_path: Any, rate: int
) -> None:
    async def exercise() -> None:
        prepared = await _prepare(
            postgres_harness,
            tmp_path,
            duration_ms=25_000,
            recipe_revision=AUDIOATLAS_HOSTED_RECIPE if rate == 16000 else AUDIOATLAS_RECIPE,
        )
        try:
            worker = prepared.worker
            if rate == 16000:

                class LocalNativeDouble:
                    def inspect(
                        self, source: Path, outdir: Path, *, job_id: UUID, rate: Literal[16000]
                    ) -> dict[str, Any]:
                        assert rate == 16000
                        # Real native extraction, local helper-transport double;
                        # this is not a hosted confinement/deployment receipt.
                        return inspect_media(source, outdir, rate=rate)

                worker = HostedConversationWorker(
                    prepared.worker.sessions,
                    storage=prepared.storage,
                    scratch=prepared.scratch,
                    environment="development",
                    native_runtime=LocalNativeDouble(),
                )
            assert await worker.run_once()
            async with worker.sessions() as db:
                execution = await db.get(ConversationRun, prepared.run_id)
                assert execution is not None and execution.state == "completed"
                checkpoint = await db.scalar(
                    select(ConversationCheckpoint).where(
                        ConversationCheckpoint.recording_id == prepared.recording_id,
                        ConversationCheckpoint.stage == "C1",
                    )
                )
                assert checkpoint is not None and checkpoint.payload is not None
                assert checkpoint.payload["media_duration_ms"] == 25_000
                assert checkpoint.payload["source_sha256"] == prepared.state.source_sha256
                assert checkpoint.payload["native_receipt"]["rows"] == 2500
                assert checkpoint.payload["timebase"]["rate"] == rate
        finally:
            await prepared.worker.sessions.kw["bind"].dispose()

    run(exercise())


def test_native_failure_retains_category_without_raw_text(
    postgres_harness: Any, tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def exercise() -> None:
        prepared = await _prepare(postgres_harness, tmp_path)
        try:

            def failed_inspection(*args: Any, **kwargs: Any) -> Any:
                raise NativeRuntimeError("native_runtime_feature_invalid")

            monkeypatch.setattr(prepared.worker, "_inspect", failed_inspection)
            with pytest.raises(RuntimeError, match="see its durable state"):
                await prepared.worker.run_once()
            async with prepared.worker.sessions() as db:
                execution = await db.get(ConversationRun, prepared.run_id)
                event = await db.scalar(
                    select(AuditEvent).where(
                        AuditEvent.action == "conversation.local_failure_observed",
                        AuditEvent.resource_id == str(execution.job_id),
                    )
                )
                assert event is not None
                assert event.payload["failure_code"] == "native_runtime_feature_invalid"
                assert event.payload["phase"] == "local_inspection"
        finally:
            await prepared.worker.sessions.kw["bind"].dispose()

    run(exercise())
