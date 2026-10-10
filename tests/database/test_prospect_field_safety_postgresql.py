"""Fictional tenant collisions and deterministic field-edit/safety lock races."""

import asyncio
from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from sqlalchemy import event, select, text, update

from ac_platform.audit.models import AuditEvent
from ac_platform.audit.service import verify_audit_chain
from ac_platform.conversation_intelligence.checkpoints import build_checkpoint, content_hash
from ac_platform.conversation_intelligence.guest_models import ConversationGuestSubmission
from ac_platform.conversation_intelligence.inference import binding_for
from ac_platform.conversation_intelligence.models import (
    ConversationCheckpoint,
    ConversationRecording,
)
from ac_platform.conversation_intelligence.prospect_models import ConversationProspectFieldRevision
from ac_platform.conversation_intelligence.prospect_store import ProspectStore
from ac_platform.conversation_intelligence.sensitive_segment_models import (
    ConversationSensitiveSegmentMark,
)
from ac_platform.conversation_intelligence.sensitive_segments_store import SensitiveSegmentsStore
from tests.database.test_conversation_postgresql import postgres_harness as _postgres_harness
from tests.database.test_conversation_postgresql import run, seed, wait_blocked
from tests.database.test_conversation_submission_http_postgresql import _setup
from tests.database.test_prospect_fields_postgresql import value
from tests.database.test_prospect_library_postgresql import snapshot
from tests.database.test_prospect_profile_edit_postgresql import PREFIX, client_for, private
from tests.database.test_prospect_store_postgresql import direct_call, store


@pytest.fixture
def postgres_harness() -> Any:
    yield from cast(Any, _postgres_harness).__wrapped__()


async def detected_prospect(setup: Any, call: UUID) -> Any:
    await snapshot(setup, call)
    async with setup.sessions() as db, db.begin():
        service = store(setup, db)
        prospect = await service.create_from_call(
            setup.state.actor, call, display_name="Fictional Safety Prospect"
        )
        link = await db.get(ConversationGuestSubmission, (setup.state.tenant_id, call))
        checkpoint = await db.scalar(
            select(ConversationCheckpoint).where(
                ConversationCheckpoint.tenant_id == setup.state.tenant_id,
                ConversationCheckpoint.recording_id == link.recording_id,
                ConversationCheckpoint.stage == "C2",
            )
        )
        segment = checkpoint.payload["segments"][0]
        evidence = {
            "segment_id": segment["id"],
            "quote": segment["text"],
            "start_ms": segment["start_ms"],
            "end_ms": segment["end_ms"],
        }
        await service.record_detected(
            setup.state.actor,
            prospect.id,
            submission_id=call,
            fields={"business": value("Fictional Heard Business")},
            evidence={"business": evidence},
            extractor_revision="prospect-profile/1",
        )
        return prospect.id, link.recording_id, checkpoint, evidence


def test_colliding_submission_and_transcript_do_not_load_or_supply_foreign_evidence(
    postgres_harness: Any, tmp_path: Path, monkeypatch: Any
) -> None:
    import tests.database.test_prospect_store_postgresql as fixtures

    async def exercise() -> None:
        own_path, foreign_path = tmp_path / "own", tmp_path / "foreign"
        own_path.mkdir()
        foreign_path.mkdir()
        own = await _setup(postgres_harness, own_path)
        foreign = await _setup(postgres_harness, foreign_path)
        try:
            collision = uuid4()
            with monkeypatch.context() as patch:
                patch.setattr(fixtures, "uuid4", lambda: collision)
                call = await direct_call(own)
            identifier, recording_id, checkpoint, evidence = await detected_prospect(own, call)
            with monkeypatch.context() as patch:
                patch.setattr(fixtures, "uuid4", lambda: collision)
                assert await direct_call(foreign) == call
            async with foreign.sessions() as db, db.begin():
                link = await db.get(
                    ConversationGuestSubmission, (foreign.state.tenant_id, collision)
                )
                foreign_recording = await db.get(ConversationRecording, link.recording_id)
                binding = binding_for(foreign_recording)
                c0 = build_checkpoint(
                    binding, "C0", "fictional-collision/1", {}, [], content_hash({})
                )
                c2 = build_checkpoint(
                    binding,
                    "C2",
                    "fictional-collision/1",
                    {},
                    [c0],
                    content_hash(checkpoint.payload),
                )
                db.add(
                    ConversationCheckpoint(
                        id=uuid4(),
                        tenant_id=foreign.state.tenant_id,
                        person_id=foreign_recording.person_id,
                        recording_id=foreign_recording.id,
                        stage="C2",
                        cache_key=c2.cache_key,
                        manifest_sha256=c2.manifest_sha256,
                        payload_sha256=c2.payload_sha256,
                        feature_blob_id=None,
                        manifest=c2.as_dict(),
                        payload=checkpoint.payload,
                        created_at=foreign.clock[0],
                    )
                )
            loaded: list[Any] = []
            async with own.sessions() as db, db.begin():
                event.listen(
                    db.sync_session, "loaded_as_persistent", lambda _, row: loaded.append(row)
                )
                service = store(own, db)
                rows = await service.field_rows(
                    own.state.actor, [identifier], await service.queries(own.state.actor)
                )
                detected = [r for r in rows if r.basis == "heard_in_call"]
                assert len(detected) == 1 and detected[0].value == value("Fictional Heard Business")
                source_types = (ConversationRecording, ConversationCheckpoint)
                sources = [r for r in loaded if isinstance(r, source_types)]
                assert any(isinstance(r, ConversationRecording) for r in sources)
                assert any(isinstance(r, ConversationCheckpoint) for r in sources)
                assert all(r.tenant_id == own.state.tenant_id for r in sources)
                # The source helper also rejects an accidentally supplied foreign recording.
                loaded.clear()
                own_recording = await db.get(ConversationRecording, recording_id)
                sources_by_recording = await service._field_sources(
                    [own_recording, foreign_recording]
                )
                assert set(sources_by_recording) == {(own.state.tenant_id, recording_id)}
                assert all(r.tenant_id == own.state.tenant_id for r in loaded)
            async with client_for(own) as client:
                response = await client.get(f"{PREFIX}/{identifier}")
                private(response, 200)
                assert response.json()["prospect"]["profile_fields"]["business"]["basis"] == (
                    "heard_in_call"
                )
            async with foreign.sessions() as db, db.begin():
                marks = await SensitiveSegmentsStore(db).mark(
                    foreign.state.actor,
                    recording_id=foreign_recording.id,
                    transcript_revision=checkpoint.payload["revision"],
                    segments=[(evidence["segment_id"], "SENSITIVE_FINANCIAL")],
                    reason_ref="AUT-1585",
                    idempotency_key="fictional-foreign-collision",
                )
            # ADR 0051 keeps ID-only marks effective across shared transcripts,
            # while neither the foreign recording nor its checkpoint is loaded.
            async with own.sessions() as db, db.begin():
                loaded.clear()
                event.listen(
                    db.sync_session, "loaded_as_persistent", lambda _, row: loaded.append(row)
                )
                service = store(own, db)
                rows = await service.field_rows(
                    own.state.actor, [identifier], await service.queries(own.state.actor)
                )
                assert not any(r.basis == "heard_in_call" for r in rows)
                assert any(isinstance(r, ConversationSensitiveSegmentMark) for r in loaded)
                assert all(
                    r.tenant_id == own.state.tenant_id
                    for r in loaded
                    if isinstance(r, (ConversationRecording, ConversationCheckpoint))
                )
            async with foreign.sessions() as db, db.begin():
                await SensitiveSegmentsStore(db).release(
                    foreign.state.actor,
                    mark_id=marks[0].id,
                    reason_ref="AUT-1585",
                    idempotency_key="fictional-foreign-release",
                )
            async with own.sessions() as db, db.begin():
                await db.execute(
                    update(ConversationCheckpoint)
                    .where(ConversationCheckpoint.id == checkpoint.id)
                    .values(erased_at=own.clock[0], payload=None, manifest=None)
                )
            async with client_for(own) as client:
                response = await client.get(f"{PREFIX}/{identifier}")
                private(response, 200)
                assert response.json()["prospect"]["profile_fields"]["business"]["state"] == (
                    "unknown"
                )
        finally:
            await own.engine.dispose()
            await foreign.engine.dispose()

    run(exercise())


@pytest.mark.parametrize("first", ["put", "mark"])
def test_field_put_and_sensitive_mark_both_commit_and_withhold_evidence(
    postgres_harness: Any, tmp_path: Path, monkeypatch: Any, first: str
) -> None:
    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path)
        tasks: list[asyncio.Task[Any]] = []
        release = asyncio.Event()
        try:
            call = await direct_call(setup)
            identifier, recording_id, checkpoint, evidence = await detected_prospect(setup, call)
            # Safety writes come from a named operator, with independent identity
            # fences. Reusing PUT's session in a bare store call would bypass the
            # operator HTTP resolver and introduce an unrelated identity/FK cycle.
            operator = await seed(setup.engine, tenant_id=setup.state.tenant_id)
            paused = asyncio.Event()
            second_pid: asyncio.Future[int] = asyncio.get_running_loop().create_future()
            original_audit = ProspectStore._audit
            original_receipt = SensitiveSegmentsStore._request_receipt
            original_fields = ProspectStore.field_rows

            async def pause_put(self: Any, *args: Any, **kwargs: Any) -> None:
                await original_audit(self, *args, **kwargs)
                if first == "put" and args[2] == "fields_changed":
                    paused.set()
                    await asyncio.wait_for(release.wait(), 10)

            async def pause_mark(self: Any, *args: Any, **kwargs: Any) -> Any:
                if first == "mark":
                    paused.set()
                    await asyncio.wait_for(release.wait(), 10)
                return await original_receipt(self, *args, **kwargs)

            async def observe_put(self: Any, *args: Any, **kwargs: Any) -> Any:
                if first == "mark" and not second_pid.done():
                    second_pid.set_result(
                        await self.database.scalar(text("SELECT pg_backend_pid()"))
                    )
                return await original_fields(self, *args, **kwargs)

            monkeypatch.setattr(ProspectStore, "_audit", pause_put)
            monkeypatch.setattr(SensitiveSegmentsStore, "_request_receipt", pause_mark)
            monkeypatch.setattr(ProspectStore, "field_rows", observe_put)

            async def mark() -> None:
                async with setup.sessions() as db, db.begin():
                    if first == "put":
                        second_pid.set_result(await db.scalar(text("SELECT pg_backend_pid()")))
                    await SensitiveSegmentsStore(db).mark(
                        operator.actor,
                        recording_id=recording_id,
                        transcript_revision=checkpoint.payload["revision"],
                        segments=[(evidence["segment_id"], "SENSITIVE_FINANCIAL")],
                        reason_ref="AUT-1585",
                        idempotency_key="fictional-profile-lock-race",
                    )

            async with client_for(setup) as client:

                async def put() -> Any:
                    return await client.put(
                        f"{PREFIX}/{identifier}/fields",
                        json={"expected_revision": 2, "fields": {"city": value("Jaipur")}},
                    )

                commands = {"put": put, "mark": mark}
                tasks.append(asyncio.create_task(commands[first]()))
                await asyncio.wait_for(paused.wait(), 10)
                tasks.append(asyncio.create_task(commands["mark" if first == "put" else "put"]()))
                await wait_blocked(setup.engine, await asyncio.wait_for(second_pid, 5), tasks[1])
                release.set()
                outcomes = await asyncio.wait_for(asyncio.gather(*tasks), 15)
                response = outcomes[0 if first == "put" else 1]
                private(response, 200)
                fields = response.json()["prospect"]["profile_fields"]
                assert fields["city"]["value"] == value("Jaipur") and fields["city"]["locked"]
                assert fields["business"]["state"] == ("known" if first == "put" else "unknown")
                later = await client.get(f"{PREFIX}/{identifier}")
                private(later, 200)
                fields = later.json()["prospect"]["profile_fields"]
                assert fields["business"]["state"] == "unknown"
                assert fields["city"]["value"] == value("Jaipur") and fields["city"]["locked"]
                assert "heard_differently" not in fields["business"]
            async with setup.sessions() as db:
                assert len((await db.scalars(select(ConversationSensitiveSegmentMark))).all()) == 1
                assert len((await db.scalars(select(ConversationProspectFieldRevision))).all()) == 3
                actions = (await db.scalars(select(AuditEvent.action))).all()
                assert actions.count("conversation.prospect_fields_changed") == 1
                assert actions.count("conversation.sensitive_segment.mark") == 1
                assert (await verify_audit_chain(db, setup.state.tenant_id)).valid
            print(
                f"field PUT/sensitive mark ({first} first): both committed; later evidence withheld"
            )
        finally:
            release.set()
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            await setup.engine.dispose()

    run(exercise())
