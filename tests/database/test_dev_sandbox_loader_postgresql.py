"""Normal library/report/coaching reads, atomic rollback and zero-charge sandbox import."""

import asyncio
from copy import deepcopy
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI
from pydantic import SecretStr
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from ac_platform.application.settings import Settings
from ac_platform.audit.models import AuditEvent
from ac_platform.audit.service import verify_audit_chain
from ac_platform.coaching.http import install_coaching_http
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
from ac_platform.conversation_intelligence.checkpoints import content_hash
from ac_platform.conversation_intelligence.guest_ownership import GuestOwnership
from ac_platform.conversation_intelligence.models import ConversationReportDraft
from ac_platform.conversation_intelligence.org_insights import OrganisationInsights
from ac_platform.conversation_intelligence.run_budget_alarm import overdue_processing_plans
from ac_platform.conversation_intelligence.speaker_map_models import ConversationSpeakerMapRevision
from ac_platform.conversation_intelligence.speaker_map_service import read_speaker_map
from ac_platform.conversation_intelligence.synthetic_import_contracts import (
    SyntheticCallBundle,
    SyntheticRecordInput,
)
from ac_platform.conversation_intelligence.synthetic_import_models import (
    ConversationSandboxOrganisation,
    ConversationSyntheticRecord,
)
from ac_platform.http.auth import install_identity_http
from ac_platform.http.problem import register_problem_handlers
from ac_platform.http.routes import RouteContext
from ac_platform.identity.models import PasswordCredential, Person, ProviderIdentity
from ac_platform.outbox.models import Job
from ac_platform.tenancy.models import Membership, Organisation, Tenant
from tests.database.test_conversation_account_library_postgresql import _session
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

            async def load(*, apply=True):
                async with AsyncSession(engine) as db, db.begin():
                    return await module.load(
                        db,
                        root=Path("unused-fictional-root"),
                        approver=owner.person_id,
                        approval="AUT-1701 fictional dev test",
                        apply=apply,
                    )

            async def history(*, apply=True):
                return await module.load_history(
                    async_sessionmaker(engine, expire_on_commit=False),
                    root=Path("unused-fictional-root"),
                    approver=owner.person_id,
                    approval="AUT-1701 fictional dev test",
                    apply=apply,
                )

            preview = await load(apply=False)
            assert preview["calls_created"] == 1 and preview["after_calls"] == 0
            assert preview["speaker_maps_created"] == 1
            async with AsyncSession(engine) as db:
                assert (
                    await db.scalar(select(func.count()).select_from(ConversationAcquisitionUsage))
                    == 0
                )
            first, second = await asyncio.gather(load(), load())
            assert sorted([first["calls_created"], second["calls_created"]]) == [0, 1]
            assert first["reports_with_pillars"] == second["reports_with_pillars"] == 1
            assert first["reports_without_pillars"] == second["reports_without_pillars"] == 0
            assert sorted([first["speaker_maps_created"], second["speaker_maps_created"]]) == [0, 1]
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
                normalized = stored_report.transcript["normalized"]
                mapping = await read_speaker_map(
                    ownership, submission, actor=owner.actor, allow_organisation_read=True
                )
                assert mapping["status"] == "confirmed"
                assert mapping["transcript_revision"] == report["transcript_revision"]
                assert {s["speaker_id"]: s["role"] for s in mapping["speakers"]} == {
                    "rep": "salesperson",
                    "prospect": "prospect",
                }
                assert all(s["role_source"] == "confirmed" for s in mapping["speakers"])
                seeded_map = await db.scalar(select(ConversationSpeakerMapRevision))
                assert seeded_map.actor_person_id == owner.person_id
                assert seeded_map.revision == 1
                authored_choices = deepcopy(seeded_map.speakers)
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

            # The Report embeds Coaching only when every identity and citation
            # matches its loaded report. Exercise the actual signed-in HTTP path.
            origin = "https://salesxray.example.test"
            settings = Settings(
                _env_file=None,
                environment="test",
                public_app_url="https://learner.example.test",
                admin_app_url="https://admin.example.test",
                coach_app_url="https://coach.example.test",
                api_url="https://api.example.test",
                sales_xray_app_url=origin,
                public_learner_tenant_id=uuid4(),
                operations_tenant_id=uuid4(),
                session_token_pepper=SecretStr("fictional-loader-session-hash-test-only"),
            )
            sessions = async_sessionmaker(engine, expire_on_commit=False)
            app = FastAPI()
            register_problem_handlers(app)
            require_actor = install_identity_http(app, settings=settings, sessions=sessions)
            install_coaching_http(app, RouteContext(settings, require_actor, sessions))
            token = await _session(SimpleNamespace(settings=settings, sessions=sessions), owner)
            route = f"/v1/me/coaching/calls/{submission}"
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url=origin
            ) as client:
                assert (await client.get(route)).status_code == 401
                client.cookies.set(settings.session_cookie_name, token)
                response = await client.get(route)
                assert response.status_code == 200
                bound = response.json()
                assert bound["state"] == "ready"
                for key in ("recording_id", "source_sha256", "transcript_revision"):
                    assert bound[key] == report[key]
                assert bound["report_revision"] == content_hash(report["report"])
                segments = {s["id"]: s for s in normalized["segments"]}
                moments = [*bound["evidence"], bound["lesson"]["own_call"]]
                assert moments
                for moment in moments:
                    assert moment["submission_id"] == str(submission)
                    for key in ("recording_id", "source_sha256", "transcript_revision"):
                        assert moment[key] == report[key]
                    segment = segments[moment["segment_id"]]
                    assert moment["quote"] in segment["text"]
                    assert (
                        segment["start_ms"]
                        <= moment["start_ms"]
                        < moment["end_ms"]
                        <= segment["end_ms"]
                    )
                    assert moment["playable"] is False
                other_token = await _session(
                    SimpleNamespace(settings=settings, sessions=sessions),
                    await seed(engine, tenant_id=module.TARGET, role="owner"),
                )
                client.cookies.set(settings.session_cookie_name, other_token)
                denied = await client.get(route)
                assert denied.status_code == 404
                assert source.coaching["action"]["mission"]["behaviour"] not in denied.text

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
            history_preview = await history(apply=False)
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
            history_result = await history()
            assert history_result["summaries_created"] == 1
            assert history_result["batches"] == 1
            again = await history()
            assert again["summaries_skipped"] == 1
            # An existing later speaker choice always wins over a source replay.
            async with AsyncSession(engine) as db, db.begin():
                choices = deepcopy(authored_choices)
                next(s for s in choices if s["speaker_id"] == "rep")["display_name"] = (
                    "Reviewed synthetic representative"
                )
                db.add(
                    ConversationSpeakerMapRevision(
                        id=uuid4(),
                        tenant_id=module.TARGET,
                        submission_id=submission,
                        revision=2,
                        transcript_revision=report["transcript_revision"],
                        speakers=choices,
                        actor_person_id=owner.person_id,
                        created_at=owner.now,
                    )
                )
            replay = await load()
            assert replay["speaker_maps_created"] == 0 and replay["speaker_maps_preserved"] == 1
            async with AsyncSession(engine) as db:
                assert (
                    await db.scalar(
                        select(func.count()).select_from(ConversationSpeakerMapRevision)
                    )
                    == 2
                )
                latest = await db.scalar(
                    select(ConversationSpeakerMapRevision)
                    .order_by(ConversationSpeakerMapRevision.revision.desc())
                    .limit(1)
                )
                assert latest.speakers == choices
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
                await history()
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


@pytest.mark.parametrize("failure", ["audit", "approval"])
def test_history_batches_release_locks_audit_rollback_and_resume(
    postgres_harness, monkeypatch, failure
):
    async def scenario():
        module = loader()
        monkeypatch.setattr(module, "TARGET", uuid4())
        source = dated_bundle()
        rows = [
            SyntheticRecordInput.model_validate(
                {
                    "kind": "call_summary",
                    "key": f"syn-fixture-history-{i}",
                    "business_id": "syn-fixture",
                    "revision": 1,
                    "occurred_at": source.occurred_at,
                    "payload": {
                        "schema_version": "synthetic-sales-simulation/1",
                        "synthetic": True,
                        "call_id": f"syn-fixture-history-{i}",
                        "rep_id": "syn-fixture-R1",
                        "duration_ms": 1000,
                        "report": deepcopy(source.report),
                    },
                }
            )
            for i in range(3)
        ]
        monkeypatch.setattr(module, "summaries", lambda _root: iter(rows))
        engine = create_async_engine(postgres_harness.url, hide_parameters=True)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        try:
            async with sessions() as db, db.begin():
                db.add(Tenant(id=module.TARGET, name="AC Sandbox", slug=module.TARGET.hex))
            owner = await seed(engine, tenant_id=module.TARGET, role="owner")
            async with sessions() as db, db.begin():
                db.add(
                    Organisation(
                        tenant_id=module.TARGET,
                        created_by_person_id=owner.person_id,
                        creation_command_id=uuid4(),
                        domain_verification_token="x" * 43,
                    )
                )
                await db.flush()
                db.add(
                    ConversationSandboxOrganisation(
                        tenant_id=module.TARGET,
                        approved_by_person_id=owner.person_id,
                        approval_reference="Fictional dev batch test",
                        created_at=owner.now,
                    )
                )

            async def history(*, apply=True, batch_size=1):
                return await module.load_history(
                    sessions,
                    root=Path("unused-fictional-root"),
                    approver=owner.person_id,
                    approval="Fictional dev batch test",
                    apply=apply,
                    batch_size=batch_size,
                )

            async def stored():
                async with sessions() as db:
                    records = list(
                        await db.scalars(
                            select(ConversationSyntheticRecord).where(
                                ConversationSyntheticRecord.tenant_id == module.TARGET,
                            )
                        )
                    )
                    events = list(
                        await db.scalars(
                            select(AuditEvent)
                            .where(
                                AuditEvent.tenant_id == module.TARGET,
                            )
                            .order_by(AuditEvent.sequence_no)
                        )
                    )
                    assert (await verify_audit_chain(db, module.TARGET)).valid
                    return records, events

            preview = await history(apply=False)
            assert preview["summaries_validated"] == 3
            assert preview["before_summaries"] == preview["after_summaries"] == 0
            assert await stored() == ([], [])

            original_target, original_preserved = module.target, module.preserved
            original_audit = module.AuditRepository.append
            targets = 0
            between_batches = 0

            async def checked_target(db, approver):
                nonlocal targets
                targets += 1
                if failure == "approval" and targets == 3:
                    async with sessions() as revoked, revoked.begin():
                        await revoked.execute(
                            update(Membership)
                            .where(
                                Membership.tenant_id == module.TARGET,
                                Membership.person_id == approver,
                            )
                            .values(role="member")
                        )
                await original_target(db, approver)

            async def checked_preserved(db, **kwargs):
                nonlocal between_batches
                async with sessions() as observer, observer.begin():
                    # The API's tenant SHARE fence works during a loader batch.
                    assert (
                        await observer.scalar(
                            select(Tenant)
                            .where(
                                Tenant.id == module.TARGET,
                            )
                            .with_for_update(read=True, nowait=True)
                        )
                        is not None
                    )
                    if kwargs["key"] == rows[1].key:
                        # The prior batch has committed and released its approver FK.
                        assert (
                            await observer.scalar(
                                select(Person)
                                .where(
                                    Person.id == owner.person_id,
                                )
                                .with_for_update(nowait=True)
                            )
                            is not None
                        )
                        records, events = await stored()
                        assert len(records) == len(events) == 1
                        between_batches += 1
                return await original_preserved(db, **kwargs)

            async def failing_audit(repository, **kwargs):
                payload = kwargs["payload"]
                if failure == "audit" and payload.get("batch") == 2:
                    raise ValueError("Fictional audit failure")
                return await original_audit(repository, **kwargs)

            monkeypatch.setattr(module, "target", checked_target)
            monkeypatch.setattr(module, "preserved", checked_preserved)
            monkeypatch.setattr(module.AuditRepository, "append", failing_audit)
            with pytest.raises(ValueError, match="audit failure|current approving owner"):
                await history()
            records, events = await stored()
            assert [record.synthetic_key for record in records] == [rows[0].key]
            assert len(events) == 1
            assert events[0].payload["mode"] == "history_batch"
            assert events[0].payload["summaries_created"] == 1
            assert events[0].payload["source_sha256"]
            assert between_batches == (1 if failure == "audit" else 0)

            monkeypatch.setattr(module, "target", original_target)
            monkeypatch.setattr(module, "preserved", original_preserved)
            monkeypatch.setattr(module.AuditRepository, "append", original_audit)
            async with sessions() as db, db.begin():
                await db.execute(
                    update(Membership)
                    .where(
                        Membership.tenant_id == module.TARGET,
                        Membership.person_id == owner.person_id,
                    )
                    .values(role="owner")
                )
            resumed = await history()
            assert resumed["summaries_created"] == 2 and resumed["summaries_skipped"] == 1
            assert resumed["before_summaries"] == 1 and resumed["after_summaries"] == 3
            assert resumed["insight_rows_refreshed"] == 3
            replay = await history()
            assert replay["summaries_created"] == 0 and replay["summaries_skipped"] == 3
            assert replay["source_sha256"] == resumed["source_sha256"] == preview["source_sha256"]
            records, events = await stored()
            assert len(records) == 3
            assert all(event.payload["provider_calls"] == 0 for event in events)
            assert all(event.payload["charged_seconds"] == 0 for event in events)

            # Dry-run checks preserved content too; it never accepts a changed revision.
            changed = rows[0].model_copy(deep=True)
            changed.payload["duration_ms"] = 2000
            monkeypatch.setattr(module, "summaries", lambda _root: iter([changed]))
            with pytest.raises(ValueError, match="preserved synthetic revision changed"):
                await history(apply=False)
            unchanged, unchanged_events = await stored()
            assert len(unchanged) == 3 and len(unchanged_events) == len(events)
        finally:
            await engine.dispose()

    run(scenario())
