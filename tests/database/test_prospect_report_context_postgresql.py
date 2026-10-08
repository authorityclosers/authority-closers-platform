"""Fictional two-call HTTP citations and withdrawal on disposable PostgreSQL."""

import hashlib
import json
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import event, null, select, update

from ac_platform.conversation_intelligence.acquisition_reports import AcquisitionReports
from ac_platform.conversation_intelligence.checkpoints import build_checkpoint, content_hash
from ac_platform.conversation_intelligence.guest_models import ConversationGuestSubmission
from ac_platform.conversation_intelligence.inference import binding_for, verified_checkpoint
from ac_platform.conversation_intelligence.models import (
    ConversationCheckpoint,
    ConversationPermission,
    ConversationRecording,
    ConversationReportDraft,
    ConversationRun,
)
from ac_platform.conversation_intelligence.prospect_models import ConversationProspectMembership
from ac_platform.conversation_intelligence.prospect_report_context import previous_call_context
from ac_platform.conversation_intelligence.report_store import PrivateProofReference
from ac_platform.conversation_intelligence.reports import load_report_profile, parse_report_draft
from ac_platform.conversation_intelligence.sensitive_segments_store import SensitiveSegmentsStore
from ac_platform.outbox.models import Job
from tests.conversation_overview_fixtures import overview_for
from tests.database.test_conversation_postgresql import postgres_harness as _postgres_harness
from tests.database.test_conversation_postgresql import run, seed
from tests.database.test_conversation_submission_http_postgresql import ORIGIN, PREFIX, _setup
from tests.database.test_prospect_store_postgresql import direct_call, store
from tests.unit.conversation_intelligence.test_reports import _payload, _transcript

PROMISE = "I will send the proposal on Friday."


@pytest.fixture(scope="module")
def postgres_harness() -> Any:
    yield from cast(Any, _postgres_harness).__wrapped__()


async def report_fixture(setup: Any, submission: UUID, *, wording: str = PROMISE) -> dict[str, Any]:
    """Seed immutable, private-import-shaped fictional reports, never a live provider receipt."""
    async with setup.sessions() as db, db.begin():
        rec = await db.get(
            ConversationRecording,
            await db.scalar(
                select(ConversationGuestSubmission.recording_id).where(
                    ConversationGuestSubmission.submission_id == submission
                )
            ),
        )
        assert rec is not None
        raw = json.dumps({"text": wording, "fictional_source_id": str(rec.id)})
        transcript = _transcript(count=1)
        transcript.update(
            source_sha256=rec.source_sha256, revision=hashlib.sha256(raw.encode()).hexdigest()
        )
        transcript["segments"][0]["text"] = "Native line 1: " + wording
        payload = _payload(transcript)
        payload["overview"] = overview_for(payload)
        payload["overview"]["prospect_interpretations"] = [
            {
                "source": {
                    "text": "A next action was stated.",
                    "evidence": payload["strengths"][0]["evidence"],
                },
                "possible_concern": "The prospect may want time to review.",
                "interpretation_kind": "inference",
            }
        ]
        report = parse_report_draft(payload, transcript, source_label="Fictional call").model_dump(
            mode="json"
        )
        built, ids, replicate = {}, {}, uuid4().hex
        for stage, parents, value in [
            ("C0", [], {}),
            ("C1", ["C0"], {}),
            ("C2", ["C0"], transcript),
            ("C3", ["C1", "C2"], {}),
            ("C4", ["C2", "C3"], {}),
            ("C5", ["C4"], report),
        ]:
            cp = build_checkpoint(
                binding_for(rec),
                stage,
                "fictional-context-v1",
                {},
                [built[p] for p in parents],
                content_hash(value),
                replicate=replicate,
            )
            built[stage], ids[stage] = cp, uuid4()
            db.add(
                ConversationCheckpoint(
                    id=ids[stage],
                    tenant_id=rec.tenant_id,
                    person_id=rec.person_id,
                    recording_id=rec.id,
                    stage=stage,
                    cache_key=cp.cache_key,
                    manifest_sha256=cp.manifest_sha256,
                    payload_sha256=cp.payload_sha256,
                    manifest=cp.as_dict(),
                    payload=value,
                    created_at=setup.clock[0],
                )
            )
        job = Job(
            tenant_id=rec.tenant_id,
            kind="fictional-context",
            dedupe_key=str(uuid4()),
            payload={},
            status="succeeded",
        )
        db.add(job)
        await db.flush()
        run_row = ConversationRun(
            id=uuid4(),
            tenant_id=rec.tenant_id,
            person_id=rec.person_id,
            recording_id=rec.id,
            request_key=str(uuid4()),
            intent_sha256="a" * 64,
            recipe_revision="fictional-context-v1",
            generation=rec.generation,
            state="completed",
            job_id=job.id,
            created_at=setup.clock[0],
            completed_at=setup.clock[0],
        )
        db.add(run_row)
        await db.flush()
        bundle = {"normalized": transcript, "native_json": raw}
        receipt = PrivateProofReference(
            schema_id="ac.sales-xray.private-proof-reference/1",
            approval_receipt_sha256="a" * 64,
            transcription_response_sha256=transcript["revision"],
            generation_receipt_sha256="b" * 64,
            source_review_receipt_sha256="c" * 64,
            new_provider_calls=0,
        ).model_dump(mode="json")
        draft = ConversationReportDraft(
            id=uuid4(),
            tenant_id=rec.tenant_id,
            person_id=rec.person_id,
            recording_id=rec.id,
            run_id=run_row.id,
            source_revision=rec.source_revision,
            source_sha256=rec.source_sha256,
            report_sha256=content_hash(report),
            transcript_sha256=content_hash(bundle),
            profile_sha256=content_hash(load_report_profile()),
            evidence_receipt_sha256=content_hash(receipt),
            payload=report,
            transcript=bundle,
            evidence_receipt=receipt,
            created_at=setup.clock[0],
        )
        db.add(draft)
        return {
            "recording_id": rec.id,
            "permission_id": rec.permission_id,
            "checkpoint_id": ids["C5"],
            "draft_id": draft.id,
            "report": report,
            "manifest": built["C2"].manifest_sha256,
        }


async def pair(setup: Any) -> tuple[UUID, UUID, dict[str, Any]]:
    first = await direct_call(setup)
    evidence = await report_fixture(setup, first)
    setup.clock[0] += timedelta(seconds=1)
    second = await direct_call(setup)
    await report_fixture(setup, second, wording="Please resend the proposal.")
    async with setup.sessions() as db, db.begin():
        prospect = await store(setup, db).create_from_call(
            setup.state.actor, first, display_name="Fictional Example"
        )
        evidence["prospect_id"] = prospect.id
    return first, second, evidence


async def context(setup: Any, second: UUID, actor: Any = None) -> dict[str, Any]:
    async with setup.sessions() as db, db.begin():
        return await previous_call_context(
            store(setup, db).ownership,
            actor or setup.state.actor,
            second,
            report_created_at=setup.clock[0],
        )


def test_second_report_cites_first_only_after_confirmation(
    postgres_harness: Any, tmp_path: Path
) -> None:
    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path)
        try:
            first, second, evidence = await pair(setup)
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=setup.app), base_url=ORIGIN
            ) as client:
                client.cookies.set(setup.settings.session_cookie_name, setup.token)
                path = f"{PREFIX}/submissions/{second}/report"
                unconfirmed = await client.get(path)
                assert unconfirmed.status_code == 200, unconfirmed.text
                assert unconfirmed.json()["previous_call_context"]["sources"] == []
                async with setup.sessions() as db, db.begin():
                    await store(setup, db).confirm_link(
                        setup.state.actor,
                        second,
                        evidence["prospect_id"],
                        expected_membership_id=None,
                    )
                response = await client.get(path)
                assert response.status_code == 200, response.text
                envelope = response.json()
                source = envelope["previous_call_context"]["sources"][0]
                assert source["submission_id"] == str(first)
                assert source["report_url"] == f"/analysis/calls/{first}"
                assert source["reference"]["snapshot_id"] == str(evidence["checkpoint_id"])
                assert source["reference"]["report_sha256"] == content_hash(evidence["report"])
                assert source["reference"]["transcript_manifest_sha256"] == evidence["manifest"]
                assert source["reference"]["source_revision"] == 1
                assert source["source_quotes"] == [
                    {"segment_id": "s1", "quote": PROMISE, "start_ms": 0, "end_ms": 900}
                ]
                assert source["report_interpretations"][0]["interpretation_kind"] == "inference"
                assert PROMISE not in str(envelope["report"]["content"])
                assert response.headers["cache-control"] == "private, no-store"
                assert (await client.get(path)).json() == envelope
                async with setup.sessions() as db:
                    old = await db.get(ConversationReportDraft, evidence["draft_id"])
                    assert old is not None and old.payload == evidence["report"]
                    assert (
                        await db.get(ConversationCheckpoint, evidence["checkpoint_id"])
                    ).payload == evidence["report"]
        finally:
            await setup.engine.dispose()

    run(exercise())


@pytest.mark.parametrize(
    "unavailable", ["revoked", "expired", "deleted", "erased", "corrupt", "unlinked", "sensitive"]
)
def test_unavailable_sources_disappear(
    postgres_harness: Any, tmp_path: Path, unavailable: str
) -> None:
    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path)
        try:
            first, second, evidence = await pair(setup)
            async with setup.sessions() as db, db.begin():
                service = store(setup, db)
                await service.confirm_link(
                    setup.state.actor, second, evidence["prospect_id"], expected_membership_id=None
                )
            assert len((await context(setup, second))["sources"]) == 1
            async with setup.sessions() as db, db.begin():
                if unavailable in {"revoked", "expired"}:
                    values = (
                        {"revoked_at": setup.clock[0]}
                        if unavailable == "revoked"
                        else {"retention_until": setup.clock[0]}
                    )
                    await db.execute(
                        update(ConversationPermission)
                        .where(ConversationPermission.id == evidence["permission_id"])
                        .values(**values)
                    )
                elif unavailable == "deleted":
                    await db.execute(
                        update(ConversationRecording)
                        .where(ConversationRecording.id == evidence["recording_id"])
                        .values(state="deleted")
                    )
                elif unavailable == "erased":
                    await db.execute(
                        update(ConversationCheckpoint)
                        .where(ConversationCheckpoint.id == evidence["checkpoint_id"])
                        .values(erased_at=setup.clock[0], payload=null(), manifest=null())
                    )
                elif unavailable == "corrupt":
                    original = await db.get(ConversationCheckpoint, evidence["checkpoint_id"])
                    rec = await db.get(ConversationRecording, evidence["recording_id"])
                    cp = replace(
                        verified_checkpoint(original, binding_for(rec)), replicate="corrupt-fixture"
                    )
                    db.add(
                        ConversationCheckpoint(
                            id=uuid4(),
                            tenant_id=original.tenant_id,
                            person_id=original.person_id,
                            recording_id=rec.id,
                            stage="C5",
                            cache_key=cp.cache_key,
                            manifest_sha256=cp.manifest_sha256,
                            payload_sha256=cp.payload_sha256,
                            manifest=cp.as_dict(),
                            payload={"broken": "fictional corrupt payload"},
                            created_at=setup.clock[0],
                        )
                    )
                elif unavailable == "unlinked":
                    service = store(setup, db)
                    current = await service.read_memberships(
                        setup.state.actor, evidence["prospect_id"]
                    )
                    member = next(row for row in current if row.submission_id == first)
                    await service.unlink(setup.state.actor, first, expected_membership_id=member.id)
                else:
                    await SensitiveSegmentsStore(db).mark(
                        setup.state.actor,
                        recording_id=evidence["recording_id"],
                        transcript_revision=evidence["report"]["transcript_revision"],
                        segments=[("s1", "SENSITIVE_FINANCIAL")],
                        reason_ref="AUT-1070",
                        idempotency_key="fictional-context-withhold",
                    )
            async with setup.sessions() as db, db.begin():
                result = await AcquisitionReports(store(setup, db).ownership).report(
                    second, actor=setup.state.actor
                )
                assert result["previous_call_context"]["sources"] == []
                assert PROMISE not in json.dumps(result)
        finally:
            await setup.engine.dispose()

    run(exercise())


def test_person_workspace_chronology_and_constant_query_count(
    postgres_harness: Any, tmp_path: Path
) -> None:
    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path)
        try:
            first, second, evidence = await pair(setup)
            other = await seed(setup.engine, tenant_id=setup.state.tenant_id, role="member")
            foreign = await seed(setup.engine)
            hidden = await direct_call(setup, other.actor)
            await report_fixture(setup, hidden, wording="Private fictional detail.")
            async with setup.sessions() as db, db.begin():
                await store(setup, db).confirm_link(
                    setup.state.actor, second, evidence["prospect_id"], expected_membership_id=None
                )
                db.add(
                    ConversationProspectMembership(
                        id=uuid4(),
                        tenant_id=setup.state.tenant_id,
                        prospect_id=evidence["prospect_id"],
                        submission_id=hidden,
                        linked_by_person_id=other.person_id,
                        created_at=setup.clock[0],
                    )
                )
            statements: list[str] = []

            def count(
                _conn: Any, _cursor: Any, sql: str, _params: Any, _context: Any, _many: Any
            ) -> None:
                statements.append(sql)

            event.listen(setup.engine.sync_engine, "before_cursor_execute", count)
            counts = []
            for actor in [setup.state.actor, other.actor, foreign.actor]:
                statements.clear()
                result = await context(setup, second, actor)
                counts.append(len(statements))
                assert [source["submission_id"] for source in result["sources"]] == (
                    [str(first)] if actor == setup.state.actor else []
                )
            assert counts == [6, 6, 6]
            event.remove(setup.engine.sync_engine, "before_cursor_execute", count)
            # Later calls/revisions cannot become evidence for an older report.
            setup.clock[0] += timedelta(seconds=1)
            later = await direct_call(setup)
            await report_fixture(setup, later, wording="A later fictional statement.")
            async with setup.sessions() as db, db.begin():
                await store(setup, db).confirm_link(
                    setup.state.actor, later, evidence["prospect_id"], expected_membership_id=None
                )
            assert [s["submission_id"] for s in (await context(setup, second))["sources"]] == [
                str(first)
            ]
            await report_fixture(setup, first, wording="A later report revision.")
            async with setup.sessions() as db, db.begin():
                older = await AcquisitionReports(store(setup, db).ownership).report(
                    second, actor=setup.state.actor
                )
                source = older["previous_call_context"]["sources"][0]
                assert source["reference"]["snapshot_id"] == str(evidence["checkpoint_id"])
                assert source["source_quotes"][0]["quote"] == PROMISE
        finally:
            await setup.engine.dispose()

    run(exercise())


def test_history_cap_and_timestamp_ties_are_deterministic(
    postgres_harness: Any, tmp_path: Path
) -> None:
    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path)
        try:
            prior = []
            for index in range(5):
                call = await direct_call(setup)
                await report_fixture(setup, call, wording=f"A fictional detail for call {index}.")
                prior.append(call)
            setup.clock[0] += timedelta(seconds=1)
            current = await direct_call(setup)
            async with setup.sessions() as db, db.begin():
                service = store(setup, db)
                prospect = await service.create_from_call(
                    setup.state.actor, prior[0], display_name="Fictional history"
                )
                for call in [*prior[1:], current]:
                    await service.confirm_link(
                        setup.state.actor, call, prospect.id, expected_membership_id=None
                    )
            result = await context(setup, current)
            assert [s["submission_id"] for s in result["sources"]] == [
                str(call) for call in sorted(prior, key=str)[-3:]
            ]
            assert await context(setup, current) == result
        finally:
            await setup.engine.dispose()

    run(exercise())
