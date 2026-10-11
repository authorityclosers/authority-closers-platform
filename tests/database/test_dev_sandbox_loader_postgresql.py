"""Normal library/report/coaching reads, atomic rollback and zero-charge sandbox import."""

import asyncio
from copy import deepcopy
from datetime import timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from ac_platform.audit.service import verify_audit_chain
from ac_platform.coaching.report_adapter import from_report
from ac_platform.coaching.sandbox import SandboxCoaching, call_uuid, rep_uuid
from ac_platform.conversation_intelligence.acquisition_library import account_library
from ac_platform.conversation_intelligence.acquisition_models import (
    ConversationAcquisitionSettlement,
    ConversationAcquisitionUsage,
    ConversationReportMinuteEvent,
)
from ac_platform.conversation_intelligence.acquisition_reports import AcquisitionReports
from ac_platform.conversation_intelligence.acquisition_sessions import AcquisitionSessions
from ac_platform.conversation_intelligence.guest_ownership import GuestOwnership
from ac_platform.conversation_intelligence.models import ConversationReportDraft
from ac_platform.conversation_intelligence.org_insights import OrganisationInsights
from ac_platform.conversation_intelligence.run_budget_alarm import overdue_processing_plans
from ac_platform.conversation_intelligence.synthetic_import_contracts import (
    SyntheticCallBundle,
    SyntheticRecordInput,
)
from ac_platform.conversation_intelligence.synthetic_import_models import (
    ConversationSyntheticRecord,
)
from ac_platform.identity.models import PasswordCredential, ProviderIdentity
from ac_platform.outbox.models import Job
from ac_platform.tenancy.models import Membership, Organisation, Tenant
from tests.database.test_conversation_postgresql import postgres_harness as _postgres_harness
from tests.database.test_conversation_postgresql import run, seed
from tests.unit.conversation_intelligence.test_dev_sandbox_loader import dated_bundle, loader


@pytest.fixture(scope="module")
def postgres_harness():
    yield from _postgres_harness.__wrapped__()


def test_normal_reads_replay_race_and_rollback(postgres_harness, monkeypatch):
    async def scenario():
        module = loader()
        source = dated_bundle()
        reps = [
            {
                "synthetic": True,
                "synthetic_identity": True,
                "person_id": f"syn-fixture-R{i}",
                "fields": {
                    "email": f"rep{i}@example.invalid",
                    "name": f"Synthetic Rep {i}",
                    "joined_on": "2017-01-01",
                },
            }
            for i in range(1, 61)
        ]
        monkeypatch.setattr(module, "representatives", lambda _root: reps)
        monkeypatch.setattr(module, "bundles", lambda _root: iter([source]))
        monkeypatch.setattr(module, "EXPECTED_BUNDLES", 1)
        monkeypatch.setattr(
            module,
            "read_json",
            lambda _root, path, **_kwargs: (
                {"synthetic": True, "start": "2017-01-01"}
                if path == "simulation/config.json"
                else {
                    "synthetic": True,
                    "fictional": True,
                    "business_id": "syn-fixture",
                    "name": "Fictional selling company",
                }
            ),
        )
        engine = create_async_engine(postgres_harness.url, hide_parameters=True)
        try:
            async with AsyncSession(engine) as db, db.begin():
                db.add(Tenant(id=module.TARGET, name="AC Sandbox", slug="ac-sandbox"))
            owner = await seed(engine, tenant_id=module.TARGET, role="owner")
            async with AsyncSession(engine) as db, db.begin():
                db.add(
                    Organisation(
                        tenant_id=module.TARGET,
                        created_by_person_id=owner.person_id,
                        creation_command_id=uuid4(),
                        domain_verification_token="x" * 43,
                    )
                )

            async def load(*, apply=True, include_history=False):
                async with AsyncSession(engine) as db, db.begin():
                    return await module.load(
                        db,
                        root=Path("unused-fictional-root"),
                        approver=owner.person_id,
                        approval="AUT-1701 fictional dev test",
                        apply=apply,
                        include_history=include_history,
                    )

            preview = await load(apply=False)
            assert preview["calls_created"] == 1 and preview["after_calls"] == 0
            async with AsyncSession(engine) as db:
                assert (
                    await db.scalar(select(func.count()).select_from(ConversationAcquisitionUsage))
                    == 0
                )
            first, second = await asyncio.gather(load(), load())
            assert sorted([first["calls_created"], second["calls_created"]]) == [0, 1]
            assert first["reports_with_pillars"] == second["reports_with_pillars"] == 1
            assert first["reports_without_pillars"] == second["reports_without_pillars"] == 0
            async with AsyncSession(engine) as db, db.begin():
                ownership = GuestOwnership(
                    AcquisitionSessions(
                        db,
                        tenant_id=module.TARGET,
                        policy_revision="fictional-dev-1",
                        clock=lambda: owner.now + timedelta(minutes=1),
                    )
                )
                library = await account_library(ownership, owner.actor, include_owners=True)
                assert len(library["submissions"]) == 1
                row = library["submissions"][0]
                assert row["has_report"] and row["state"] == "report_ready"
                assert row["owner_name"] == "Synthetic Rep 1"
                submission = module.identifier("submission", source.metadata["call_id"])
                loaded_rep_id = module.identifier("person", source.metadata["rep_id"])
                assert row["submission_id"] == str(submission)
                assert row["owner_person_id"] == str(loaded_rep_id)
                report = await AcquisitionReports(ownership).report(
                    submission, actor=owner.actor, allow_organisation_read=True
                )
                progress = await AcquisitionReports(ownership).progress(
                    submission, actor=owner.actor, allow_organisation_read=True
                )
                assert progress["run_state"] == "done"
                assert not progress["retry_available"]
                assert report["report"]["content"]["summary"].startswith("Synthetic test call.")
                pillars = report["report"]["content"]["pillars"]
                assert pillars["outcome"]["status"] == "Follow-up Set"
                assert pillars["next_step"] == pillars["deal"]["next_event"]
                assert pillars["next_step"]["when"] == "05 January 2027 at 10:00 AM, India time"
                assert (
                    pillars["next_step"]["evidence"][0]["quote"]
                    == (source.transcript["lines"][1]["text"])
                )
                assert pillars["timeline"] == [{"label": "Opening", "start_ms": 0}]
                assert pillars["moments"][0]["kind"] == "Turning Point"
                assert pillars["deal"]["position"] is None
                stored_report = await db.get(
                    ConversationReportDraft, module.identifier("report", source.metadata["call_id"])
                )
                assert stored_report.payload["pillars"]["summary"] == "A fictional discovery call."
                assert stored_report.payload["improvements"][0]["title"] == "Agree a date"
                assert stored_report.payload["dimensions"][0]["call_state"] == "observed"
                coaching = from_report(
                    report,
                    submission_id=submission,
                    created_at=source.occurred_at,
                    comparison_key=f"unlinked:{submission}",
                )
                assert coaching is not None
                sandbox = SandboxCoaching(db, module.TARGET)
                assert await sandbox.flagged()
                team = await sandbox.read_team(owner.person_id)
                assert team.scope == "sandbox" and team.sandbox
                assert (team.analysed_calls, team.rep_count) == (1, 1)
                assert team.reps[0].name == "Synthetic Rep 1"
                assert team.reps[0].focus_label == source.coaching["current_focus"]["label"]
                rep_id = rep_uuid(module.TARGET, source.metadata["rep_id"])
                rep = await sandbox.read_rep(owner.person_id, rep_id)
                assert rep is not None and rep.state == "ready" and rep.analysed_calls == 1
                authored_call_id = call_uuid(module.TARGET, source.metadata["call_id"])
                call = await sandbox.read_call(owner.person_id, authored_call_id)
                assert call is not None and call.state == "ready"
                assert call.mission.behavior == source.coaching["action"]["mission"]["behaviour"]
                assert call.lesson.own_call.quote == source.transcript["lines"][0]["text"]
                assert not any(moment.playable for moment in call.evidence)
                # Calls -> Report -> Coaching retains the normal library's exact ids.
                linked = await sandbox.read_call(owner.person_id, submission)
                assert linked is not None and linked.state == "ready"
                assert linked.submission_id == submission
                assert linked.rep_person_id == loaded_rep_id
                assert linked.focus == call.focus
                assert linked.mission.origin_submission_id == submission
                assert linked.mission.behavior == call.mission.behavior
                assert linked.lesson.own_call.submission_id == submission
                assert linked.lesson.own_call.quote == call.lesson.own_call.quote
                assert {moment.submission_id for moment in linked.evidence} == {submission}
                assert [
                    (moment.quote, moment.start_ms, moment.end_ms, moment.playable)
                    for moment in linked.evidence
                ] == [
                    (moment.quote, moment.start_ms, moment.end_ms, moment.playable)
                    for moment in call.evidence
                ]
                linked_rep = await sandbox.read_rep(owner.person_id, loaded_rep_id)
                assert linked_rep is not None and linked_rep.state == "ready"
                assert linked_rep.person_id == loaded_rep_id
                assert linked_rep.focus == rep.focus
                assert {item.submission_id for item in linked_rep.calls} == {submission}
                other_viewer = uuid4()
                assert (await sandbox.read_team(other_viewer)).analysed_calls == 0
                assert await sandbox.read_rep(other_viewer, rep_id) is None
                assert await sandbox.read_call(other_viewer, authored_call_id) is None
                assert await sandbox.read_rep(other_viewer, loaded_rep_id) is None
                assert await sandbox.read_call(other_viewer, submission) is None
                assert (
                    await db.scalar(
                        select(func.sum(ConversationAcquisitionSettlement.charged_seconds))
                    )
                    == 0
                )
                assert await db.scalar(select(func.sum(ConversationReportMinuteEvent.seconds))) == 0
                assert (await db.scalars(select(Job.status))).all() == ["succeeded"]
                assert await db.scalar(select(func.count()).select_from(PasswordCredential)) == 0
                assert await db.scalar(select(func.count()).select_from(ProviderIdentity)) == 0
                assert (await verify_audit_chain(db, module.TARGET)).valid
                alarm = await overdue_processing_plans(db)
                assert not alarm["overdue"] and not alarm["overdue_sources"]
                assert not alarm["released_unfinished_runs"]
                insights = OrganisationInsights(db, module.TARGET)
                assert await insights.pending() == 0

            summary = SyntheticRecordInput.model_validate(
                {
                    "kind": "call_summary",
                    "key": "syn-fixture-historical-call",
                    "business_id": "syn-fixture",
                    "revision": 1,
                    "occurred_at": source.occurred_at,
                    "payload": {
                        "schema_version": "synthetic-sales-simulation/1",
                        "synthetic": True,
                        "call_id": "syn-fixture-historical-call",
                        "rep_id": "syn-fixture-R1",
                        "duration_ms": 1000,
                        "report": deepcopy(source.report),
                    },
                }
            )
            monkeypatch.setattr(module, "summaries", lambda _root: iter([summary]))
            history_preview = await load(apply=False, include_history=True)
            assert history_preview["summaries_validated"] == 1
            async with AsyncSession(engine) as db:
                assert (
                    await db.scalar(
                        select(func.count())
                        .select_from(ConversationSyntheticRecord)
                        .where(ConversationSyntheticRecord.kind == "call_summary")
                    )
                    == 0
                )
            history = await load(include_history=True)
            assert history["summaries_created"] == 1 and history["calls_created"] == 0
            again = await load(include_history=True)
            assert again["summaries_skipped"] == 1
            async with AsyncSession(engine) as db:
                stored_summary = await db.scalar(
                    select(ConversationSyntheticRecord).where(
                        ConversationSyntheticRecord.kind == "call_summary"
                    )
                )
                assert stored_summary.payload == summary.payload
                assert await OrganisationInsights(db, module.TARGET).pending() == 0
                assert (await verify_audit_chain(db, module.TARGET)).valid

            changed_summary = deepcopy(summary.model_dump())
            changed_summary["payload"]["report"]["the_big_picture"]["executive_summary"] = [
                "Changed authored history"
            ]
            monkeypatch.setattr(
                module,
                "summaries",
                lambda _root: iter([SyntheticRecordInput.model_validate(changed_summary)]),
            )
            with pytest.raises(ValueError, match="preserved synthetic revision changed"):
                await load(include_history=True)
            monkeypatch.setattr(module, "summaries", lambda _root: iter([summary]))

            changed = deepcopy(source.model_dump(by_alias=True))
            changed["coaching"]["action"]["new_authored_step"] = "Different preserved coaching"
            monkeypatch.setattr(
                module,
                "bundles",
                lambda _root: iter([SyntheticCallBundle.model_construct(**changed)]),
            )
            with pytest.raises(ValueError, match="original authored bundle changed"):
                await load()
            async with AsyncSession(engine) as db:
                assert (
                    await db.scalar(select(func.count()).select_from(ConversationReportDraft)) == 1
                )
                assert (
                    await db.scalar(
                        select(func.count())
                        .select_from(ConversationSyntheticRecord)
                        .where(ConversationSyntheticRecord.kind == "call")
                    )
                    == 1
                )
                members_before = await db.scalar(select(func.count()).select_from(Membership))

            # A new import failing after a pending member is still completely rolled back.
            monkeypatch.setattr(
                module,
                "representatives",
                lambda _root: (
                    reps
                    + [
                        {
                            **reps[0],
                            "person_id": "syn-fixture-extra",
                            "fields": {
                                **reps[0]["fields"],
                                "email": "extra@example.invalid",
                                "name": "Extra synthetic",
                            },
                        }
                    ]
                ),
            )
            with pytest.raises(ValueError):
                await load()
            async with AsyncSession(engine) as db:
                assert (
                    await db.scalar(select(func.count()).select_from(Membership)) == members_before
                )
        finally:
            await engine.dispose()

    run(scenario())
