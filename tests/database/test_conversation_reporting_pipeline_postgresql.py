"""Synthetic provider-to-report proof on disposable loopback PostgreSQL."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from ac_platform.conversation_intelligence.acquisition_reports import AcquisitionReports
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
from ac_platform.conversation_intelligence.speaker_report_basis import read_report_basis
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
    def __init__(
        self,
        data: bytes,
        *,
        deepgram_tail_ms: int | None = None,
        elevenlabs_malformed: bool = False,
    ) -> None:
        super().__init__(data, mode="malformed" if elevenlabs_malformed else "success")
        self.routes: list[str] = []
        self.deepgram_tail_ms = deepgram_tail_ms

    async def execute(self, reservation: Any, payload: bytes) -> ProviderResult:
        self.routes.append(reservation.quote.provider_id)
        if reservation.quote.provider_id == "elevenlabs":
            return await super().execute(reservation, payload)
        self.calls += 1
        self.payloads.append(payload)
        provider = reservation.quote.provider_id
        if provider == "deepgram":
            native_tail_end = (60_000 + (self.deepgram_tail_ms or 0)) / 1_000
            words = (
                [
                    {"word": "hello", "start": 0.0, "end": 54.135, "speaker": 0},
                    {"word": "buyer", "start": 54.135, "end": native_tail_end, "speaker": 1},
                ]
                if self.deepgram_tail_ms is not None
                else [
                    {"word": "hello", "start": 0.0, "end": 0.5, "speaker": 0},
                    {"word": "buyer", "start": 0.5, "end": 0.9, "speaker": 0},
                ]
            )
            data = {
                "results": {
                    "channels": [
                        {
                            "alternatives": [
                                {
                                    "transcript": "hello buyer",
                                    "words": words,
                                }
                            ]
                        }
                    ]
                }
            }
            raw = canonical(data)
            return ProviderResult(
                provider="deepgram",
                model=reservation.quote.provider_model,
                request_id=f"synthetic-deepgram-{self.calls}",
                response_sha256=hashlib.sha256(raw).hexdigest(),
                raw_json=raw,
                data=data,
                usage={},
                input_sha256=reservation.quote.input_sha256,
            )
        body = json.loads(payload)
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
            data["overview"]["strength_details"] += [
                {"finding_index": 2, "why_it_matters": "Invalid reference"},
                data["overview"]["strength_details"][0],
            ]
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
@pytest.mark.parametrize("with_roles", [False, True])
def test_saved_transcript_to_private_report_and_profile_reuse(
    postgres_harness: Any,
    tmp_path: Path,
    multiple_chunks: bool,
    provider: str,
    monkeypatch: pytest.MonkeyPatch,
    with_roles: bool,
    entitlement_seconds: int = 1,
) -> None:
    if with_roles:
        monkeypatch.setattr(
            "ac_platform.conversation_intelligence.reports.SPEAKER_ROLE_PROMPT_REVISIONS",
            frozenset({"coaching-v3"}),
        )

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
                entitlement_seconds=entitlement_seconds,
            )
            asr = await enqueue(sessions, prepared, qid, quote, None, "report-asr")
            assert await worker.run_once()
            c2 = await completed_checkpoint(sessions, asr)
            async with sessions() as db, db.begin():
                early = await ConversationReports(ConversationApplication(db)).transcript(
                    prepared.state.actor, prepared.recording_id
                )
                assert early["segments"][0]["text"].startswith("hello buyer")
                holder = early["segments"][0]["speaker_id"]
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
                coaching_prompt_revision="coaching-v3" if with_roles else "coaching-v1",
                speaker_roles={
                    "origin": "text_predicted_roles",
                    "transcript_revision": early["revision"],
                    "map_revision": "b" * 64,
                    "speakers": [
                        {"speaker_id": holder, "role": "seller", "is_account_holder": True}
                    ],
                }
                if with_roles
                else None,
            )
            qid, quote = await text_quote(sessions, prepared, coaching)
            cview = await enqueue(sessions, prepared, qid, quote, coaching, "report-coaching")
            assert await worker.run_once()
            await completed_checkpoint(sessions, cview)
            async with sessions() as db, db.begin():
                reports = ConversationReports(ConversationApplication(db))
                recording = await reports.application._recording(
                    prepared.state.actor, prepared.recording_id
                )
                reader = AcquisitionReports(
                    SimpleNamespace(database=db, clock=reports.application.clock)
                )
                basis = await read_report_basis(
                    reader,
                    recording,
                    uuid4(),
                    {
                        "transcript_revision": early["revision"],
                        "map_revision": "c" * 64,
                        "speakers": [
                            {"speaker_id": holder, "role": "you", "role_source": "confirmed"}
                        ],
                    },
                )
                assert basis == (
                    {
                        "status": "confirmed",
                        "map_revision": "b" * 64,
                        "you_speaker_id": holder,
                        "matches_current": True,
                    }
                    if with_roles
                    else None
                )
                assert not db.new and not db.dirty
                response = await reports.get(prepared.state.actor, UUID(cview["id"]))
                assert response["report"]["review_status"] == "draft_not_dipak_adjudicated"
                assert response["report"]["summary"] == "A synthetic draft from saved facts."
                assert len(response["report"]["overview"]["strength_details"]) == 1
                assert response["report"]["provider_extras"]["compatibility"]["overview_drops"][
                    "strength_details"
                ] == {"reference_out_of_range": 1, "reference_duplicate": 1}
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


@pytest.mark.parametrize("winner", ["publication", "failure"])
def test_validated_acquisition_publication_and_terminal_recovery_race(
    postgres_harness: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, winner: str
) -> None:
    """Real C2/C4/C5/C6, customer capture, source read and expired-worker recovery.

    The fixtures use approved fictional adapters and an owned database. The
    source-only failure writer is invoked by this test, never a runtime caller.
    """
    import asyncio
    import threading
    from contextlib import suppress
    from datetime import UTC, datetime, timedelta

    import httpx
    from sqlalchemy import update

    from ac_platform.audit.models import AuditEvent
    from ac_platform.conversation_intelligence.acquisition_models import (
        ConversationAcquisitionSettlement,
        ConversationAcquisitionUsage,
    )
    from ac_platform.conversation_intelligence.acquisition_usage import acquisition_seconds
    from ac_platform.conversation_intelligence.broker_router import (
        FixedProviderRouter,
        ProviderRoute,
    )
    from ac_platform.conversation_intelligence.customer_failure_candidate import (
        locked_recovered_customer_failure,
    )
    from ac_platform.conversation_intelligence.customer_terminal_settlement import (
        settle_recovered_customer_failure,
    )
    from ac_platform.conversation_intelligence.models import ConversationProcessingPlan
    from ac_platform.conversation_intelligence.processing_actor import ProcessingActor
    from ac_platform.conversation_intelligence.processing_plan import ProcessingPlanScheduler
    from ac_platform.conversation_intelligence.worker import OfflineConversationWorker
    from ac_platform.outbox.errors import LeaseLostError
    from tests.database.test_conversation_processing_plan_postgresql import _make_due
    from tests.database.test_conversation_submission_http_postgresql import (
        ORIGIN,
        PREFIX,
        _headers,
        _setup,
        _sign_in,
    )
    from tests.database.test_conversation_worker_postgresql import (
        _reconcile,
        _wav_one_second_48k,
    )

    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path, gemini=True)
        release_raw, raw_written = threading.Event(), threading.Event()
        publish_locked, release_publish = asyncio.Event(), asyncio.Event()
        publisher: Any = None
        sweeper: Any = None
        try:
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=setup.app), base_url=ORIGIN
            ) as client:
                _sign_in(setup, client)
                data, submission = _wav_one_second_48k(), uuid4()
                path = f"{PREFIX}/submissions/{submission}"
                uploaded = await client.put(
                    path + "/source", content=data, headers=await _headers(client, data)
                )
                assert uploaded.status_code == 202, uploaded.text
                await _reconcile(setup.sessions, setup.state)
                local = OfflineConversationWorker(
                    setup.sessions,
                    storage=setup.runtime.storage,
                    scratch=setup.runtime.scratch,
                    environment="test",
                )
                assert await local.run_once()
                response = await client.post(
                    path + "/plan/quote",
                    headers={
                        "Origin": ORIGIN,
                        "Idempotency-Key": "terminal-race-plan",
                    },
                )
                assert response.status_code == 201, response.text
                quoted = response.json()
                plan_id = UUID(quoted["id"])
                accepted = await client.post(
                    path + "/plan",
                    json={
                        "plan_id": quoted["id"],
                        "plan_fingerprint": quoted["plan_fingerprint"],
                        "privacy_revision": quoted["privacy_revision"],
                        "accepted": True,
                    },
                    headers={"Origin": ORIGIN, "Idempotency-Key": "terminal-race-accept"},
                )
                assert accepted.status_code == 202, accepted.text
                broker = ReportingBroker(data)
                worker = ConversationInferenceWorker(
                    setup.sessions,
                    setup.runtime.storage,
                    FixedProviderRouter(
                        {
                            provider: ProviderRoute(provider, f"ref:credential:{provider}", broker)
                            for provider in ("elevenlabs", "gemini")
                        },
                        authority=setup.authority,
                    ),
                    authority=setup.authority,
                )
                scheduler = ProcessingPlanScheduler(setup.sessions, setup.authority)
                for _ in range(2):
                    assert await worker.run_once()
                    await _make_due(setup, plan_id)
                    await scheduler.step()
                work = await worker.claim()
                assert work is not None
                async with setup.sessions() as db:
                    task = await db.scalar(
                        select(ConversationInferenceTask).where(
                            ConversationInferenceTask.job_id == work.job_id
                        )
                    )
                    assert task is not None and task.stage == "C5"
                    run_id = task.run_id
                    plan = await db.get(ConversationProcessingPlan, plan_id)
                    actor = ProcessingActor(
                        plan.person_id, plan.tenant_id, plan.processing_lease_id
                    )
                    usage = await db.scalar(
                        select(ConversationAcquisitionUsage).where(
                            ConversationAcquisitionUsage.submission_id == submission
                        )
                    )
                    usage_id = usage.id
                original_save = worker._save_raw

                def pause_raw(scope: Any, result: Any) -> None:
                    original_save(scope, result)
                    raw_written.set()
                    if not release_raw.wait(10):
                        raise RuntimeError("fictional raw publication barrier timed out")

                monkeypatch.setattr(worker, "_save_raw", pause_raw)
                original_finish = ReportingPipeline.finish

                async def pause_finish(self: Any, *args: Any, **kwargs: Any) -> None:
                    publish_locked.set()
                    await asyncio.wait_for(release_publish.wait(), 10)
                    await original_finish(self, *args, **kwargs)

                if winner == "publication":
                    monkeypatch.setattr(ReportingPipeline, "finish", pause_finish)
                publisher = asyncio.create_task(worker._dispatch(work))
                assert await asyncio.to_thread(raw_written.wait, 10)
                # Only this fictional job's existing finite lease is moved to
                # the boundary. Dispatch markers, receipts and attempts remain.
                async with setup.sessions() as db, db.begin():
                    await db.execute(
                        update(Job)
                        .where(Job.id == work.job_id)
                        .values(
                            leased_until=datetime.now(UTC) + timedelta(seconds=10)
                            if winner == "publication"
                            else datetime.now(UTC) - timedelta(seconds=1),
                            **({"max_attempts": Job.attempt_count} if winner == "failure" else {}),
                        )
                    )
                if winner == "publication":
                    release_raw.set()
                    await asyncio.wait_for(publish_locked.wait(), 5)
                    # The live publication has the canonical job/run locks.
                    # Concurrent recovery must not manufacture a failure.
                    # The opposite case below expires the same worker first.
                    sweeper = asyncio.create_task(worker.claim())
                    await asyncio.sleep(0.05)
                    release_publish.set()
                    await asyncio.wait_for(publisher, 5)
                    assert await asyncio.wait_for(sweeper, 5) is None
                    report = await client.get(path + "/report")
                    assert report.status_code == 200, report.text
                    envelope = report.json()
                    assert envelope["source_sha256"] == hashlib.sha256(data).hexdigest()
                    assert envelope["report"]["access"] == "claimed_account"
                    assert (
                        envelope["report"]["content"]["overview"]["version"] == "dipak-14-point-v1"
                    )
                    transcript = await client.get(path + "/transcript")
                    assert transcript.status_code == 200
                    assert transcript.json()["revision"] == envelope["transcript_revision"]
                else:
                    assert await asyncio.wait_for(worker.claim(), 5) is None
                    async with setup.sessions() as db:
                        event = await db.scalar(
                            select(AuditEvent).where(
                                AuditEvent.tenant_id == actor.tenant_id,
                                AuditEvent.action == "conversation.provider_job_recovery_required",
                                AuditEvent.resource_id == str(work.job_id),
                            )
                        )
                        assert event is not None
                        event_id = event.id
                    async with (
                        setup.sessions() as db,
                        locked_recovered_customer_failure(
                            db, actor=actor, run_id=run_id, event_id=event_id
                        ) as receipt,
                    ):
                        failure = receipt
                    async with setup.sessions() as db:
                        result = await settle_recovered_customer_failure(
                            db, actor=actor, run_id=run_id, event_id=event_id, receipt=failure
                        )
                        assert result.changed
                    release_raw.set()
                    with pytest.raises((LeaseLostError, ConversationConflict)):
                        await asyncio.wait_for(publisher, 5)
                    assert (await client.get(path + "/report")).status_code == 404
                async with setup.sessions() as db:
                    settlement = await db.get(ConversationAcquisitionSettlement, usage_id)
                    assert settlement is not None
                    assert (settlement.kind, settlement.charged_seconds) == (
                        ("completed", 1) if winner == "publication" else ("terminal_failure", 0)
                    )
                    count = await db.scalar(
                        select(func.count())
                        .select_from(ConversationReportDraft)
                        .where(ConversationReportDraft.recording_id == task.recording_id)
                    )
                    assert count == (1 if winner == "publication" else 0)
                    assert await acquisition_seconds(
                        db, tenant_id=setup.state.tenant_id, person_id=setup.state.person_id
                    ) == (1 if winner == "publication" else 0)
                    job = await db.get(Job, work.job_id)
                    assert job.dispatch_started_at is not None and job.provider_receipt is not None
                    assert job.provider_receipt["validation_state"] == (
                        "validated" if winner == "publication" else "provider_returned"
                    )
                assert broker.routes == ["elevenlabs", "gemini", "gemini"]
                assert broker.calls == 3
                client.cookies.clear()
                client.cookies.set("ac_xray_guest", setup.stranger.token)
                assert (await client.get(path + "/report")).status_code == 404
        finally:
            release_raw.set()
            release_publish.set()
            for pending in (publisher, sweeper):
                if pending is not None and not pending.done():
                    with suppress(Exception):
                        await asyncio.wait_for(pending, 10)
            await setup.engine.dispose()

    run(exercise())
