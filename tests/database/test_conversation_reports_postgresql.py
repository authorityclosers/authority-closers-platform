"""Disposable-loopback PostgreSQL proof for private report draft persistence.

The fixture reuses the real local worker preparation and ``run_once`` path so a
report can only be imported after a source-bound C1 checkpoint exists. Native
Scribe JSON and WAV bytes are synthetic; no provider transport is called.
"""

from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from ac_platform.audit.models import AuditEvent
from ac_platform.conversation_intelligence.application import (
    ConversationApplication,
    ConversationDenied,
    ConversationError,
    ConversationNotFound,
)
from ac_platform.conversation_intelligence.models import (
    ConversationPermission,
    ConversationRecording,
    ConversationReportDraft,
    ConversationRun,
)
from ac_platform.conversation_intelligence.report_store import (
    ConversationReports,
    PrivateDraftIntent,
    PrivateProofReference,
)
from ac_platform.identity.models import Person
from ac_platform.identity.models import Session as IdentitySession
from ac_platform.kernel.authz import ActorContext
from ac_platform.tenancy.models import Membership, Tenant
from tests.database.test_conversation_postgresql import (
    postgres_harness as _postgres_harness,
)
from tests.database.test_conversation_postgresql import (
    run,
    seed,
)
from tests.database.test_conversation_worker_postgresql import (
    Prepared as WorkerPrepared,
)
from tests.database.test_conversation_worker_postgresql import (
    _prepare as prepare_worker,
)


@pytest.fixture(scope="module")
def postgres_harness() -> Any:
    yield from _postgres_harness.__wrapped__()  # type: ignore[attr-defined]


@dataclass(frozen=True)
class ReportFixture:
    prepared: WorkerPrepared
    actor: ActorContext
    intent: PrivateDraftIntent


def _reports(database: AsyncSession, fixture: ReportFixture) -> ConversationReports:
    return ConversationReports(
        ConversationApplication(database, clock=lambda: fixture.prepared.state.now)
    )


def _report_payload() -> dict[str, Any]:
    evidence = {
        "segment_id": "s1",
        "quote": "Hello buyer",
        "start_ms": 0,
        "end_ms": 900,
    }
    finding = {
        "title": "Clarify the stated barrier",
        "explanation": "The line provides an observable source-bound conversation fact.",
        "evidence": [evidence],
    }
    return {
        "summary": "A synthetic qualitative draft for human review.",
        "strengths": [copy.deepcopy(finding)],
        "missed_opportunities": [copy.deepcopy(finding)],
        "improvements": [copy.deepcopy(finding)],
        "objection_analysis": [copy.deepcopy(finding)],
        "closing_analysis": [copy.deepcopy(finding)],
        "verdict": "Qualitative draft only; no official score is assigned.",
        "review_status": "draft_not_dipak_adjudicated",
    }


def _intent(source_sha256: str) -> PrivateDraftIntent:
    native = {
        "text": "Hello buyer",
        "words": [
            {"text": "Hello", "start": 0.0, "end": 0.4, "speaker_id": "speaker_1"},
            {"text": "buyer", "start": 0.5, "end": 0.9, "speaker_id": "speaker_1"},
        ],
    }
    raw = json.dumps(native, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    transcription_hash = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    return PrivateDraftIntent(
        raw_transcription_json=raw,
        report=_report_payload(),
        receipt=PrivateProofReference(
            schema_id="ac.sales-xray.private-proof-reference/1",
            approval_receipt_sha256="a" * 64,
            transcription_response_sha256=transcription_hash,
            generation_receipt_sha256="b" * 64,
            source_review_receipt_sha256="c" * 64,
            new_provider_calls=0,
        ),
    )


async def _promote_worker_actor(engine: Any, prepared: WorkerPrepared) -> ActorContext:
    async with AsyncSession(engine) as database, database.begin():
        person = await database.get(Person, prepared.state.person_id)
        assert person is not None
        # Each harness owns a separate disposable schema. The current contract
        # requires the exact verified control account as well as an admin role.
        person.email = "admin@authorityclosers.com"
        person.email_verified_at = prepared.state.now
        membership = await database.scalar(
            select(Membership).where(
                Membership.tenant_id == prepared.state.tenant_id,
                Membership.person_id == prepared.state.person_id,
            )
        )
        assert membership is not None
        membership.role = "admin"
    return ActorContext(
        prepared.state.person_id,
        prepared.state.session_id,
        prepared.state.tenant_id,
        frozenset({"admin_surface"}),
    )


async def _build_fixture(postgres_harness: Any, scratch_root: Path) -> ReportFixture:
    prepared = await prepare_worker(postgres_harness, scratch_root)
    assert await prepared.worker.run_once()
    engine = create_async_engine(postgres_harness.url)
    try:
        actor = await _promote_worker_actor(engine, prepared)
        return ReportFixture(prepared, actor, _intent(prepared.state.source_sha256))
    finally:
        await engine.dispose()


@pytest.fixture(scope="module")
def report_fixture(
    postgres_harness: Any, tmp_path_factory: pytest.TempPathFactory
) -> ReportFixture:
    return run(_build_fixture(postgres_harness, tmp_path_factory.mktemp("conversation-report")))


async def _report_count(sessions: async_sessionmaker[AsyncSession], fixture: ReportFixture) -> int:
    async with sessions() as database:
        return int(
            await database.scalar(
                select(func.count())
                .select_from(ConversationReportDraft)
                .where(ConversationReportDraft.run_id == fixture.prepared.run_id)
            )
        )


async def _import_valid(
    fixture: ReportFixture,
    sessions: async_sessionmaker[AsyncSession],
    *,
    key: str = "report-import-valid",
) -> dict[str, Any]:
    async with sessions() as database, database.begin():
        return await _reports(database, fixture).import_internal_draft(
            fixture.actor,
            fixture.prepared.run_id,
            fixture.intent,
            storage=fixture.prepared.storage,
            key=key,
        )


def test_source_bound_report_import_read_and_replay(
    postgres_harness: Any, report_fixture: ReportFixture
) -> None:
    async def exercise() -> None:
        engine = create_async_engine(postgres_harness.url)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        try:
            first = await _import_valid(report_fixture, sessions)
            assert first["state"] == "completed"
            assert first["provider_calls"] == 0
            report = first["report"]
            assert report is not None
            assert report["source_sha256"] == report_fixture.prepared.state.source_sha256
            assert (
                report["transcript_revision"]
                == report_fixture.intent.receipt.transcription_response_sha256
            )
            assert report["source_label"] == "Your sales call"
            before = await _report_count(sessions, report_fixture)
            replay = await _import_valid(report_fixture, sessions)
            assert replay == first
            assert await _report_count(sessions, report_fixture) == before == 1
            async with sessions() as database:
                draft = await database.scalar(
                    select(ConversationReportDraft).where(
                        ConversationReportDraft.run_id == report_fixture.prepared.run_id
                    )
                )
                assert draft is not None
                assert draft.payload is not None
                assert draft.transcript is not None
                assert draft.evidence_receipt is not None
                assert draft.source_sha256 == report_fixture.prepared.state.source_sha256
                run_row = await database.get(ConversationRun, report_fixture.prepared.run_id)
                assert run_row is not None and run_row.state == "completed"
        finally:
            await engine.dispose()

    run(exercise())


def test_forged_native_hash_quote_and_timing_are_rejected(
    postgres_harness: Any, report_fixture: ReportFixture
) -> None:
    async def exercise() -> None:
        engine = create_async_engine(postgres_harness.url)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        try:
            before = await _report_count(sessions, report_fixture)
            bad_receipt = report_fixture.intent.model_copy(
                update={
                    "receipt": report_fixture.intent.receipt.model_copy(
                        update={"transcription_response_sha256": "d" * 64}
                    )
                }
            )
            with pytest.raises(ConversationError, match="does not match its receipt"):
                async with sessions() as database, database.begin():
                    await _reports(database, report_fixture).import_internal_draft(
                        report_fixture.actor,
                        report_fixture.prepared.run_id,
                        bad_receipt,
                        storage=report_fixture.prepared.storage,
                        key="report-forged-native-hash",
                    )

            bad_quote_payload = copy.deepcopy(report_fixture.intent.report)
            bad_quote_payload["strengths"][0]["evidence"][0]["quote"] = "Forged quote"
            bad_quote = report_fixture.intent.model_copy(update={"report": bad_quote_payload})
            with pytest.raises(ConversationError, match="draft or its exact transcript evidence"):
                async with sessions() as database, database.begin():
                    await _reports(database, report_fixture).import_internal_draft(
                        report_fixture.actor,
                        report_fixture.prepared.run_id,
                        bad_quote,
                        storage=report_fixture.prepared.storage,
                        key="report-forged-quote",
                    )

            native = json.loads(report_fixture.intent.raw_transcription_json)
            native["words"][1]["start"] = 2.2
            native["words"][1]["end"] = 2.4
            raw = json.dumps(native, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            bad_timing = report_fixture.intent.model_copy(
                update={
                    "raw_transcription_json": raw,
                    "receipt": report_fixture.intent.receipt.model_copy(
                        update={
                            "transcription_response_sha256": hashlib.sha256(
                                raw.encode("utf-8")
                            ).hexdigest()
                        }
                    ),
                }
            )
            with pytest.raises(ConversationError, match="draft or its exact transcript evidence"):
                async with sessions() as database, database.begin():
                    await _reports(database, report_fixture).import_internal_draft(
                        report_fixture.actor,
                        report_fixture.prepared.run_id,
                        bad_timing,
                        storage=report_fixture.prepared.storage,
                        key="report-forged-timing",
                    )
            assert await _report_count(sessions, report_fixture) == before
        finally:
            await engine.dispose()

    run(exercise())


async def _other_tenant_admin(engine: Any, fixture: ReportFixture) -> ActorContext:
    tenant_id, session_id = uuid4(), uuid4()
    now = fixture.prepared.state.now
    async with AsyncSession(engine) as database, database.begin():
        database.add(Tenant(id=tenant_id, slug=tenant_id.hex, name="Other report tenant"))
        database.add(
            Membership(
                tenant_id=tenant_id,
                person_id=fixture.prepared.state.person_id,
                role="owner",
            )
        )
        await database.flush()
        database.add(
            IdentitySession(
                id=session_id,
                person_id=fixture.prepared.state.person_id,
                selected_tenant_id=tenant_id,
                token_hash=session_id.bytes * 2,
                expires_at=now + timedelta(days=1),
            )
        )
    return ActorContext(
        fixture.prepared.state.person_id,
        session_id,
        tenant_id,
        frozenset({"admin_surface"}),
    )


def test_another_owner_and_tenant_cannot_read_or_import_source_bound_report(
    postgres_harness: Any, report_fixture: ReportFixture
) -> None:
    async def exercise() -> None:
        engine = create_async_engine(postgres_harness.url)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        try:
            await _import_valid(report_fixture, sessions)
            other = await seed(engine, role="owner")
            async with sessions() as database, database.begin():
                with pytest.raises(ConversationDenied):
                    await _reports(database, report_fixture).import_internal_draft(
                        other.actor,
                        report_fixture.prepared.run_id,
                        report_fixture.intent,
                        storage=report_fixture.prepared.storage,
                        key="report-other-owner",
                    )
            other_tenant = await _other_tenant_admin(engine, report_fixture)
            async with sessions() as database, database.begin():
                with pytest.raises(ConversationNotFound):
                    await _reports(database, report_fixture).get(
                        other_tenant, report_fixture.prepared.run_id
                    )
                with pytest.raises(ConversationNotFound):
                    await _reports(database, report_fixture).import_internal_draft(
                        other_tenant,
                        report_fixture.prepared.run_id,
                        report_fixture.intent,
                        storage=report_fixture.prepared.storage,
                        key="report-other-tenant",
                    )
        finally:
            await engine.dispose()

    run(exercise())


def test_revoked_recording_permission_denies_report_read(
    postgres_harness: Any, report_fixture: ReportFixture
) -> None:
    async def exercise() -> None:
        engine = create_async_engine(postgres_harness.url)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        try:
            await _import_valid(report_fixture, sessions)
            try:
                async with sessions() as database, database.begin():
                    await database.execute(
                        update(ConversationPermission)
                        .where(
                            ConversationPermission.id == report_fixture.prepared.state.permission_id
                        )
                        .values(revoked_at=datetime.now(UTC))
                    )
                async with sessions() as database, database.begin():
                    with pytest.raises(ConversationDenied, match="permission"):
                        await _reports(database, report_fixture).get(
                            report_fixture.actor, report_fixture.prepared.run_id
                        )
            finally:
                async with sessions() as database, database.begin():
                    await database.execute(
                        update(ConversationPermission)
                        .where(
                            ConversationPermission.id == report_fixture.prepared.state.permission_id
                        )
                        .values(revoked_at=None)
                    )
        finally:
            await engine.dispose()

    run(exercise())


def test_report_draft_update_and_delete_are_rejected(
    postgres_harness: Any, report_fixture: ReportFixture
) -> None:
    async def exercise() -> None:
        engine = create_async_engine(postgres_harness.url)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        try:
            await _import_valid(report_fixture, sessions)
            async with sessions() as database:
                draft = await database.scalar(
                    select(ConversationReportDraft).where(
                        ConversationReportDraft.run_id == report_fixture.prepared.run_id
                    )
                )
                assert draft is not None
                draft_id = draft.id
            with pytest.raises(DBAPIError):
                async with sessions() as database, database.begin():
                    await database.execute(
                        update(ConversationReportDraft)
                        .where(ConversationReportDraft.id == draft_id)
                        .values(report_sha256="0" * 64)
                    )
            with pytest.raises(DBAPIError):
                async with sessions() as database, database.begin():
                    await database.execute(
                        delete(ConversationReportDraft).where(
                            ConversationReportDraft.id == draft_id
                        )
                    )
            async with sessions() as database:
                draft = await database.get(ConversationReportDraft, draft_id)
                assert draft is not None and draft.payload is not None
        finally:
            await engine.dispose()

    run(exercise())


def test_worker_deletion_erases_report_content_and_preserves_audit(
    postgres_harness: Any, report_fixture: ReportFixture
) -> None:
    async def exercise() -> None:
        engine = create_async_engine(postgres_harness.url)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        try:
            await _import_valid(report_fixture, sessions)
            async with sessions() as database:
                before_audit = (
                    await database.scalars(
                        select(AuditEvent)
                        .where(AuditEvent.tenant_id == report_fixture.prepared.state.tenant_id)
                        .order_by(AuditEvent.sequence_no)
                    )
                ).all()
                assert any(
                    event.action == "conversation.import_private_draft" for event in before_audit
                )
            async with sessions() as database, database.begin():
                deleted = await ConversationApplication(
                    database, clock=lambda: report_fixture.prepared.state.now
                ).request_deletion(
                    report_fixture.actor,
                    report_fixture.prepared.recording_id,
                    key="report-delete-recording",
                )
                assert deleted["state"] == "deleting"
            assert await report_fixture.prepared.worker.run_once()
            assert (
                report_fixture.prepared.storage.list_recording(
                    report_fixture.prepared.state.tenant_id,
                    report_fixture.prepared.recording_id,
                )
                == ()
            )
            async with sessions() as database:
                draft = await database.scalar(
                    select(ConversationReportDraft).where(
                        ConversationReportDraft.run_id == report_fixture.prepared.run_id
                    )
                )
                assert draft is not None
                assert draft.erased_at is not None
                assert draft.payload is None
                assert draft.transcript is None
                assert draft.evidence_receipt is None
                recording = await database.get(
                    ConversationRecording, report_fixture.prepared.recording_id
                )
                assert recording is not None and recording.state == "deleted"
                events = (
                    await database.scalars(
                        select(AuditEvent)
                        .where(AuditEvent.tenant_id == report_fixture.prepared.state.tenant_id)
                        .order_by(AuditEvent.sequence_no)
                    )
                ).all()
                actions = [event.action for event in events]
                assert "conversation.import_private_draft" in actions
                assert "conversation.delete" in actions
                assert all(
                    "Hello buyer" not in json.dumps(event.payload, sort_keys=True)
                    for event in events
                )
        finally:
            await engine.dispose()

    run(exercise())
