"""Detected identity and source-safe team sharing on disposable PostgreSQL."""

import asyncio
import json
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select

from ac_platform.audit.models import AuditEvent
from ac_platform.audit.service import verify_audit_chain
from ac_platform.conversation_intelligence.call_map import parse_call_map
from ac_platform.conversation_intelligence.checkpoints import build_checkpoint, content_hash
from ac_platform.conversation_intelligence.guest_models import ConversationGuestSubmission
from ac_platform.conversation_intelligence.inference import binding_for
from ac_platform.conversation_intelligence.models import (
    ConversationCheckpoint,
    ConversationRecording,
)
from ac_platform.conversation_intelligence.prospect_models import (
    ConversationProspect,
    ConversationProspectFieldRevision,
    ConversationProspectMembership,
)
from ac_platform.conversation_intelligence.prospect_profile import (
    ProfilePolicy,
    ProfileResponse,
    extract_prospect_profile,
)
from ac_platform.conversation_intelligence.reports import ReportDraft, parse_report_draft
from ac_platform.conversation_intelligence.sensitive_segments_store import SensitiveSegmentsStore
from ac_platform.tenancy.models import Organisation
from tests.database.test_conversation_postgresql import postgres_harness as _postgres_harness
from tests.database.test_conversation_postgresql import run, seed
from tests.database.test_conversation_submission_http_postgresql import _setup
from tests.database.test_prospect_profile_edit_postgresql import PREFIX, client_for, private
from tests.database.test_prospect_store_postgresql import direct_call, store
from tests.unit.conversation_intelligence.test_reports import _payload, _transcript


@pytest.fixture
def postgres_harness() -> Any:
    yield from cast(Any, _postgres_harness).__wrapped__()


async def sales_c5(
    setup: Any, call: UUID, *, purpose: str = "sales", company: str = "Fictional Studio"
) -> dict[str, Any]:
    async with setup.sessions() as db, db.begin():
        link = await db.get(ConversationGuestSubmission, (setup.state.tenant_id, call))
        recording = await db.get(ConversationRecording, link.recording_id)
        transcript = _transcript(count=1)
        transcript["source_sha256"] = recording.source_sha256
        transcript["revision"] = f"fictional-{call}"
        transcript["segments"][0]["text"] = (
            f"Native line 1: I run {company} and want to discuss the offer."
        )
        segment = transcript["segments"][0]
        ref = {"segment_id": segment["id"], "quote": segment["text"]}
        payload = _payload(transcript)
        payload["call_map"] = {
            "version": "call-map/1",
            "verdict_line": "The prospect described their company.",
            "call_purpose": {"kind": purpose, "evidence": [ref]},
            "speakers": [{"speaker_id": segment["speaker_id"], "role": "prospect"}],
            "phases": [{"name": "opening", "start_ms": 0}],
            "time_promise": None,
            "outcome": {
                "kind": "none",
                "next_step_rung": "none",
                "next_step_when": None,
                "evidence": [],
            },
            "signals": [],
            "pitch_items": [],
            "pains": [],
            "money": [],
            "claims": [],
            "qualification_gaps": [],
            "qualification_confirmed": [],
            "prospect_tasks": [],
            "seller_tasks": [],
            "objections": [],
            "prospect_facts": [{"key": "company", "text": company, "evidence": [ref]}],
        }
        call_map = parse_call_map(payload.pop("call_map"))
        report = (
            parse_report_draft(payload, transcript)
            .model_copy(update={"call_map": call_map})
            .model_dump(mode="json")
        )
        built: dict[str, Any] = {}
        for stage, parents, value in [
            ("C0", [], {}),
            ("C1", ["C0"], {}),
            ("C2", ["C0"], transcript),
            ("C3", ["C1", "C2"], {}),
            ("C4", ["C2", "C3"], {}),
            ("C5", ["C4"], report),
        ]:
            checkpoint = build_checkpoint(
                binding_for(recording),
                stage,
                "fictional-detection-v1",
                {},
                [built[p] for p in parents],
                content_hash(value),
            )
            built[stage] = checkpoint
            db.add(
                ConversationCheckpoint(
                    id=uuid4(),
                    tenant_id=recording.tenant_id,
                    person_id=recording.person_id,
                    recording_id=recording.id,
                    stage=stage,
                    cache_key=checkpoint.cache_key,
                    manifest_sha256=checkpoint.manifest_sha256,
                    payload_sha256=checkpoint.payload_sha256,
                    feature_blob_id=None,
                    manifest=checkpoint.as_dict(),
                    payload=value,
                    created_at=setup.clock[0],
                )
            )
        return {**ref, "start_ms": segment["start_ms"], "end_ms": segment["end_ms"]}


def test_detection_idempotency_separate_people_confirmation_and_explicit_unlink(
    postgres_harness: Any, tmp_path: Path
) -> None:
    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path)
        try:
            first, second, internal, unanalysed = [await direct_call(setup) for _ in range(4)]
            await sales_c5(setup, first)
            await sales_c5(setup, second)
            await sales_c5(setup, internal, purpose="internal")

            async def detect() -> UUID:
                async with setup.sessions() as db, db.begin():
                    row = await store(setup, db).ensure_detected(setup.state.actor, first)
                    return row.id

            identifiers = await asyncio.gather(detect(), detect())
            assert identifiers[0] == identifiers[1]
            identifier = identifiers[0]
            async with client_for(setup) as client:
                for call in (first, second, internal, unanalysed):
                    private(await client.post(f"{PREFIX}/calls/{call}/detect", json={}), 200)
                page = (await client.get(PREFIX)).json()
                assert page["total"] == 2
                assert len({row["prospect_id"] for row in page["prospects"]}) == 2
                detail = (await client.get(f"{PREFIX}/{identifier}")).json()["prospect"]
                assert detail["origin"] == "detected" and detail["confirmed_at"] is None
                assert detail["profile_fields"]["name"]["state"] == "unknown"
                assert detail["profile_fields"]["business"]["value"]["text"] == "Fictional Studio"
                assert detail["profile_fields"]["business"]["evidence"]["submission_id"] == str(
                    first
                )
                assert not detail["profile_fields"]["business"]["locked"]
                for key in ("phone", "email"):
                    assert detail["profile_fields"][key]["state"] == "unknown"
                path = f"{PREFIX}/{identifier}/confirm"
                private(await client.post(path, json={"expected_revision": 1}), 409)
                private(await client.post(path, json={"expected_revision": 2}), 200)
                private(await client.post(path, json={"expected_revision": 2}), 200)
                confirmed = (await client.get(f"{PREFIX}/{identifier}")).json()["prospect"]
                assert confirmed["confirmed_at"] and confirmed["revision"] == 3
                assert not confirmed["profile_fields"]["business"]["locked"]
                private(await client.post(path, json={"expected_revision": True}), 422)
                private(
                    await client.post(
                        path,
                        json={"expected_revision": 3},
                        headers={"Origin": "https://evil.example.test"},
                    ),
                    403,
                )
            async with setup.sessions() as db, db.begin():
                service = store(setup, db)
                memberships = await service.read_memberships(setup.state.actor, identifier)
                assert memberships[0].link_kind == "detected"
                await service.unlink(
                    setup.state.actor, first, expected_membership_id=memberships[0].id
                )
                assert await service.ensure_detected(setup.state.actor, first) is None
                assert await db.scalar(select(func.count()).select_from(ConversationProspect)) == 2
                assert (
                    await db.scalar(
                        select(func.count()).select_from(ConversationProspectFieldRevision)
                    )
                    == 2
                )
                events = (
                    await db.scalars(
                        select(AuditEvent).where(
                            AuditEvent.action == "conversation.prospect_confirmed"
                        )
                    )
                ).all()
                assert len(events) == 1
                assert (await verify_audit_chain(db, setup.state.tenant_id)).valid
        finally:
            await setup.engine.dispose()

    run(exercise())


def test_team_customer_reads_and_explicit_links_preserve_source_and_person_locks(
    postgres_harness: Any, tmp_path: Path
) -> None:
    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path)
        try:
            other = await seed(setup.engine, tenant_id=setup.state.tenant_id, role="member")
            call = await direct_call(setup)
            ref = await sales_c5(setup, call)
            other_call = await direct_call(setup, other.actor)
            await sales_c5(setup, other_call)
            async with setup.sessions() as db, db.begin():
                db.add(
                    Organisation(
                        tenant_id=setup.state.tenant_id,
                        created_by_person_id=setup.state.person_id,
                        creation_command_id=uuid4(),
                        domain_verification_token="fictional-token-" * 4,
                    )
                )
                service = store(setup, db)
                row = await service.ensure_detected(setup.state.actor, call)
                identifier = row.id
                await service.edit_fields(
                    setup.state.actor,
                    identifier,
                    fields={"business": {"kind": "text", "text": "Person's Company"}},
                    expected_revision=2,
                )
                assert (await service.read(other.actor, identifier)).id == identifier
                assert await service.read_memberships(other.actor, identifier) == []
                await service.confirm_link(
                    other.actor, other_call, identifier, expected_membership_id=None
                )
                setup.clock[0] += timedelta(seconds=1)
                await service.record_detected(
                    other.actor,
                    identifier,
                    submission_id=other_call,
                    fields={"business": {"kind": "text", "text": "Fictional Studio"}},
                    evidence={"business": ref},
                    extractor_revision="prospect-profile/1",
                )
            async with client_for(setup) as client:
                fields = (await client.get(f"{PREFIX}/{identifier}")).json()["prospect"][
                    "profile_fields"
                ]
                assert fields["business"]["value"]["text"] == "Person's Company"
                assert fields["business"]["locked"]
                # The owning rep cannot see another member's private call quotes.
                assert "heard_differently" not in fields["business"]
            async with setup.sessions() as db:
                rows = (
                    await db.scalars(
                        select(ConversationProspectMembership).where(
                            ConversationProspectMembership.prospect_id == identifier
                        )
                    )
                ).all()
                assert len(rows) == 2
                assert (await verify_audit_chain(db, setup.state.tenant_id)).valid
        finally:
            await setup.engine.dispose()

    run(exercise())


def test_profile_step_writes_observed_fields_without_changing_c5_and_hides_marked_sources(
    postgres_harness: Any, tmp_path: Path
) -> None:
    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path)
        try:
            call = await direct_call(setup)
            ref = await sales_c5(setup, call)
            async with setup.sessions() as db, db.begin():
                service = store(setup, db)
                row = await service.ensure_detected(setup.state.actor, call)
                identifier = row.id
                scope = await service._write_scope(setup.state.actor, call)
                checkpoints = (
                    await db.scalars(
                        select(ConversationCheckpoint).where(
                            ConversationCheckpoint.recording_id == scope.recording_id,
                            ConversationCheckpoint.stage.in_(("C2", "C5")),
                        )
                    )
                ).all()
                c5 = next(item for item in checkpoints if item.stage == "C5")
                transcript = next(item.payload for item in checkpoints if item.stage == "C2")
                before = content_hash(c5.payload)
                requests: list[object] = []

                class Broker:
                    async def quote(self, request: Any) -> Decimal:
                        requests.append(request)
                        return Decimal("0.001")

                    async def extract(
                        self, request: Any, *, maximum_cost_usd: Decimal
                    ) -> ProfileResponse:
                        assert maximum_cost_usd == Decimal("0.001")
                        return ProfileResponse(
                            json.dumps(
                                {
                                    "version": request["version"],
                                    "source_sha256": request["source_sha256"],
                                    "transcript_revision": request["transcript_revision"],
                                    "fields": {
                                        "main_pain": {
                                            "value": {
                                                "kind": "text",
                                                "text": "want to discuss the offer",
                                            },
                                            "evidence": ref,
                                        }
                                    },
                                }
                            ),
                            Decimal("0.0005"),
                        )

                async def write(**values: Any) -> None:
                    await service.record_detected(
                        setup.state.actor, identifier, submission_id=call, **values
                    )

                report = ReportDraft.model_validate(c5.payload)
                disabled = await extract_prospect_profile(
                    policy=ProfilePolicy(),
                    report=report,
                    transcript=transcript,
                    customer_call=True,
                    broker=Broker(),
                    write_detected=write,
                )
                assert disabled.state == "disabled" and not requests
                result = await extract_prospect_profile(
                    policy=ProfilePolicy(True, Decimal("0.002")),
                    report=report,
                    transcript=transcript,
                    customer_call=True,
                    broker=Broker(),
                    write_detected=write,
                )
                assert result.state == "done" and result.field_count == 1 and len(requests) == 1
                assert content_hash(c5.payload) == before
            async with client_for(setup) as client:
                profile = (await client.get(f"{PREFIX}/{identifier}")).json()["prospect"][
                    "profile_fields"
                ]
                assert profile["main_pain"]["value"]["text"] == "want to discuss the offer"
                assert not profile["main_pain"]["locked"]
            async with setup.sessions() as db, db.begin():
                await SensitiveSegmentsStore(db).mark(
                    setup.state.actor,
                    recording_id=scope.recording_id,
                    transcript_revision=transcript["revision"],
                    segments=[(ref["segment_id"], "SENSITIVE_FINANCIAL")],
                    reason_ref="AUT-1677",
                    idempotency_key="fictional-detection-privacy",
                )
            async with client_for(setup) as client:
                profile = (await client.get(f"{PREFIX}/{identifier}")).json()["prospect"][
                    "profile_fields"
                ]
                assert profile["main_pain"]["state"] == "unknown"
                assert profile["business"]["state"] == "unknown"
            # Withheld purpose evidence cannot create another detected identity.
            async with setup.sessions() as db, db.begin():
                rec = await db.get(ConversationRecording, scope.recording_id)
                from ac_platform.conversation_intelligence.prospect_library import ProspectLibrary

                snapshots = await ProspectLibrary(store(setup, db))._snapshots(
                    [rec], include_facts=True
                )
                assert not snapshots[rec.id]["customer_call"]
        finally:
            await setup.engine.dispose()

    run(exercise())


def test_changed_field_comes_from_append_only_history_and_loses_withheld_previous_evidence(
    postgres_harness: Any, tmp_path: Path
) -> None:
    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path)
        try:
            first = await direct_call(setup)
            old_ref = await sales_c5(setup, first)
            async with setup.sessions() as db, db.begin():
                row = await store(setup, db).ensure_detected(setup.state.actor, first)
                identifier = row.id
                scope = await store(setup, db)._write_scope(setup.state.actor, first)
            setup.clock[0] += timedelta(seconds=1)
            second = await direct_call(setup)
            ref = await sales_c5(setup, second, company="Fictional Studio Two")
            async with setup.sessions() as db, db.begin():
                service = store(setup, db)
                await service.confirm_link(
                    setup.state.actor, second, identifier, expected_membership_id=None
                )
                await service.record_detected(
                    setup.state.actor,
                    identifier,
                    submission_id=second,
                    fields={"business": {"kind": "text", "text": "Fictional Studio Two"}},
                    evidence={"business": ref},
                    extractor_revision="prospect-profile/1",
                )
            async with client_for(setup) as client:
                field = (await client.get(f"{PREFIX}/{identifier}")).json()["prospect"][
                    "profile_fields"
                ]["business"]
                assert field["value"]["text"] == "Fictional Studio Two"
                assert field["changed_from"]["value"]["text"] == "Fictional Studio"
                assert field["changed_from"]["evidence"]["submission_id"] == str(first)
            async with setup.sessions() as db, db.begin():
                await SensitiveSegmentsStore(db).mark(
                    setup.state.actor,
                    recording_id=scope.recording_id,
                    transcript_revision=f"fictional-{first}",
                    segments=[(old_ref["segment_id"], "SENSITIVE_FINANCIAL")],
                    reason_ref="AUT-1677",
                    idempotency_key="fictional-previous-value-privacy",
                )
            async with client_for(setup) as client:
                field = (await client.get(f"{PREFIX}/{identifier}")).json()["prospect"][
                    "profile_fields"
                ]["business"]
                assert field["state"] == "unknown" or "changed_from" not in field
                # Native-source withholding may also cover repeated quote grams.
                assert "Fictional Studio" not in json.dumps(field.get("changed_from"))
        finally:
            await setup.engine.dispose()

    run(exercise())
