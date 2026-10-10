"""Private Coaching on disposable PostgreSQL; every call and quote is fictional."""

import hashlib
from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import func, select, update

from ac_platform.audit.models import AuditEvent
from ac_platform.coaching.http import install_coaching_http
from ac_platform.conversation_intelligence.acquisition_reports import AcquisitionReports
from ac_platform.conversation_intelligence.checkpoints import build_checkpoint, content_hash
from ac_platform.conversation_intelligence.guest_models import ConversationGuestSubmission
from ac_platform.conversation_intelligence.guest_ownership import GuestOwnership
from ac_platform.conversation_intelligence.inference import binding_for
from ac_platform.conversation_intelligence.models import (
    ConversationCheckpoint,
    ConversationPermission,
    ConversationRecording,
    ConversationReportDraft,
    ConversationRun,
)
from ac_platform.conversation_intelligence.report_store import PrivateProofReference
from ac_platform.conversation_intelligence.reports import load_report_profile, parse_report_draft
from ac_platform.conversation_intelligence.sensitive_segments_store import SensitiveSegmentsStore
from ac_platform.http.routes import RouteContext
from ac_platform.outbox.models import Job
from ac_platform.tenancy.models import Membership
from tests.conversation_overview_fixtures import overview_for
from tests.database.test_conversation_account_library_postgresql import _session
from tests.database.test_conversation_postgresql import postgres_harness as _postgres_harness
from tests.database.test_conversation_postgresql import run, seed
from tests.database.test_conversation_submission_http_postgresql import ORIGIN, _setup
from tests.database.test_prospect_store_postgresql import direct_call
from tests.unit.conversation_intelligence.test_reports import _payload, _transcript

PATH = "/v1/me/coaching"


@pytest.fixture
def postgres_harness() -> Any:
    yield from cast(Any, _postgres_harness).__wrapped__()


def install(setup: Any) -> None:
    install_coaching_http(
        setup.app, RouteContext(setup.settings, setup.require_actor, setup.sessions)
    )


async def draft_for(setup: Any, submission: UUID) -> tuple[UUID, str]:
    """A valid private legacy draft, intentionally not linked to other evaluators."""
    async with setup.sessions() as db, db.begin():
        link = await db.scalar(
            select(ConversationGuestSubmission).where(
                ConversationGuestSubmission.submission_id == submission
            )
        )
        recording = await db.get(ConversationRecording, link.recording_id)
        current_run = await db.scalar(
            select(ConversationRun).where(ConversationRun.recording_id == recording.id)
        )
        if current_run is None:
            job = Job(kind="fictional.coaching.receipt", dedupe_key=str(uuid4()), payload={})
            db.add(job)
            await db.flush()
            current_run = ConversationRun(
                id=uuid4(),
                tenant_id=recording.tenant_id,
                person_id=recording.person_id,
                recording_id=recording.id,
                request_key=str(uuid4()),
                intent_sha256="a" * 64,
                recipe_revision="fictional-private-import-v1",
                generation=recording.generation,
                state="completed",
                job_id=job.id,
                created_at=setup.clock[0],
            )
            db.add(current_run)
            await db.flush()
        current_run.state = "completed"
        current_run.completed_at = setup.clock[0]
        native = '{"text":"Fictional line: the buyer asks about price and timing."}'
        revision = hashlib.sha256(native.encode()).hexdigest()
        normalized = _transcript(count=1)
        normalized.update(source_sha256=recording.source_sha256, revision=revision)
        profile = load_report_profile()
        payload = _payload(normalized)
        payload["overview"] = overview_for(payload)
        payload["dimensions"] = [
            {
                "dimension_id": row["id"],
                "status": "observed" if row["id"] == "problem_impact_desire" else "unknown",
                "observation": "The fictional barrier remains unclear.",
                "evidence": payload["improvements"][0]["evidence"]
                if row["id"] == "problem_impact_desire"
                else [],
            }
            for row in profile["dimensions"]
        ]
        # This inspected private draft explicitly retains source-bound dimension
        # evidence. Ordinary old v4 outputs omit it and cannot establish a focus.
        report = parse_report_draft(payload, normalized, canonical_read=True).model_dump(
            mode="json"
        )
        transcript = {"native_json": native, "normalized": normalized}
        receipt = PrivateProofReference(
            schema_id="ac.sales-xray.private-proof-reference/1",
            approval_receipt_sha256="a" * 64,
            transcription_response_sha256=revision,
            generation_receipt_sha256="b" * 64,
            source_review_receipt_sha256="c" * 64,
            new_provider_calls=0,
        ).model_dump(mode="json")
        db.add(
            ConversationReportDraft(
                id=uuid4(),
                tenant_id=recording.tenant_id,
                person_id=recording.person_id,
                recording_id=recording.id,
                run_id=current_run.id,
                source_revision=recording.source_revision,
                source_sha256=recording.source_sha256,
                report_sha256=content_hash(report),
                transcript_sha256=content_hash(transcript),
                profile_sha256=content_hash(profile),
                evidence_receipt_sha256=content_hash(receipt),
                payload=report,
                transcript=transcript,
                evidence_receipt=receipt,
                created_at=setup.clock[0],
            )
        )
        c0 = build_checkpoint(
            binding_for(recording), "C0", "fictional-v1", {}, [], content_hash({})
        )
        c2 = build_checkpoint(
            binding_for(recording), "C2", "fictional-v1", {}, [c0], content_hash(normalized)
        )
        db.add(
            ConversationCheckpoint(
                id=uuid4(),
                tenant_id=recording.tenant_id,
                person_id=recording.person_id,
                recording_id=recording.id,
                stage="C2",
                cache_key=c2.cache_key,
                manifest_sha256=c2.manifest_sha256,
                payload_sha256=c2.payload_sha256,
                feature_blob_id=None,
                manifest=c2.as_dict(),
                payload=normalized,
                created_at=setup.clock[0],
            )
        )
        return recording.id, revision


def test_coaching_cookie_host_selector_and_read_only_empty_state(
    postgres_harness: Any, tmp_path: Path
) -> None:
    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path)
        install(setup)
        try:
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=setup.app), base_url=ORIGIN
            ) as client:
                assert (await client.get(PATH)).status_code == 401
                client.cookies.set(setup.settings.session_cookie_name, setup.token)
                async with setup.sessions() as db:
                    before = (
                        await db.scalar(select(func.count()).select_from(Job)),
                        await db.scalar(select(func.count()).select_from(AuditEvent)),
                    )
                response = await client.get(PATH)
                assert response.status_code == 200, response.text
                assert response.headers["cache-control"] == "private, no-store"
                assert response.headers["vary"] == "Cookie"
                data = response.json()
                assert data["person_id"] == str(setup.state.person_id)
                assert data["state"] == "not_enough_evidence" and data["focus"] is None
                assert data["entitlement"] == "coaching" and data["analysed_calls"] == 0
                assert data["mastery"]["correct_count"] is None
                assert (
                    await client.get(PATH, params={"person_id": str(uuid4())})
                ).status_code == 422
                assert (await client.get("https://admin.example.test" + PATH)).status_code == 404
                async with setup.sessions() as db:
                    assert before == (
                        await db.scalar(select(func.count()).select_from(Job)),
                        await db.scalar(select(func.count()).select_from(AuditEvent)),
                    )
                    await db.execute(
                        update(Membership)
                        .where(Membership.person_id == setup.state.person_id)
                        .values(status="inactive", ended_at=setup.clock[0])
                    )
                    await db.commit()
                assert (await client.get(PATH)).status_code in (401, 403)
        finally:
            await setup.engine.dispose()

    run(exercise())


def test_coaching_own_report_withholding_and_revocation(
    postgres_harness: Any, tmp_path: Path
) -> None:
    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path)
        install(setup)
        try:
            call = await direct_call(setup)
            recording_id, revision = await draft_for(setup, call)
            async with setup.sessions() as db, db.begin():
                await AcquisitionReports(GuestOwnership(setup.factory(db))).report(
                    call, actor=setup.state.actor
                )
            stranger = await seed(setup.engine, tenant_id=setup.state.tenant_id, role="admin")
            other_token = await _session(setup, stranger)
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=setup.app), base_url=ORIGIN
            ) as client:
                client.cookies.set(setup.settings.session_cookie_name, other_token)
                other = (await client.get(PATH)).json()
                assert other["analysed_calls"] == 0 and other["evidence"] == []
                client.cookies.set(setup.settings.session_cookie_name, setup.token)
                result = await client.get(PATH)
                assert result.status_code == 200, result.text
                data = result.json()
                assert data["state"] == "ready" and data["analysed_calls"] == 1, data
                assert data["focus"]["skill_id"] == "problem_impact_desire"
                assert data["evidence"][0]["submission_id"] == str(call)
                assert data["mastery"]["state"] == "not_enough_evidence"
                assert data["mission"]["behavior"] == "Ask before presenting."
                async with setup.sessions() as db, db.begin():
                    await SensitiveSegmentsStore(db).mark(
                        setup.state.actor,
                        recording_id=recording_id,
                        transcript_revision=revision,
                        segments=[("s1", "SENSITIVE_FINANCIAL")],
                        reason_ref="AUT-1678",
                        idempotency_key="fictional-coaching-sensitive",
                    )
                withheld = (await client.get(PATH)).json()
                assert withheld["focus"] is None and withheld["evidence"] == []
                assert "buyer asks" not in str(withheld)
                async with setup.sessions() as db, db.begin():
                    recording = await db.get(ConversationRecording, recording_id)
                    permission = await db.get(ConversationPermission, recording.permission_id)
                    permission.revoked_at = setup.clock[0]
                revoked = (await client.get(PATH)).json()
                assert revoked["analysed_calls"] == 0 and revoked["evidence"] == []
        finally:
            await setup.engine.dispose()

    run(exercise())
