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
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

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
from ac_platform.conversation_intelligence.entitlements import ExecutionPermission, Quote
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
from ac_platform.identity.models import Person
from ac_platform.kernel.authz import ActorContext
from ac_platform.outbox.models import Job
from ac_platform.outbox.repository import canonical_receipt_digest
from ac_platform.tenancy.models import Membership
from tests.database.test_conversation_postgresql import (
    run,
)
from tests.database.test_conversation_worker_postgresql import _prepare

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
                version = await database.scalar(
                    select(ConversationRetainedC5Version).where(
                        ConversationRetainedC5Version.run_id == case["run_id"]
                    )
                )
                assert version is not None
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
                version = await database.get(ConversationRetainedC5Version, corrected["id"])
                assert (
                    version is not None
                    and version.payload is None
                    and version.erased_at is not None
                )
                assert version.original_raw_sha256 == case["raw_sha256"]
        finally:
            await engine.dispose()

    run(exercise())
