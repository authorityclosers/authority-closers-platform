"""Failed provider jobs keep a content-free failure detail on disposable PostgreSQL."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from ac_platform.conversation_intelligence import failure_detail as failure_detail_module
from ac_platform.conversation_intelligence.checkpoints import canonical
from ac_platform.conversation_intelligence.failure_detail import (
    FAILURE_DETAIL_MAX_BYTES,
    FAILURE_DETAIL_SCHEMA,
    canonical_failure_detail,
)
from ac_platform.conversation_intelligence.inference_tasks import InferenceTaskError
from ac_platform.conversation_intelligence.inference_worker import ConversationInferenceWorker
from ac_platform.conversation_intelligence.models import ConversationInferenceTask
from ac_platform.conversation_intelligence.providers import ProviderResult
from ac_platform.conversation_intelligence.reporting_pipeline import StageRequest
from ac_platform.conversation_intelligence.reports import REPORT_VALIDATOR_REVISION
from ac_platform.outbox.models import Job
from tests.database.test_conversation_inference_postgresql import _provider_quote
from tests.database.test_conversation_postgresql import run
from tests.database.test_conversation_reporting_guards_postgresql import _queued_c5
from tests.database.test_conversation_reporting_pipeline_postgresql import (
    ReportingBroker,
    completed_checkpoint,
    enqueue,
    text_quote,
)
from tests.database.test_conversation_worker_postgresql import (
    _postgres_harness,
)
from tests.database.test_conversation_worker_postgresql import _prepare as prepare_local

SENTINEL = "sentinel_9f3c_private_words"
SITE = re.compile(r"^[A-Za-z0-9_.]+\.py:\d+:[A-Za-z0-9_<>]+$")
CODE = re.compile(r"^[a-z0-9_]{1,60}$")
CATCH_ALL = "conversation_provider_result_validation_failed"


@pytest.fixture
def postgres_harness() -> Any:
    yield from _postgres_harness.__wrapped__()


class TamperingBroker(ReportingBroker):
    """Return the synthetic Groq response after one content-level edit."""

    def __init__(
        self,
        data: bytes,
        *,
        facts: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
        coaching: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
        elevenlabs_malformed: bool = False,
    ) -> None:
        super().__init__(data, elevenlabs_malformed=elevenlabs_malformed)
        self.facts = facts
        self.coaching = coaching

    async def execute(self, reservation: Any, payload: bytes) -> ProviderResult:
        result = await super().execute(reservation, payload)
        if reservation.quote.provider_id != "groq":
            return result
        user = json.loads(payload)["messages"][1]["content"]
        tamper = self.facts if user.startswith("{") else self.coaching
        if tamper is None:
            return result
        content = json.loads(result.data["choices"][0]["message"]["content"])
        envelope = {"choices": [{"message": {"content": json.dumps(tamper(content))}}]}
        raw = canonical(envelope)
        return ProviderResult(
            provider=result.provider,
            model=result.model,
            request_id=result.request_id,
            response_sha256=hashlib.sha256(raw).hexdigest(),
            raw_json=raw,
            data=envelope,
            usage=result.usage,
            input_sha256=result.input_sha256,
        )


async def _job_for(sessions: Any, view: dict[str, Any]) -> Job:
    async with sessions() as db:
        task = await db.get(ConversationInferenceTask, UUID(view["id"]))
        assert task is not None
        job = await db.get(Job, task.job_id)
        assert isinstance(job, Job)
        return job


def _assert_detail(job: Job, *, stage: str, sentinel: str | None = None) -> dict[str, Any]:
    assert job.status == "dead_letter"
    assert job.last_error is not None
    detail = job.failure_detail
    assert detail is not None
    assert detail["schema"] == FAILURE_DETAIL_SCHEMA
    assert detail["stage"] == stage
    assert detail["failure_code"] == job.last_error
    assert isinstance(detail["code"], str) and CODE.match(detail["code"])
    assert isinstance(detail["site"], str) and SITE.match(detail["site"])
    assert detail["validator_revision"] == (
        REPORT_VALIDATOR_REVISION if stage in {"C4", "C5"} else None
    )
    text = canonical_failure_detail(detail)
    assert len(text) <= FAILURE_DETAIL_MAX_BYTES
    if sentinel is not None:
        assert sentinel not in text
    return detail


async def _through_c2(
    postgres_harness: Any, tmp_path: Path, broker: ReportingBroker
) -> tuple[Any, Any, Any, ConversationInferenceWorker, dict[str, Any]]:
    """Queue and run the C2 stage with ``broker``; return the C2 task view."""

    prepared = await prepare_local(postgres_harness, tmp_path)
    assert await prepared.worker.run_once()
    engine = create_async_engine(postgres_harness.url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    worker = ConversationInferenceWorker(sessions, prepared.storage, broker)
    quote_id, quote = await _provider_quote(
        sessions,
        prepared.state,
        prepared.recording_id,
        prepared.scope_id,
        hashlib.sha256(prepared.data).hexdigest(),
    )
    asr = await enqueue(sessions, prepared, quote_id, quote, None, "detail-asr")
    assert await worker.run_once()
    return prepared, engine, sessions, worker, asr


def test_c5_strict_model_failure_stores_stage_code_site_and_errors_without_content(
    postgres_harness: Any, tmp_path: Path
) -> None:
    def break_summary(content: dict[str, Any]) -> dict[str, Any]:
        return {**content, "summary": [SENTINEL]}

    async def exercise() -> None:
        tampering = TamperingBroker(b"synthetic", coaching=break_summary)
        prepared, engine, sessions, broker, worker, view = await _queued_c5(
            postgres_harness, tmp_path, tampering
        )
        try:
            assert await worker.run_once()
            job = await _job_for(sessions, view)
            detail = _assert_detail(job, stage="C5", sentinel=SENTINEL)
            assert job.last_error == "conversation_report_payload_invalid"
            assert detail["code"] == "report_payload_invalid"
            assert detail["site"].endswith(":parse_report_draft")
            assert {"loc": "summary", "type": "string_type"} in detail["errors"]
        finally:
            await engine.dispose()

    run(exercise())


def test_catch_all_code_keeps_inner_code_and_drops_exception_message(
    postgres_harness: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def exercise() -> None:
        prepared, engine, sessions, broker, worker, view = await _queued_c5(
            postgres_harness, tmp_path
        )
        try:

            async def dispatch(_work: Any) -> None:
                try:
                    raise RuntimeError(f"private detail {SENTINEL}")
                except RuntimeError as cause:
                    raise InferenceTaskError("task_payload_source_context_mismatch") from cause

            monkeypatch.setattr(worker, "_dispatch", dispatch)
            assert await worker.run_once()
            job = await _job_for(sessions, view)
            assert job.last_error == CATCH_ALL
            detail = job.failure_detail
            assert detail is not None
            assert detail["failure_code"] == CATCH_ALL
            assert detail["code"] == "task_payload_source_context_mismatch"
            assert detail["stage"] == "C5"
            assert SENTINEL not in canonical_failure_detail(detail)
            assert "private detail" not in canonical_failure_detail(detail)
        finally:
            await engine.dispose()

    run(exercise())


def test_c2_failure_stores_its_stage_without_a_validator_revision(
    postgres_harness: Any, tmp_path: Path
) -> None:
    async def exercise() -> None:
        broker = TamperingBroker(b"synthetic", elevenlabs_malformed=True)
        prepared, engine, sessions, worker, asr = await _through_c2(
            postgres_harness, tmp_path, broker
        )
        try:
            job = await _job_for(sessions, asr)
            _assert_detail(job, stage="C2")
        finally:
            await engine.dispose()

    run(exercise())


def test_c4_strict_model_failure_stores_its_stage_and_field_path(
    postgres_harness: Any, tmp_path: Path
) -> None:
    def add_unknown_key(content: dict[str, Any]) -> dict[str, Any]:
        return {**content, "unexpected_key": SENTINEL}

    async def exercise() -> None:
        broker = TamperingBroker(b"synthetic", facts=add_unknown_key)
        prepared, engine, sessions, worker, asr = await _through_c2(
            postgres_harness, tmp_path, broker
        )
        try:
            c2 = await completed_checkpoint(sessions, asr)
            facts = StageRequest(stage="C4", transcript_checkpoint_id=c2)
            quote_id, quote = await text_quote(sessions, prepared, facts)
            view = await enqueue(sessions, prepared, quote_id, quote, facts, "detail-facts")
            assert await worker.run_once()
            job = await _job_for(sessions, view)
            detail = _assert_detail(job, stage="C4", sentinel=SENTINEL)
            assert job.last_error == "conversation_fact_packet_invalid"
            assert detail["code"] == "fact_packet_invalid"
            assert detail["errors"] == [{"loc": "unexpected_key", "type": "extra_forbidden"}]
        finally:
            await engine.dispose()

    run(exercise())


def test_builder_failure_still_dead_letters_with_the_minimal_detail(
    postgres_harness: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def exercise() -> None:
        prepared, engine, sessions, broker, worker, view = await _queued_c5(
            postgres_harness, tmp_path
        )
        try:

            def explode(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
                raise RuntimeError("synthetic builder failure")

            monkeypatch.setattr(failure_detail_module, "_describe", explode)

            async def dispatch(_work: Any) -> None:
                raise InferenceTaskError("report_evidence_invalid")

            monkeypatch.setattr(worker, "_dispatch", dispatch)
            assert await worker.run_once()
            job = await _job_for(sessions, view)
            assert job.status == "dead_letter"
            assert job.last_error == "conversation_report_evidence_invalid"
            assert job.failure_detail == {
                "schema": FAILURE_DETAIL_SCHEMA,
                "failure_code": "conversation_report_evidence_invalid",
            }
        finally:
            await engine.dispose()

    run(exercise())
