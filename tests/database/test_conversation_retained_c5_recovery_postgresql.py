"""Disposable PostgreSQL proof for retained C5 recovery.

This fixture creates only synthetic source-bound rows in a per-test schema. It
uses the retained response object already written to the private test storage;
no provider transport, worker dispatch or production database is involved.
"""

from __future__ import annotations

import hashlib
from datetime import timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from ac_platform.conversation_intelligence.acquisition_processing import (
    AcquisitionProcessing,
    upload_policy,
)
from ac_platform.conversation_intelligence.acquisition_sessions import MeasuredSource
from ac_platform.conversation_intelligence.acquisition_source import MeasuredUpload
from ac_platform.conversation_intelligence.application import (
    ConversationApplication,
    ConversationConflict,
    utc,
)
from ac_platform.conversation_intelligence.checkpoints import (
    SourceBinding,
    build_checkpoint,
    canonical,
    content_hash,
)
from ac_platform.conversation_intelligence.contracts import IntakeIntent
from ac_platform.conversation_intelligence.entitlements import ExecutionPermission, Quote
from ac_platform.conversation_intelligence.guest_models import ConversationGuestSubmission
from ac_platform.conversation_intelligence.guest_ownership import GuestOwnership
from ac_platform.conversation_intelligence.inference import binding_for
from ac_platform.conversation_intelligence.inference_tasks import prepare_coaching_input
from ac_platform.conversation_intelligence.models import (
    ConversationCheckpoint,
    ConversationInferenceTask,
    ConversationPermission,
    ConversationQuote,
    ConversationRecording,
    ConversationRun,
)
from ac_platform.conversation_intelligence.recovery_models import ConversationRetainedC5Version
from ac_platform.conversation_intelligence.reports import (
    GROQ_MODEL,
    FactPacket,
    load_report_profile,
)
from ac_platform.conversation_intelligence.retained_c5_recovery import (
    RetainedC5Correction,
    RetainedC5CorrectionIntent,
    RetainedC5RecoveryService,
)
from ac_platform.conversation_intelligence.storage import ObjectKey, ObjectKind
from ac_platform.http.auth import install_identity_http
from ac_platform.http.conversation_admin import install_conversation_admin_http
from ac_platform.identity.models import Person
from ac_platform.kernel.authz import ActorContext
from ac_platform.outbox.models import Job
from ac_platform.outbox.repository import canonical_receipt_digest
from ac_platform.tenancy.models import Membership
from tests.database.test_conversation_postgresql import run
from tests.database.test_conversation_submission_http_postgresql import (
    ORIGIN as ACQUISITION_ORIGIN,
)
from tests.database.test_conversation_submission_http_postgresql import (
    _setup as acquisition_setup,
)
from tests.database.test_conversation_worker_postgresql import _prepare, _wav_one_second_48k

pytest_plugins = ("tests.database.test_conversation_postgresql",)


def _transcript(source_sha256: str) -> dict[str, Any]:
    return {
        "source_sha256": source_sha256,
        "revision": "synthetic-c2-recovery-r1",
        "timebase_id": "scribe-native-seconds",
        "duration_ms": 1_000,
        "segments": [
            {
                "id": "seg-1",
                "speaker_id": "speaker-1",
                "start_ms": 0,
                "end_ms": 800,
                "text": "Buyer asks about price and timing.",
            }
        ],
    }


def _facts(source_sha256: str, revision: str) -> FactPacket:
    return FactPacket.model_validate(
        {
            "schema": "ac.sales-xray.style-independent-facts/1",
            "source_sha256": source_sha256,
            "transcript_revision": revision,
            "timebase_id": "scribe-native-seconds",
            "chunk_index": 1,
            "chunk_count": 1,
            "covered_segment_ids": ["seg-1"],
            "overview": "The buyer asked about price and timing.",
            "observations": [],
            "uncertainties": [],
        }
    )


def _provider_raw(*, quote: str) -> bytes:
    report = {
        "summary": "A synthetic qualitative draft for human review.",
        "strengths": [
            {
                "title": "A source-bound observation",
                "explanation": "The call contains a directly observable buyer question.",
                "evidence": [{"segment_id": "seg-1", "quote": quote, "start_ms": 0, "end_ms": 800}],
            }
        ],
        "missed_opportunities": [],
        "improvements": [],
        "objection_analysis": [],
        "closing_analysis": [],
        "verdict": "Qualitative draft only; human review is required.",
        "review_status": "draft_not_dipak_adjudicated",
    }
    envelope = {"choices": [{"message": {"content": canonical(report).decode("utf-8")}}]}
    return canonical(envelope)


async def _seed_retained_case(postgres_harness: Any, scratch_root: Path) -> dict[str, Any]:
    prepared = await _prepare(postgres_harness, scratch_root)
    engine = create_async_engine(postgres_harness.url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sessions() as database, database.begin():
            person = await database.get(Person, prepared.state.person_id)
            membership = await database.get(
                Membership,
                (prepared.state.tenant_id, prepared.state.person_id),
            )
            assert person is not None and membership is not None
            person.email = "admin@authorityclosers.com"
            person.email_verified_at = prepared.state.now
            membership.role = "admin"
            recording = await database.get(ConversationRecording, prepared.recording_id)
            assert recording is not None
            binding = binding_for(recording)
            c0_payload = {
                "source_sha256": recording.source_sha256,
                "source_bytes": recording.source_bytes,
                "content_type": recording.content_type,
                "permission_reference": str(recording.permission_id),
            }
            c0 = build_checkpoint(
                binding,
                "C0",
                "synthetic-recording-v1",
                {},
                (),
                content_hash(c0_payload),
            )
            c1 = build_checkpoint(
                binding,
                "C1",
                "synthetic-measurement-v1",
                {},
                (c0,),
                content_hash({"schema": "synthetic-measurement"}),
            )
            transcript = _transcript(recording.source_sha256)
            facts = _facts(recording.source_sha256, transcript["revision"])
            profile = load_report_profile()
            prepared_input = prepare_coaching_input(
                transcript,
                [facts],
                provider="groq",
                model=GROQ_MODEL,
                profile=profile,
                max_completion_tokens=1_800,
                output_profile="standard",
            )
            c2 = build_checkpoint(
                binding,
                "C2",
                "synthetic-transcript-v1",
                {},
                (c0,),
                content_hash(transcript),
            )
            c3_payload = {"schema": "ac.sales-xray.alignment/1", "segments": ["seg-1"]}
            c3 = build_checkpoint(
                binding,
                "C3",
                "synthetic-alignment-v1",
                {},
                (c1, c2),
                content_hash(c3_payload),
            )
            fact_payload = facts.model_dump(mode="json", by_alias=True)
            c4 = build_checkpoint(
                binding,
                "C4",
                "synthetic-facts-v1",
                {
                    "chunk_index": 1,
                    "chunk_count": 1,
                    "provider": "groq",
                    "model": GROQ_MODEL,
                    "input_sha256": prepared_input.input_sha256,
                },
                (c2, c3),
                content_hash(fact_payload),
            )
            for checkpoint, payload in ((c2, transcript), (c3, c3_payload), (c4, fact_payload)):
                database.add(
                    ConversationCheckpoint(
                        id=uuid4(),
                        tenant_id=recording.tenant_id,
                        person_id=recording.person_id,
                        recording_id=recording.id,
                        cache_key=checkpoint.cache_key,
                        manifest_sha256=checkpoint.manifest_sha256,
                        payload_sha256=checkpoint.payload_sha256,
                        stage=checkpoint.stage,
                        feature_blob_id=None,
                        manifest=checkpoint.as_dict(),
                        payload=payload,
                        created_at=prepared.state.now,
                    )
                )
            await database.flush()
            c2_row = await database.scalar(
                select(ConversationCheckpoint).where(
                    ConversationCheckpoint.recording_id == recording.id,
                    ConversationCheckpoint.manifest_sha256 == c2.manifest_sha256,
                )
            )
            c3_row = await database.scalar(
                select(ConversationCheckpoint).where(
                    ConversationCheckpoint.recording_id == recording.id,
                    ConversationCheckpoint.manifest_sha256 == c3.manifest_sha256,
                )
            )
            c4_row = await database.scalar(
                select(ConversationCheckpoint).where(
                    ConversationCheckpoint.recording_id == recording.id,
                    ConversationCheckpoint.manifest_sha256 == c4.manifest_sha256,
                )
            )
            assert c2_row is not None and c3_row is not None and c4_row is not None

            quote_id = uuid4()
            quote = Quote(
                quote_id=str(quote_id),
                source=SourceBinding(
                    str(recording.tenant_id),
                    str(recording.id),
                    recording.source_sha256,
                    str(recording.source_revision),
                ),
                account_id=str(recording.person_id),
                budget_scope_id=str(prepared.scope_id),
                provider_id="groq",
                provider_model=GROQ_MODEL,
                recipe_revision="qualitative-coaching-v1",
                operation="chat_completion",
                input_sha256=prepared_input.input_sha256,
                privacy_revision="synthetic-local-privacy-v1",
                permission_ref=str(recording.permission_id),
                provider_terms_ref="synthetic-no-provider-call",
                retention_ref="delete-test-schema",
                professional_gate_ref="synthetic-fixture-only",
                pricing_ref="local-zero-price",
                entitlement_seconds=120,
                max_cost_paise=0,
                created_at_epoch=int(prepared.state.now.timestamp()) - 1,
                expires_at_epoch=int(prepared.state.now.timestamp()) + 3600,
            )
            database.add(
                ConversationQuote(
                    id=quote_id,
                    tenant_id=recording.tenant_id,
                    person_id=recording.person_id,
                    recording_id=recording.id,
                    budget_scope_id=prepared.scope_id,
                    quote=quote.as_dict(),
                    execution_permission=ExecutionPermission(
                        "synthetic-recovery-execution",
                        quote.fingerprint,
                        "synthetic-admin",
                        int(prepared.state.now.timestamp()) + 3600,
                    ).as_dict(),
                )
            )
            raw_blob_id = uuid4()
            raw = _provider_raw(quote="Wrong quote")
            raw_sha256 = hashlib.sha256(raw).hexdigest()
            prepared.storage.put(
                ObjectKey(
                    recording.tenant_id,
                    recording.id,
                    raw_blob_id,
                    ObjectKind.PROVIDER_RESPONSE,
                ),
                (raw,),
                expected_sha256=raw_sha256,
                expected_bytes=len(raw),
            )
            receipt = {
                "schema": "ac.sales-xray.provider-receipt/1",
                "provider": "groq",
                "model": GROQ_MODEL,
                "provider_request_id": "synthetic-provider-request",
                "response_sha256": raw_sha256,
                "raw_blob_id": str(raw_blob_id),
                "input_sha256": prepared_input.input_sha256,
                "human_approved": False,
                "usage": {"total_tokens": 0},
                "idempotency_key": "synthetic-provider-idempotency",
            }
            job_id = uuid4()
            database.add(
                Job(
                    id=job_id,
                    tenant_id=recording.tenant_id,
                    kind="conversation.infer_provider.v1",
                    dedupe_key=f"synthetic-recovery:{job_id}",
                    payload={"stage": "C5", "recording_id": str(recording.id)},
                    external_side_effect=True,
                    recovery_generation=1,
                    status="dead_letter",
                    attempt_count=1,
                    max_attempts=1,
                    last_error="synthetic semantic validation failure",
                    provider_idempotency_key=receipt["idempotency_key"],
                    dispatch_started_at=prepared.state.now,
                    provider_receipt=receipt,
                    provider_receipt_digest=canonical_receipt_digest(receipt),
                    receipt_recorded_at=prepared.state.now,
                    dead_lettered_at=prepared.state.now,
                    created_at=prepared.state.now,
                    updated_at=prepared.state.now,
                )
            )
            await database.flush()
            run_id = uuid4()
            request = {
                "stage": "C5",
                "transcript_checkpoint_id": str(c2_row.id),
                "fact_checkpoint_ids": [str(c4_row.id)],
                "chunk_index": 1,
                "provider": "groq",
                "model": GROQ_MODEL,
                "max_input_chars": 16_000,
                "max_completion_tokens": 1_800,
                "output_profile": "standard",
                "profile": profile,
            }
            intent = {
                "schema": "ac.sales-xray.text-intent/1",
                "request": request,
                "input": prepared_input.as_dict(),
                "checkpoint": {"stage": "C5", "canonical_checkpoint_id": None},
            }
            database.add(
                ConversationRun(
                    id=run_id,
                    tenant_id=recording.tenant_id,
                    person_id=recording.person_id,
                    recording_id=recording.id,
                    request_key=f"synthetic-recovery-run:{run_id}",
                    intent_sha256=content_hash({"run_id": str(run_id)}),
                    recipe_revision="qualitative-coaching-v1",
                    generation=recording.generation,
                    state="failed",
                    job_id=job_id,
                    created_at=prepared.state.now,
                    completed_at=None,
                )
            )
            await database.flush()
            database.add(
                ConversationInferenceTask(
                    run_id=run_id,
                    tenant_id=recording.tenant_id,
                    person_id=recording.person_id,
                    recording_id=recording.id,
                    session_id=prepared.state.session_id,
                    processing_lease_id=None,
                    job_id=job_id,
                    quote_id=quote_id,
                    generation=recording.generation,
                    stage="C5",
                    cache_key=content_hash({"recovery": str(run_id)}),
                    input_sha256=prepared_input.input_sha256,
                    intent_sha256=content_hash(intent),
                    intent=intent,
                    state="failed",
                    checkpoint_id=None,
                    created_at=prepared.state.now,
                    erased_at=None,
                )
            )
            await database.flush()
        return {
            "prepared": prepared,
            "engine": engine,
            "sessions": sessions,
            "run_id": run_id,
            "raw_sha256": raw_sha256,
            "historical_input": prepared_input.payload,
            "recording_id": prepared.recording_id,
        }
    except BaseException:
        await engine.dispose()
        raise


async def _seed_guest_retained_case(postgres_harness: Any, scratch_root: Path) -> dict[str, Any]:
    """Create the same retained C5 shape through the acquisition owner path."""

    setup = await acquisition_setup(postgres_harness, scratch_root)
    try:
        data = _wav_one_second_48k()
        submission_id = uuid4()
        async with setup.sessions() as database, database.begin():
            sessions = setup.factory(database)
            processing = AcquisitionProcessing(GuestOwnership(sessions), setup.runtime)
            measured = MeasuredUpload(
                MeasuredSource(
                    submission_id,
                    hashlib.sha256(data).hexdigest(),
                    1_000,
                    "e" * 64,
                ),
                IntakeIntent(
                    source_sha256=hashlib.sha256(data).hexdigest(),
                    source_bytes=len(data),
                    content_type="audio/wav",
                    duration_ms=1_000,
                    purpose="internal_analysis",
                ),
            )
            processing_actor, quote_payload = await processing.prepare(
                measured,
                policy_sha256=upload_policy(setup.runtime.policy)["policy_sha256"],
                token=setup.guest.token,
            )
            recording_id = UUID(quote_payload["recording_id"])
            await processing.application.store_source(
                processing_actor,
                recording_id,
                chunks=(data,),
                storage=setup.runtime.storage,
            )
            await processing.enqueue(processing_actor, quote_payload)
            recording = await database.get(ConversationRecording, recording_id)
            assert recording is not None
            run_row = await database.scalar(
                select(ConversationRun).where(
                    ConversationRun.recording_id == recording_id,
                    ConversationRun.tenant_id == setup.state.tenant_id,
                    ConversationRun.person_id == recording.person_id,
                )
            )
            link = await database.scalar(
                select(ConversationGuestSubmission).where(
                    ConversationGuestSubmission.recording_id == recording_id,
                    ConversationGuestSubmission.tenant_id == setup.state.tenant_id,
                )
            )
            quote = await database.scalar(
                select(ConversationQuote).where(
                    ConversationQuote.recording_id == recording_id,
                    ConversationQuote.tenant_id == setup.state.tenant_id,
                    ConversationQuote.person_id == recording.person_id,
                )
            )
            assert run_row is not None and link is not None and quote is not None
            job = await database.get(Job, run_row.job_id)
            assert job is not None
            binding = binding_for(recording)
            c0_payload = {
                "source_sha256": recording.source_sha256,
                "source_bytes": recording.source_bytes,
                "content_type": recording.content_type,
                "permission_reference": str(recording.permission_id),
            }
            c0 = build_checkpoint(
                binding,
                "C0",
                "synthetic-recording-v1",
                {},
                (),
                content_hash(c0_payload),
            )
            c1 = build_checkpoint(
                binding,
                "C1",
                "synthetic-measurement-v1",
                {},
                (c0,),
                content_hash({"schema": "synthetic-measurement"}),
            )
            transcript = _transcript(recording.source_sha256)
            facts = _facts(recording.source_sha256, transcript["revision"])
            profile = load_report_profile()
            prepared_input = prepare_coaching_input(
                transcript,
                [facts],
                provider="groq",
                model=GROQ_MODEL,
                profile=profile,
                max_completion_tokens=1_800,
                output_profile="standard",
            )
            c2 = build_checkpoint(
                binding,
                "C2",
                "synthetic-transcript-v1",
                {},
                (c0,),
                content_hash(transcript),
            )
            c3_payload = {"schema": "ac.sales-xray.alignment/1", "segments": ["seg-1"]}
            c3 = build_checkpoint(
                binding,
                "C3",
                "synthetic-alignment-v1",
                {},
                (c1, c2),
                content_hash(c3_payload),
            )
            fact_payload = facts.model_dump(mode="json", by_alias=True)
            c4 = build_checkpoint(
                binding,
                "C4",
                "synthetic-facts-v1",
                {
                    "chunk_index": 1,
                    "chunk_count": 1,
                    "provider": "groq",
                    "model": GROQ_MODEL,
                    "input_sha256": prepared_input.input_sha256,
                },
                (c2, c3),
                content_hash(fact_payload),
            )
            for checkpoint, payload in ((c2, transcript), (c3, c3_payload), (c4, fact_payload)):
                database.add(
                    ConversationCheckpoint(
                        id=uuid4(),
                        tenant_id=recording.tenant_id,
                        person_id=recording.person_id,
                        recording_id=recording.id,
                        cache_key=checkpoint.cache_key,
                        manifest_sha256=checkpoint.manifest_sha256,
                        payload_sha256=checkpoint.payload_sha256,
                        stage=checkpoint.stage,
                        feature_blob_id=None,
                        manifest=checkpoint.as_dict(),
                        payload=payload,
                        created_at=setup.state.now,
                    )
                )
            await database.flush()
            c2_row = await database.scalar(
                select(ConversationCheckpoint).where(
                    ConversationCheckpoint.recording_id == recording.id,
                    ConversationCheckpoint.manifest_sha256 == c2.manifest_sha256,
                )
            )
            c3_row = await database.scalar(
                select(ConversationCheckpoint).where(
                    ConversationCheckpoint.recording_id == recording.id,
                    ConversationCheckpoint.manifest_sha256 == c3.manifest_sha256,
                )
            )
            c4_row = await database.scalar(
                select(ConversationCheckpoint).where(
                    ConversationCheckpoint.recording_id == recording.id,
                    ConversationCheckpoint.manifest_sha256 == c4.manifest_sha256,
                )
            )
            assert c2_row is not None and c3_row is not None and c4_row is not None
            raw_blob_id = uuid4()
            raw = _provider_raw(quote="Wrong quote")
            raw_sha256 = hashlib.sha256(raw).hexdigest()
            setup.runtime.storage.put(
                ObjectKey(
                    recording.tenant_id,
                    recording.id,
                    raw_blob_id,
                    ObjectKind.PROVIDER_RESPONSE,
                ),
                (raw,),
                expected_sha256=raw_sha256,
                expected_bytes=len(raw),
            )
            receipt = {
                "schema": "ac.sales-xray.provider-receipt/1",
                "provider": "groq",
                "model": GROQ_MODEL,
                "provider_request_id": "synthetic-provider-request",
                "response_sha256": raw_sha256,
                "raw_blob_id": str(raw_blob_id),
                "input_sha256": prepared_input.input_sha256,
                "human_approved": False,
                "usage": {"total_tokens": 0},
                "idempotency_key": "synthetic-provider-idempotency",
            }
            job.status = "dead_letter"
            job.attempt_count = 1
            job.last_error = "synthetic semantic validation failure"
            job.provider_idempotency_key = receipt["idempotency_key"]
            job.dispatch_started_at = setup.state.now
            job.provider_receipt = receipt
            job.provider_receipt_digest = canonical_receipt_digest(receipt)
            job.receipt_recorded_at = setup.state.now
            job.dead_lettered_at = setup.state.now
            run_row.state = "failed"
            request = {
                "stage": "C5",
                "transcript_checkpoint_id": str(c2_row.id),
                "fact_checkpoint_ids": [str(c4_row.id)],
                "chunk_index": 1,
                "provider": "groq",
                "model": GROQ_MODEL,
                "max_input_chars": 16_000,
                "max_completion_tokens": 1_800,
                "output_profile": "standard",
                "profile": profile,
            }
            intent = {
                "schema": "ac.sales-xray.text-intent/1",
                "request": request,
                "input": prepared_input.as_dict(),
                "checkpoint": {"stage": "C5", "canonical_checkpoint_id": None},
            }
            database.add(
                ConversationInferenceTask(
                    run_id=run_row.id,
                    tenant_id=recording.tenant_id,
                    person_id=recording.person_id,
                    recording_id=recording.id,
                    session_id=None,
                    processing_lease_id=link.processing_lease_id,
                    job_id=job.id,
                    quote_id=quote.id,
                    generation=recording.generation,
                    stage="C5",
                    cache_key=content_hash({"recovery": str(run_row.id)}),
                    input_sha256=prepared_input.input_sha256,
                    intent_sha256=content_hash(intent),
                    intent=intent,
                    state="failed",
                    checkpoint_id=None,
                    created_at=setup.state.now,
                    erased_at=None,
                )
            )
            person = await database.get(Person, setup.state.person_id)
            membership = await database.get(
                Membership, (setup.state.tenant_id, setup.state.person_id)
            )
            assert person is not None and membership is not None
            person.email = "dipak@authorityclosers.com"
            membership.role = "admin"
            await database.flush()
        return {
            "setup": setup,
            "run_id": run_row.id,
            "recording_id": recording_id,
            "submission_id": submission_id,
            "raw_sha256": raw_sha256,
            "historical_input": prepared_input.payload,
            "source_bytes": data,
        }
    except BaseException:
        await setup.engine.dispose()
        raise


def test_retained_c5_recovery_real_postgres(postgres_harness: Any, tmp_path: Path) -> None:
    async def exercise() -> None:
        case = await _seed_retained_case(postgres_harness, tmp_path)
        engine = case["engine"]
        sessions: async_sessionmaker[AsyncSession] = case["sessions"]
        prepared = case["prepared"]
        admin_actor = ActorContext(
            prepared.state.person_id,
            prepared.state.session_id,
            prepared.state.tenant_id,
            frozenset({"admin_surface"}),
        )
        service = None
        try:
            async with sessions() as database, database.begin():
                service = RetainedC5RecoveryService(
                    ConversationApplication(database, clock=lambda: prepared.state.now),
                    operations_tenant_id=prepared.state.tenant_id,
                    recording_tenant_ids=(prepared.state.tenant_id,),
                )
                with pytest.raises(ConversationConflict):
                    await service.revalidate(
                        admin_actor,
                        case["run_id"],
                        original_raw_sha256=case["raw_sha256"],
                        key="recovery-wrong-input",
                        storage=prepared.storage,
                        historical_input=b"not-the-retained-input",
                    )
                with pytest.raises(ConversationConflict):
                    await service.revalidate(
                        admin_actor,
                        case["run_id"],
                        original_raw_sha256="0" * 64,
                        key="recovery-wrong-raw",
                        storage=prepared.storage,
                        historical_input=case["historical_input"],
                    )
                first = await service.revalidate(
                    admin_actor,
                    case["run_id"],
                    original_raw_sha256=case["raw_sha256"],
                    key="recovery-auto",
                    storage=prepared.storage,
                    historical_input=None,
                )
                assert first["recovery"]["validation_state"] == "needs_correction"
                assert first["report"] is None
            async with sessions() as database:
                task_before = await database.get(ConversationInferenceTask, case["run_id"])
                job_before = await database.get(Job, task_before.job_id if task_before else None)
                run_before = await database.get(ConversationRun, case["run_id"])
                assert (
                    task_before is not None
                    and task_before.state == "failed"
                    and job_before is not None
                    and job_before.status == "dead_letter"
                    and run_before is not None
                    and run_before.state == "failed"
                )
            correction = RetainedC5Correction(
                path="/strengths/0/evidence/0/quote",
                old_sha256=hashlib.sha256(b"Wrong quote").hexdigest(),
                new_text="Buyer asks about price and timing.",
                source_segment_ids=("seg-1",),
                rationale="The retained transcript provides the exact source quote.",
            )
            intent = RetainedC5CorrectionIntent(
                original_raw_sha256=case["raw_sha256"],
                corrections=(correction,),
                correction_payload_sha256=content_hash([correction.model_dump(mode="json")]),
            )
            async with sessions() as database, database.begin():
                service = RetainedC5RecoveryService(
                    ConversationApplication(database, clock=lambda: prepared.state.now),
                    operations_tenant_id=prepared.state.tenant_id,
                    recording_tenant_ids=(prepared.state.tenant_id,),
                )
                corrected = await service.revalidate(
                    admin_actor,
                    case["run_id"],
                    original_raw_sha256=case["raw_sha256"],
                    key="recovery-correct",
                    storage=prepared.storage,
                    correction=intent,
                    historical_input=case["historical_input"],
                )
                assert corrected["recovery"]["validation_state"] == "corrected"
                assert corrected["report"] is not None
                assert corrected["recovery"]["provider_calls"] == 0
            async with sessions() as database, database.begin():
                service = RetainedC5RecoveryService(
                    ConversationApplication(database, clock=lambda: prepared.state.now),
                    operations_tenant_id=prepared.state.tenant_id,
                    recording_tenant_ids=(prepared.state.tenant_id,),
                )
                replay = await service.revalidate(
                    admin_actor,
                    case["run_id"],
                    original_raw_sha256=case["raw_sha256"],
                    key="recovery-correct",
                    storage=prepared.storage,
                    correction=intent,
                    historical_input=case["historical_input"],
                )
                assert replay["id"] == corrected["id"]
            async with sessions() as database, database.begin():
                service = RetainedC5RecoveryService(
                    ConversationApplication(database, clock=lambda: prepared.state.now),
                    operations_tenant_id=prepared.state.tenant_id,
                    recording_tenant_ids=(prepared.state.tenant_id,),
                )
                owner = await service.owner_report(prepared.state.actor, case["run_id"])
                admin = await service.admin_report(admin_actor, case["run_id"])
                assert owner is not None and owner["report"] is not None
                assert admin is not None and admin["report"] is not None
            async with sessions() as database, database.begin():
                permission = await database.get(
                    ConversationPermission, prepared.state.permission_id
                )
                assert permission is not None
                permission.retention_until = prepared.state.now + timedelta(seconds=1)
            async with sessions() as database, database.begin():
                service = RetainedC5RecoveryService(
                    ConversationApplication(
                        database, clock=lambda: prepared.state.now + timedelta(seconds=2)
                    ),
                    operations_tenant_id=prepared.state.tenant_id,
                    recording_tenant_ids=(prepared.state.tenant_id,),
                )
                with pytest.raises(ConversationConflict):
                    await service.admin_report(admin_actor, case["run_id"])
            async with sessions() as database, database.begin():
                permission = await database.get(
                    ConversationPermission, prepared.state.permission_id
                )
                assert permission is not None
                permission.retention_until = prepared.state.now.replace(
                    year=prepared.state.now.year + 1
                )
                versions = (
                    await database.scalars(
                        select(ConversationRetainedC5Version).where(
                            ConversationRetainedC5Version.run_id == case["run_id"]
                        )
                    )
                ).all()
                assert len(versions) == 2
                for version in versions:
                    version.c5_input = None
                    version.original_quote = None
                    version.original_attempt = None
                    version.original_receipt = None
                    version.correction = None
                    version.proof = None
                    version.payload = None
                    version.erased_at = utc(prepared.state.now)
                await database.flush()
            async with sessions() as database:
                versions = (
                    await database.scalars(
                        select(ConversationRetainedC5Version).where(
                            ConversationRetainedC5Version.run_id == case["run_id"]
                        )
                    )
                ).all()
                assert len(versions) == 2
                assert all(
                    version.payload is None
                    and version.erased_at is not None
                    and version.original_raw_sha256 == case["raw_sha256"]
                    for version in versions
                )
        finally:
            await engine.dispose()

    run(exercise())


def test_retained_c5_recovery_http_admin_and_acquisition_reads(
    postgres_harness: Any, tmp_path: Path
) -> None:
    async def exercise() -> None:
        case = await _seed_guest_retained_case(postgres_harness, tmp_path)
        setup = case["setup"]
        admin_settings = setup.settings.model_copy(
            update={"operations_tenant_id": setup.state.tenant_id}
        )
        require_actor = install_identity_http(
            setup.app, settings=admin_settings, sessions=setup.sessions
        )
        install_conversation_admin_http(
            setup.app,
            settings=admin_settings,
            require_actor=require_actor,
            recovery_storage=setup.runtime.storage,
        )
        try:
            endpoint = f"/v1/admin/conversation/runs/{case['run_id']}"
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=setup.app),
                base_url=str(admin_settings.admin_app_url),
            ) as admin_client:
                admin_client.cookies.set(admin_settings.session_cookie_name, setup.token)
                revalidated = await admin_client.post(
                    endpoint + "/retained-c5/revalidate",
                    headers={
                        "Origin": str(admin_settings.admin_app_url).rstrip("/"),
                        "Idempotency-Key": "http-retained-c5-revalidate",
                    },
                    json={"original_raw_sha256": case["raw_sha256"]},
                )
                assert revalidated.status_code == 201, revalidated.text
                correction = RetainedC5Correction(
                    path="/strengths/0/evidence/0/quote",
                    old_sha256=hashlib.sha256(b"Wrong quote").hexdigest(),
                    new_text="Buyer asks about price and timing.",
                    source_segment_ids=("seg-1",),
                    rationale="The retained transcript provides the exact source quote.",
                )
                corrected = RetainedC5CorrectionIntent(
                    original_raw_sha256=case["raw_sha256"],
                    corrections=(correction,),
                    correction_payload_sha256=content_hash([correction.model_dump(mode="json")]),
                )
                corrected_response = await admin_client.post(
                    endpoint + "/retained-c5/correct",
                    headers={
                        "Origin": str(admin_settings.admin_app_url).rstrip("/"),
                        "Idempotency-Key": "http-retained-c5-correct",
                    },
                    json=corrected.model_dump(mode="json"),
                )
                assert corrected_response.status_code == 201, corrected_response.text
                assert corrected_response.json()["report"] is not None

            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=setup.app), base_url=ACQUISITION_ORIGIN
            ) as guest_client:
                guest_client.cookies.set("ac_xray_guest", setup.guest.token)
                prefix = f"/v1/conversation/acquisition/submissions/{case['submission_id']}"
                report = await guest_client.get(prefix + "/report")
                transcript = await guest_client.get(prefix + "/transcript")
                progress = await guest_client.get(prefix)
                assert report.status_code == 200, report.text
                assert transcript.status_code == 200, transcript.text
                assert progress.status_code == 200, progress.text
                assert report.json()["recovery"]["provider_calls"] == 0
                assert report.json()["report"]["review_status"] == "draft_not_dipak_adjudicated"
                assert transcript.json()["source_sha256"] == report.json()["source_sha256"]
                assert transcript.json()["segments"][0]["id"] == "seg-1"
                assert progress.json()["state"] == "report_ready"
                source = await guest_client.get(prefix + "/source")
                assert source.status_code == 200, source.text
                assert source.content == case["source_bytes"]
                guest_client.cookies.set("ac_xray_guest", setup.stranger.token)
                for suffix in ("", "/report", "/transcript"):
                    denied = await guest_client.get(prefix + suffix)
                    assert denied.status_code == 404, denied.text

            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=setup.app),
                base_url=str(admin_settings.admin_app_url),
            ) as admin_client:
                admin_client.cookies.set(admin_settings.session_cookie_name, setup.token)
                opened = await admin_client.get(endpoint + "/report")
                assert opened.status_code == 200, opened.text
                assert opened.json()["report"] is not None
                assert opened.json()["recovery"]["provider_calls"] == 0
                assert opened.json()["recovery"]["canonical_c5_checkpoint_id"] is None
                assert opened.json()["version"] >= 1
                assert "failure_code" in opened.json()["recovery"]
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=setup.app),
                base_url=str(admin_settings.admin_app_url),
            ) as anonymous_admin:
                authentication_required = await anonymous_admin.get(endpoint + "/report")
                assert authentication_required.status_code == 401, authentication_required.text
        finally:
            await setup.engine.dispose()

    run(exercise())
