"""Append-only wording repair, current-owner gate, atomic rollback and normal reads."""

import asyncio
from copy import deepcopy
from datetime import timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from ac_platform.audit.models import AuditEvent
from ac_platform.audit.service import verify_audit_chain
from ac_platform.coaching.sandbox import SandboxCoaching
from ac_platform.conversation_intelligence.acquisition_models import (
    ConversationAcquisitionSettlement,
)
from ac_platform.conversation_intelligence.acquisition_reports import AcquisitionReports
from ac_platform.conversation_intelligence.acquisition_sessions import AcquisitionSessions
from ac_platform.conversation_intelligence.checkpoints import content_hash
from ac_platform.conversation_intelligence.guest_ownership import GuestOwnership
from ac_platform.conversation_intelligence.models import ConversationReportDraft
from ac_platform.conversation_intelligence.prospect_call_outcome_models import (
    ConversationCallOutcomeRevision,
)
from ac_platform.conversation_intelligence.synthetic_import_models import (
    ConversationSyntheticRecord,
)
from ac_platform.outbox.models import Job
from ac_platform.tenancy.models import Membership, Organisation, Tenant
from tests.database.test_conversation_postgresql import postgres_harness as _postgres_harness
from tests.database.test_conversation_postgresql import run, seed
from tests.unit.conversation_intelligence.test_dev_sandbox_summary_repair import (
    fixture_plan,
    repair,
    summary_bundle,
)


@pytest.fixture(scope="module")
def postgres_harness():
    yield from _postgres_harness.__wrapped__()


def test_supersession_guards_rollback_replay_and_connected_reads(postgres_harness, monkeypatch):
    async def scenario():
        module, source = repair(), summary_bundle()
        loader = module.loader
        proposal, candidates = fixture_plan(module, monkeypatch, [source])
        key = source.metadata["call_id"]
        old_id = loader.identifier("report", key)
        new_id = loader.identifier(module.POLICY, key)
        submission = loader.identifier("submission", key)
        monkeypatch.setattr(loader, "EXPECTED_BUNDLES", 1)
        monkeypatch.setattr(loader, "bundles", lambda _root: iter([source]))
        monkeypatch.setattr(
            loader,
            "representatives",
            lambda _root: [
                {
                    "synthetic": True,
                    "synthetic_identity": True,
                    "person_id": "syn-fixture-R1",
                    "fields": {
                        "email": "rep1@example.invalid",
                        "name": "Synthetic Rep 1",
                        "joined_on": "2017-01-01",
                    },
                }
            ],
        )
        monkeypatch.setattr(
            loader,
            "read_json",
            lambda _root, path, **_kwargs: (
                {"synthetic": True, "start": "2017-01-01"}
                if path == "simulation/config.json"
                else {"synthetic": True, "fictional": True, "business_id": "syn-fixture"}
            ),
        )
        engine = create_async_engine(postgres_harness.url, hide_parameters=True)
        try:
            async with AsyncSession(engine) as db, db.begin():
                db.add(Tenant(id=loader.TARGET, name="AC Sandbox", slug="ac-sandbox"))
            owner = await seed(engine, tenant_id=loader.TARGET, role="owner")
            async with AsyncSession(engine) as db, db.begin():
                db.add(
                    Organisation(
                        tenant_id=loader.TARGET,
                        created_by_person_id=owner.person_id,
                        creation_command_id=uuid4(),
                        domain_verification_token="x" * 43,
                    )
                )
            async with AsyncSession(engine) as db, db.begin():
                await loader.load(
                    db,
                    root=Path("fictional"),
                    approver=owner.person_id,
                    approval="fictional original load",
                    apply=True,
                )
            outcome_id = uuid4()
            async with AsyncSession(engine) as db, db.begin():
                db.add(
                    ConversationCallOutcomeRevision(
                        id=outcome_id,
                        tenant_id=loader.TARGET,
                        submission_id=submission,
                        revision=1,
                        outcome="won",
                        set_by_person_id=loader.identifier("person", "syn-fixture-R1"),
                        created_at=owner.now,
                    )
                )
                old = await db.get(ConversationReportDraft, old_id)
                old_payload, old_transcript, old_proof = (
                    deepcopy(old.payload),
                    deepcopy(old.transcript),
                    deepcopy(old.evidence_receipt),
                )
                audits_before = await db.scalar(select(func.count()).select_from(AuditEvent))

            async def apply(*, live_apply=True, expected=proposal["plan_sha256"]):
                async with AsyncSession(engine) as db, db.begin():
                    return await module.supersede(
                        db,
                        proposal,
                        candidates,
                        approver=owner.person_id,
                        approval="fictional separate wording approval",
                        apply=live_apply,
                        expected_plan_sha256=expected,
                    )

            preview = await apply(live_apply=False)
            assert not preview["applied"] and preview["reports_superseded"] == 1
            async with AsyncSession(engine) as db:
                assert await db.get(ConversationReportDraft, new_id) is None
                assert (
                    await db.scalar(select(func.count()).select_from(AuditEvent)) == audits_before
                )
            with pytest.raises(ValueError, match="exact previously reviewed plan"):
                await apply(expected="f" * 64)
            for altered in ("draft", "source"):
                # Simulate a corrupt/stale read in the identity map. The database itself
                # forbids rewriting these rows, so no altered fixture is flushed.
                with pytest.raises(ValueError, match="intact original synthetic"):
                    async with AsyncSession(engine) as db, db.begin():
                        if altered == "draft":
                            row = await db.get(ConversationReportDraft, old_id)
                            row.payload = {**row.payload, "summary": "Changed by a later reviewer."}
                            row.report_sha256 = content_hash(row.payload)
                        else:
                            row = await db.get(
                                ConversationSyntheticRecord, (loader.TARGET, "call", key, 1)
                            )
                            row.payload = {**row.payload, "new_authored_note": "Changed source."}
                            row.payload_sha256 = content_hash(row.payload)
                        with db.no_autoflush:
                            await module.supersede(
                                db,
                                proposal,
                                candidates,
                                approver=owner.person_id,
                                approval="fictional separate wording approval",
                                apply=False,
                            )
            async with AsyncSession(engine) as db, db.begin():
                await db.execute(
                    update(Membership)
                    .where(
                        Membership.tenant_id == loader.TARGET,
                        Membership.person_id == owner.person_id,
                    )
                    .values(role="member")
                )
            with pytest.raises(ValueError, match="current approving owner"):
                await apply()
            async with AsyncSession(engine) as db, db.begin():
                await db.execute(
                    update(Membership)
                    .where(
                        Membership.tenant_id == loader.TARGET,
                        Membership.person_id == owner.person_id,
                    )
                    .values(role="owner")
                )

            original_append = module.AuditRepository.append

            async def fail_audit(*_args, **_kwargs):
                raise RuntimeError("fictional audit failure")

            monkeypatch.setattr(module.AuditRepository, "append", fail_audit)
            with pytest.raises(RuntimeError, match="audit failure"):
                await apply()
            monkeypatch.setattr(module.AuditRepository, "append", original_append)
            async with AsyncSession(engine) as db:
                assert await db.get(ConversationReportDraft, new_id) is None
                assert (
                    await db.scalar(select(func.count()).select_from(AuditEvent)) == audits_before
                )

            first, replay = await asyncio.gather(apply(), apply())
            assert sorted([first["reports_superseded"], replay["reports_superseded"]]) == [0, 1]
            async with AsyncSession(engine) as db, db.begin():
                old, new = (
                    await db.get(ConversationReportDraft, old_id),
                    await db.get(ConversationReportDraft, new_id),
                )
                assert (old.payload, old.transcript, old.evidence_receipt) == (
                    old_payload,
                    old_transcript,
                    old_proof,
                )
                assert (
                    new.transcript == old.transcript
                    and new.evidence_receipt == old.evidence_receipt
                )
                assert (
                    await db.scalar(select(func.count()).select_from(ConversationReportDraft)) == 2
                )
                assert (
                    await db.scalar(
                        select(func.count()).select_from(ConversationCallOutcomeRevision)
                    )
                    == 1
                )
                outcome = await db.get(ConversationCallOutcomeRevision, outcome_id)
                assert outcome.outcome == "won" and outcome.revision == 1
                preserved = await db.get(
                    ConversationSyntheticRecord, (loader.TARGET, "call", key, 1)
                )
                assert preserved.payload == source.model_dump(mode="json", by_alias=True)
                assert (
                    await db.scalar(select(func.count()).select_from(AuditEvent))
                    == audits_before + 1
                )
                event = await db.scalar(
                    select(AuditEvent).where(
                        AuditEvent.action == "conversation.synthetic_dev_summary_superseded"
                    )
                )
                assert event.actor_person_id == owner.person_id
                assert event.payload["reports"] == proposal["reports"]
                assert (await verify_audit_chain(db, loader.TARGET)).valid
                ownership = GuestOwnership(
                    AcquisitionSessions(
                        db,
                        tenant_id=loader.TARGET,
                        policy_revision="fictional-dev-1",
                        clock=lambda: owner.now + timedelta(minutes=1),
                    )
                )
                reader = AcquisitionReports(ownership)
                report = await reader.report(
                    submission, actor=owner.actor, allow_organisation_read=True
                )
                assert report["report"]["content"]["summary"] == candidates[0][2]["summary"]
                assert (
                    report["report"]["content"]["pillars"]["summary"]
                    == candidates[0][2]["pillars"]["summary"]
                )
                assert (
                    await reader.progress(
                        submission, actor=owner.actor, allow_organisation_read=True
                    )
                )["run_state"] == "done"
                coaching = await SandboxCoaching(db, loader.TARGET).read_call(
                    owner.person_id, submission
                )
                assert (
                    coaching.mission.behavior == source.coaching["action"]["mission"]["behaviour"]
                )
                assert coaching.lesson.own_call.quote == source.transcript["lines"][0]["text"]
                assert (
                    await db.scalar(
                        select(func.sum(ConversationAcquisitionSettlement.charged_seconds))
                    )
                    == 0
                )
                assert (await db.scalars(select(Job.status))).all() == ["succeeded"]
                # An independently added later draft must never be covered by this repair.
                db.add(
                    ConversationReportDraft(
                        id=uuid4(),
                        tenant_id=new.tenant_id,
                        person_id=new.person_id,
                        recording_id=new.recording_id,
                        run_id=new.run_id,
                        source_revision=new.source_revision,
                        source_sha256=new.source_sha256,
                        report_sha256=content_hash(
                            {**new.payload, "summary": "Later reviewed summary."}
                        ),
                        transcript_sha256=new.transcript_sha256,
                        profile_sha256=new.profile_sha256,
                        evidence_receipt_sha256=new.evidence_receipt_sha256,
                        payload={**new.payload, "summary": "Later reviewed summary."},
                        transcript=new.transcript,
                        evidence_receipt=new.evidence_receipt,
                        created_at=new.created_at + timedelta(seconds=1),
                    )
                )
            with pytest.raises(ValueError, match="later run or report"):
                await apply()
        finally:
            await engine.dispose()

    run(scenario())
