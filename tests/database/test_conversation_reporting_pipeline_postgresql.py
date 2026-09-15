"""Synthetic provider-to-report proof on disposable loopback PostgreSQL."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from ac_platform.conversation_intelligence.application import (
    ConversationApplication,
    ConversationConflict,
    ConversationDenied,
)
from ac_platform.conversation_intelligence.checkpoints import canonical
from ac_platform.conversation_intelligence.contracts import QuoteAcceptance
from ac_platform.conversation_intelligence.entitlements import ExecutionPermission, Quote
from ac_platform.conversation_intelligence.inference import ConversationInference
from ac_platform.conversation_intelligence.inference_tasks import prepare_fact_inputs
from ac_platform.conversation_intelligence.inference_worker import ConversationInferenceWorker
from ac_platform.conversation_intelligence.models import (
    ConversationCheckpoint,
    ConversationInferenceTask,
    ConversationQuote,
    ConversationReportDraft,
)
from ac_platform.conversation_intelligence.providers import ProviderResult
from ac_platform.conversation_intelligence.report_store import ConversationReports
from ac_platform.conversation_intelligence.reporting_pipeline import ReportingPipeline, StageRequest
from ac_platform.conversation_intelligence.reports import load_report_profile
from ac_platform.outbox.models import Job
from tests.conversation_overview_fixtures import overview_for
from tests.database.test_conversation_inference_postgresql import (
    FakeBroker,
    _provider_quote,
)
from tests.database.test_conversation_postgresql import run
from tests.database.test_conversation_worker_postgresql import _postgres_harness
from tests.database.test_conversation_worker_postgresql import _prepare as prepare_local


@pytest.fixture
def postgres_harness() -> Any:
    yield from _postgres_harness.__wrapped__()


class ReportingBroker(FakeBroker):
    def __init__(self, data: bytes) -> None:
        super().__init__(data)
        self.routes: list[str] = []

    async def execute(self, reservation: Any, payload: bytes) -> ProviderResult:
        self.routes.append(reservation.quote.provider_id)
        if reservation.quote.provider_id == "elevenlabs":
            return await super().execute(reservation, payload)
        self.calls += 1
        self.payloads.append(payload)
        body = json.loads(payload)
        provider = reservation.quote.provider_id
        user = (
            body["contents"][0]["parts"][0]["text"]
            if provider == "gemini"
            else body["messages"][1]["content"]
        )
        if user.startswith("{"):
            packet = json.loads(user)
            segment = packet["segments"][0]
            data = {
                "overview": "A literal greeting is present.",
                "observations": [
                    {
                        "fact": "The speaker greeted the buyer.",
                        "segment_id": segment["id"],
                        "quote": segment["text"],
                    }
                ],
                "uncertainties": ["The speaker labels have not been verified."],
            }
        else:
            facts = json.loads(user.split("\n", 1)[1])
            # C5 receives lossless source rows plus compact C4 quote ranges.
            # A provider must emit literal output spans, not echo those input
            # references into the report's different evidence contract.
            context = facts["source_context"]
            by_id = {
                row[0]: dict(zip(context["columns"], row, strict=True)) for row in context["rows"]
            }
            evidence = []
            for reference in facts["observations"][0]["evidence"]:
                segment = by_id[reference["segment_id"]]
                evidence.append(
                    {
                        "segment_id": segment["id"],
                        "quote": segment["text"][reference["quote_start"] : reference["quote_end"]],
                        "start_ms": segment["start_ms"],
                        "end_ms": segment["end_ms"],
                    }
                )
            finding = {
                "title": "A greeting is present",
                "explanation": "This is a literal quote.",
                "evidence": evidence,
            }
            data = {
                "summary": "A synthetic draft from saved facts.",
                "strengths": [finding],
                "missed_opportunities": [],
                "improvements": [],
                "objection_analysis": [],
                "closing_analysis": [],
                "verdict": "Further context requires human review.",
                "review_status": "draft_not_dipak_adjudicated",
            }
            data["overview"] = overview_for(data)
        envelope = {"choices": [{"message": {"content": json.dumps(data)}}]}
        if provider == "gemini":
            envelope = {
                "candidates": [
                    {
                        "finishReason": "STOP",
                        "content": {"role": "model", "parts": [{"text": json.dumps(data)}]},
                    }
                ]
            }
        raw = canonical(envelope)
        return ProviderResult(
            provider=provider,
            model=reservation.quote.provider_model,
            request_id=f"synthetic-text-{self.calls}",
            response_sha256=hashlib.sha256(raw).hexdigest(),
            raw_json=raw,
            data=envelope,
            usage={"total_tokens": 20},
            input_sha256=reservation.quote.input_sha256,
        )


class ChunkedReportingBroker(ReportingBroker):
    async def execute(self, reservation: Any, payload: bytes) -> ProviderResult:
        if reservation.quote.provider_id != "elevenlabs":
            return await super().execute(reservation, payload)
        self.routes.append("elevenlabs")
        self.calls += 1
        self.payloads.append(payload)
        words = [
            {
                "text": f"hello buyer {index} " + "synthetic wording " * 10,
                "start": index * 0.3,
                "end": index * 0.3 + 0.25,
                "speaker_id": f"speaker_{index}",
            }
            for index in range(3)
        ]
        native = {"text": " ".join(word["text"] for word in words), "words": words}
        raw = canonical(native)
        return ProviderResult(
            provider="elevenlabs",
            model="scribe_v2",
            request_id="synthetic-multi-segment",
            response_sha256=hashlib.sha256(raw).hexdigest(),
            raw_json=raw,
            data=native,
            input_sha256=reservation.quote.input_sha256,
        )


async def text_quote(sessions: Any, prepared: Any, request: StageRequest) -> tuple[UUID, Quote]:
    async with sessions() as db, db.begin():
        app = ConversationApplication(db)
        await app.get(prepared.state.actor, prepared.recording_id)
        recording = await app._recording(prepared.state.actor, prepared.recording_id)
        plan = await ReportingPipeline(ConversationInference(app)).plan(recording, request)
    identifier, old = await _provider_quote(
        sessions,
        prepared.state,
        prepared.recording_id,
        prepared.scope_id,
        hashlib.sha256(prepared.data).hexdigest(),
    )
    # Fixture-owned canonical quote issuance, not a runtime pricing authority.
    quote = replace(
        old,
        provider_id=plan.prepared.provider,
        provider_model=plan.prepared.model,
        recipe_revision=plan.recipe_revision,
        operation=plan.prepared.operation,
        input_sha256=plan.prepared.input_sha256,
        entitlement_seconds=0,
    )
    # Quotes themselves are immutable; create the correct one instead of rewriting.
    identifier = uuid4()
    quote = replace(quote, quote_id=str(identifier))
    permission = ExecutionPermission(
        "synthetic-text-approval",
        quote.fingerprint,
        str(prepared.state.person_id),
        quote.expires_at_epoch,
    )
    async with sessions() as db, db.begin():
        db.add(
            ConversationQuote(
                id=identifier,
                tenant_id=prepared.state.tenant_id,
                person_id=prepared.state.person_id,
                recording_id=prepared.recording_id,
                budget_scope_id=prepared.scope_id,
                quote=quote.as_dict(),
                execution_permission=permission.as_dict(),
            )
        )
    return identifier, quote


async def enqueue(
    sessions: Any,
    prepared: Any,
    quote_id: UUID,
    quote: Quote,
    request: StageRequest | None,
    key: str,
) -> dict[str, Any]:
    async with sessions() as db, db.begin():
        service = ConversationInference(ConversationApplication(db))
        await service.accept(
            prepared.state.actor,
            prepared.recording_id,
            quote_id,
            QuoteAcceptance(
                quote_fingerprint=quote.fingerprint,
                privacy_revision=quote.privacy_revision,
                accepted=True,
            ),
            request=request,
        )
        return await service.request_stage(
            prepared.state.actor, prepared.recording_id, quote_id, key=key, request=request
        )


async def completed_checkpoint(sessions: Any, view: dict[str, Any]) -> UUID:
    async with sessions() as db:
        task = await db.get(ConversationInferenceTask, UUID(view["id"]))
        assert task is not None and task.state == "completed", None if task is None else task.state
        assert task.checkpoint_id is not None
        return task.checkpoint_id


@pytest.mark.parametrize("multiple_chunks", [False, True])
@pytest.mark.parametrize("provider", ["groq", "gemini"])
def test_saved_transcript_to_private_report_and_profile_reuse(
    postgres_harness: Any,
    tmp_path: Path,
    multiple_chunks: bool,
    provider: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def exercise() -> None:
        prepared = await prepare_local(postgres_harness, tmp_path)
        assert await prepared.worker.run_once()
        engine = create_async_engine(postgres_harness.url)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        broker = (ChunkedReportingBroker if multiple_chunks else ReportingBroker)(prepared.data)
        worker = ConversationInferenceWorker(sessions, prepared.storage, broker)
        try:
            qid, quote = await _provider_quote(
                sessions,
                prepared.state,
                prepared.recording_id,
                prepared.scope_id,
                hashlib.sha256(prepared.data).hexdigest(),
            )
            asr = await enqueue(sessions, prepared, qid, quote, None, "report-asr")
            assert await worker.run_once()
            c2 = await completed_checkpoint(sessions, asr)
            async with sessions() as db, db.begin():
                early = await ConversationReports(ConversationApplication(db)).transcript(
                    prepared.state.actor, prepared.recording_id
                )
                assert early["segments"][0]["text"].startswith("hello buyer")
            model = "gemini-3.8-flash" if provider == "gemini" else "openai/gpt-oss-120b"
            facts = StageRequest(
                stage="C4",
                transcript_checkpoint_id=c2,
                max_input_chars=512,
                provider=provider,
                model=model,
            )
            chunk_count = len(
                prepare_fact_inputs(early, provider=provider, model=model, max_input_chars=512)
            )
            assert chunk_count == (3 if multiple_chunks else 1)
            qid, quote = await text_quote(sessions, prepared, facts)
            # A quote cannot authorize different model bytes.
            with pytest.raises(ConversationDenied):
                await enqueue(
                    sessions,
                    prepared,
                    qid,
                    quote,
                    facts.model_copy(
                        update={
                            "model": (
                                "gemini-3.1-pro-preview"
                                if provider == "gemini"
                                else "llama-3.3-70b-versatile"
                            )
                        }
                    ),
                    "wrong-model",
                )
            fact_ids = []
            for index in range(1, chunk_count + 1):
                chunk = facts.model_copy(update={"chunk_index": index})
                chunk_quote_id, chunk_quote = await text_quote(sessions, prepared, chunk)
                fview = await enqueue(
                    sessions, prepared, chunk_quote_id, chunk_quote, chunk, f"report-facts-{index}"
                )
                assert await worker.run_once()
                fact_ids.append(await completed_checkpoint(sessions, fview))
            coaching = StageRequest(
                stage="C5",
                transcript_checkpoint_id=c2,
                fact_checkpoint_ids=tuple(reversed(fact_ids)),
                provider=provider,
                model=model,
                max_completion_tokens=1800,
            )
            qid, quote = await text_quote(sessions, prepared, coaching)
            cview = await enqueue(sessions, prepared, qid, quote, coaching, "report-coaching")
            assert await worker.run_once()
            await completed_checkpoint(sessions, cview)
            async with sessions() as db, db.begin():
                reports = ConversationReports(ConversationApplication(db))
                response = await reports.get(prepared.state.actor, UUID(cview["id"]))
                assert response["report"]["review_status"] == "draft_not_dipak_adjudicated"
                assert response["report"]["summary"] == "A synthetic draft from saved facts."
                transcript = await reports.transcript(prepared.state.actor, prepared.recording_id)
                assert transcript["source_sha256"] == hashlib.sha256(prepared.data).hexdigest()
                stages = (await db.scalars(select(ConversationCheckpoint.stage))).all()
                assert set(stages) == {"C0", "C1", "C2", "C3", "C4", "C5", "C6"}
                stable = (
                    await db.execute(
                        select(
                            ConversationCheckpoint.id, ConversationCheckpoint.manifest_sha256
                        ).where(ConversationCheckpoint.stage.in_(("C0", "C1", "C2", "C3", "C4")))
                    )
                ).all()
            # Reading an immutable draft uses its frozen profile, even if the
            # default profile is later unavailable. A broken receipt is never
            # advertised as an available report in history.
            async with sessions() as db, db.begin():
                reports = ConversationReports(ConversationApplication(db))
                with monkeypatch.context() as patch:

                    def unavailable_profile() -> Any:
                        raise ValueError("synthetic missing current profile")

                    patch.setattr(
                        "ac_platform.conversation_intelligence.report_store.load_report_profile",
                        unavailable_profile,
                    )
                    assert (await reports.get(prepared.state.actor, UUID(cview["id"])))["report"]
                task = await db.get(ConversationInferenceTask, UUID(cview["id"]))
                assert task is not None
                job = await db.get(Job, task.job_id)
                assert job is not None and job.provider_receipt is not None
                original = job.provider_receipt
                with db.no_autoflush:
                    # An in-memory corrupt loaded value models an invalid stored
                    # receipt without changing or bypassing the immutable DB row.
                    job.provider_receipt = {**original, "raw_blob_id": str(uuid4())}
                    with pytest.raises(ConversationConflict, match="canonical provider receipt"):
                        await reports.get(prepared.state.actor, UUID(cview["id"]))
                    history = await reports.history(prepared.state.actor)
                    assert history["recordings"][0]["has_report"] is False
                    job.provider_receipt = original
            replay = await enqueue(
                sessions, prepared, qid, quote, coaching, "report-coaching-again"
            )
            assert replay["id"] == cview["id"]
            assert not await worker.run_once()
            profile = load_report_profile()
            profile["revision"] = "synthetic-next-profile"
            next_provider = "groq" if provider == "gemini" else "gemini"
            next_model = "openai/gpt-oss-120b" if next_provider == "groq" else "gemini-3.8-flash"
            changed = coaching.model_copy(
                update={
                    "profile": profile,
                    "provider": next_provider,
                    "model": next_model,
                }
            )
            qid, quote = await text_quote(sessions, prepared, changed)
            new_view = await enqueue(sessions, prepared, qid, quote, changed, "report-new-profile")
            assert await worker.run_once()
            await completed_checkpoint(sessions, new_view)
            assert broker.routes == ["elevenlabs"] + [provider] * (chunk_count + 1) + [
                next_provider
            ]
            assert broker.payloads[0] == prepared.data
            assert all(payload.startswith(b"{") for payload in broker.payloads[1:])
            async with sessions() as db, db.begin():
                assert (
                    stable
                    == (
                        await db.execute(
                            select(
                                ConversationCheckpoint.id, ConversationCheckpoint.manifest_sha256
                            ).where(
                                ConversationCheckpoint.stage.in_(("C0", "C1", "C2", "C3", "C4"))
                            )
                        )
                    ).all()
                )
                reports = ConversationReports(ConversationApplication(db))
                assert (await reports.get(prepared.state.actor, UUID(cview["id"])))["report"]
                assert (await reports.get(prepared.state.actor, UUID(new_view["id"])))["report"]
                await reports.application.request_deletion(
                    prepared.state.actor, prepared.recording_id, key="delete-report-call"
                )
            assert await prepared.worker.run_once()
            assert (
                prepared.storage.list_recording(prepared.state.tenant_id, prepared.recording_id)
                == ()
            )
            async with sessions() as db:
                drafts = (await db.scalars(select(ConversationReportDraft))).all()
                assert len(drafts) == 2
                assert all(
                    d.erased_at and d.payload is None and d.transcript is None for d in drafts
                )
                assert (
                    await db.scalar(
                        select(func.count())
                        .select_from(ConversationCheckpoint)
                        .where(
                            ConversationCheckpoint.payload.is_not(None),
                            ConversationCheckpoint.erased_at.is_(None),
                        )
                    )
                    == 0
                )
        finally:
            await engine.dispose()

    run(exercise())
