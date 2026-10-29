"""Owner-approved exact deletion against disposable PostgreSQL, no hosted providers."""

from __future__ import annotations

import importlib.util
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select

from ac_platform.audit.models import AuditEvent
from ac_platform.conversation_intelligence.acquisition_models import ConversationAcquisitionUsage
from ac_platform.conversation_intelligence.models import (
    ConversationPermission,
    ConversationRecording,
    ConversationReportDraft,
    ConversationRun,
)
from ac_platform.conversation_intelligence.storage import PrivateLocalRecordingStorage
from ac_platform.lead_desk.models import Lead, LeadEvent
from ac_platform.outbox.repository import JobRepository
from tests.database.conversation_harness import conversation_harness
from tests.database.test_conversation_postgresql import run, seed
from tests.database.test_lead_os_acceptance_postgresql import ROOT, world

SPEC = importlib.util.spec_from_file_location(
    "ac_test_delete", ROOT / "scripts/data-changes/ac-test-data-delete.py"
)
assert SPEC and SPEC.loader
tool = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(tool)


@pytest.fixture(scope="module")
def postgres_harness():
    yield from conversation_harness(ROOT)


async def fixtures(here, tmp_path):
    state = here.setup.state
    sessions = here.setup.sessions
    lead = UUID(await here.add("Synthetic delete fixture", "+15555550101"))
    real_lead = UUID(await here.add("Synthetic retained fixture", "+15555550102"))
    ids = {k: set() for k in tool.KINDS}
    ids["test_lead"].add(lead)
    recording_id, report_id, run_id, usage_id, submission_id = [uuid4() for _ in range(5)]
    ids["recording"].add(recording_id)
    ids["report_draft"].add(report_id)
    ids["submission"].add(submission_id)
    async with sessions() as db, db.begin():
        permission = await db.get(ConversationPermission, state.permission_id)
        assert permission is not None
        recording = ConversationRecording(
            id=recording_id,
            tenant_id=state.tenant_id,
            person_id=state.person_id,
            permission_id=state.permission_id,
            request_key=str(uuid4()),
            intent_sha256="a" * 64,
            source_sha256=state.source_sha256,
            source_bytes=1024,
            content_type="audio/wav",
            source_revision=1,
            generation=1,
            state="ready",
            created_at=state.now,
        )
        db.add(recording)
        db.add(
            ConversationAcquisitionUsage(
                id=usage_id,
                tenant_id=state.tenant_id,
                person_id=state.person_id,
                submission_id=submission_id,
                source_sha256=state.source_sha256,
                duration_evidence_sha256="b" * 64,
                reserved_seconds=60,
                policy_revision="fixture",
                created_at=state.now,
            )
        )
        await db.flush()
        job = await JobRepository(db).enqueue(
            kind="conversation.fixture",
            dedupe_key=str(uuid4()),
            tenant_id=state.tenant_id,
            payload={"recording_id": str(recording_id)},
            external_side_effect=False,
        )
        db.add(
            ConversationRun(
                id=run_id,
                tenant_id=state.tenant_id,
                person_id=state.person_id,
                recording_id=recording_id,
                request_key=str(uuid4()),
                intent_sha256="a" * 64,
                recipe_revision="fixture",
                generation=1,
                state="completed",
                job_id=job.id,
                created_at=state.now,
            )
        )
        await db.flush()
        db.add(
            ConversationReportDraft(
                id=report_id,
                tenant_id=state.tenant_id,
                person_id=state.person_id,
                recording_id=recording_id,
                run_id=run_id,
                source_revision=1,
                source_sha256=state.source_sha256,
                report_sha256="a" * 64,
                transcript_sha256="a" * 64,
                profile_sha256="a" * 64,
                evidence_receipt_sha256="a" * 64,
                payload={"synthetic": True},
                transcript={"synthetic": True},
                evidence_receipt={"synthetic": True},
                created_at=state.now,
            )
        )
    return ids, real_lead, PrivateLocalRecordingStorage(tmp_path / "erase-objects")


@pytest.mark.parametrize("mismatch", ["tenant", "person"])
def test_refuses_wrong_boundary_before_any_effect(postgres_harness, tmp_path, mismatch):
    async def exercise():
        async with world(postgres_harness, tmp_path) as here:
            ids, real_lead, storage = await fixtures(here, tmp_path)
            other = await seed(here.setup.engine)
            options = dict(tenant=here.tenant_id, person=here.setup.state.person_id)
            options[mismatch] = getattr(other, f"{mismatch}_id")
            with pytest.raises(ValueError, match=f"refused_{mismatch}"):
                await tool.execute(here.setup.sessions, ids, apply=True, storage=storage, **options)
            async with here.setup.sessions() as db:
                row = await db.get(ConversationRecording, next(iter(ids["recording"])))
                assert row.state == "ready"
                assert await db.get(Lead, real_lead) is not None
                assert not await db.scalar(
                    select(AuditEvent.id).where(AuditEvent.action == tool.ACTION)
                )

    run(exercise())


def test_dry_apply_replay_preserves_real_and_usage_consent_audit(postgres_harness, tmp_path):
    async def exercise():
        async with world(postgres_harness, tmp_path) as here:
            ids, real_lead, storage = await fixtures(here, tmp_path)
            state = here.setup.state
            options = dict(tenant=here.tenant_id, person=state.person_id, storage=storage)
            async with here.setup.sessions() as db:
                audit_before = await db.scalar(select(func.count()).select_from(AuditEvent))
                permission_before = await db.get(ConversationPermission, state.permission_id)
                consent_expiry = permission_before.expires_at
            dry = await tool.execute(here.setup.sessions, ids, **options)
            assert dry["before"] == dry["after"]
            done = await tool.execute(here.setup.sessions, ids, apply=True, **options)
            assert done["after"] == dict(recording=0, report_draft=0, submission=1, test_lead=0)
            async with here.setup.sessions() as db:
                assert await db.get(Lead, real_lead) is not None
                assert await db.get(Lead, next(iter(ids["test_lead"]))) is None
                assert (
                    await db.get(ConversationRecording, next(iter(ids["recording"])))
                ).state == "deleted"
                draft = await db.get(ConversationReportDraft, next(iter(ids["report_draft"])))
                assert draft.erased_at and draft.payload is None and draft.transcript is None
                assert (
                    await db.scalar(select(func.count()).select_from(ConversationAcquisitionUsage))
                    == 1
                )
                assert (
                    await db.get(ConversationPermission, state.permission_id)
                ).expires_at == consent_expiry
                audit_after = await db.scalar(select(func.count()).select_from(AuditEvent))
                assert audit_after > audit_before
                assert (
                    await db.scalar(
                        select(func.count())
                        .select_from(AuditEvent)
                        .where(AuditEvent.action == tool.ACTION)
                    )
                    == 1
                )
            replay = await tool.execute(here.setup.sessions, ids, apply=True, **options)
            assert replay["before"] == replay["after"] == done["after"]
            async with here.setup.sessions() as db:
                assert await db.scalar(select(func.count()).select_from(AuditEvent)) == audit_after

    run(exercise())


def test_refuses_call_event_and_unlisted_report(postgres_harness, tmp_path):
    async def exercise():
        async with world(postgres_harness, tmp_path) as here:
            ids, _, storage = await fixtures(here, tmp_path)
            async with here.setup.sessions() as db, db.begin():
                db.add(
                    LeadEvent(
                        id=uuid4(),
                        tenant_id=here.tenant_id,
                        lead_id=next(iter(ids["test_lead"])),
                        kind="call",
                        actor_person_id=here.setup.state.person_id,
                        data={"submission_id": str(uuid4())},
                        created_at=here.setup.state.now,
                    )
                )
            with pytest.raises(ValueError, match="refused_call_event"):
                await tool.execute(
                    here.setup.sessions,
                    ids,
                    apply=True,
                    storage=storage,
                    tenant=here.tenant_id,
                    person=here.setup.state.person_id,
                )
            ids["report_draft"].clear()
            with pytest.raises(ValueError, match="refused_unlisted_report"):
                await tool.execute(
                    here.setup.sessions,
                    ids,
                    apply=True,
                    storage=storage,
                    tenant=here.tenant_id,
                    person=here.setup.state.person_id,
                )

    run(exercise())


def test_manifest_is_exact(tmp_path):
    bad = tmp_path / "ids.txt"
    bad.write_text(f"recording|{uuid4()}|f84c7afb|ready|2026-10-15\n")
    with pytest.raises(ValueError, match="refused_manifest"):
        tool.load_manifest(bad)
