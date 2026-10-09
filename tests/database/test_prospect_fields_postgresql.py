"""Fictional profile revisions, HTTP concurrency and source containment."""

import asyncio
import subprocess
from datetime import timedelta
from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import MetaData, Table, delete, event, select, text, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import registry

from ac_platform.audit.models import AuditEvent
from ac_platform.audit.service import verify_audit_chain
from ac_platform.conversation_intelligence import guest_models, guest_ownership
from ac_platform.conversation_intelligence.application import ConversationError
from ac_platform.conversation_intelligence.guest_models import ConversationGuestSubmission
from ac_platform.conversation_intelligence.models import (
    ConversationCheckpoint,
    ConversationRecording,
)
from ac_platform.conversation_intelligence.prospect_models import (
    ConversationProspect,
)
from ac_platform.conversation_intelligence.prospect_models import (
    ConversationProspectFieldRevision as FieldRevision,
)
from ac_platform.conversation_intelligence.prospect_report_context import previous_call_context
from ac_platform.conversation_intelligence.prospect_store import ProspectStore
from ac_platform.conversation_intelligence.sensitive_segments_store import SensitiveSegmentsStore
from ac_platform.db.models import model_metadata
from tests.database.test_conversation_postgresql import postgres_harness as _postgres_harness
from tests.database.test_conversation_postgresql import run, seed
from tests.database.test_conversation_submission_http_postgresql import _setup
from tests.database.test_prospect_library_postgresql import snapshot
from tests.database.test_prospect_profile_edit_postgresql import PREFIX, client_for, private
from tests.database.test_prospect_store_postgresql import direct_call, store


@pytest.fixture
def postgres_harness() -> Any:
    yield from cast(Any, _postgres_harness).__wrapped__()


def value(text_value: str) -> dict[str, str]:
    return {"kind": "text", "text": text_value}


async def saved(setup: Any, identifier: str) -> Any:
    async with setup.sessions() as db:
        row = await db.get(ConversationProspect, UUID(identifier))
        revisions = (await db.scalars(select(FieldRevision).order_by(FieldRevision.revision))).all()
        events = (await db.scalars(select(AuditEvent).order_by(AuditEvent.sequence_no))).all()
        return (
            row.revision,
            [(r.id, r.value, r.supersedes_id) for r in revisions],
            [(e.id, e.event_hash) for e in events],
        )


def test_put_persistence_noop_stale_race_denials_rollback_and_queries(
    postgres_harness: Any, tmp_path: Path, monkeypatch: Any
) -> None:
    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path)
        statements: list[str] = []

        def count(*args: Any) -> None:
            statements.append(args[2])

        try:
            call = await direct_call(setup)
            async with client_for(setup) as client:
                created = await client.post(
                    f"{PREFIX}/calls/{call}/create", json={"display_name": "Fictional Person"}
                )
                identifier = created.json()["membership"]["prospect_id"]
                path = f"{PREFIX}/{identifier}"
                fields = {
                    "business": value("Fictional Ltd"),
                    "city": value("Jaipur"),
                    "phone": value("+15555550123"),
                    "email": value("fictional@example.test"),
                }
                response = await client.put(
                    path + "/fields", json={"expected_revision": 1, "fields": fields}
                )
                private(response, 200)
                profile = response.json()["prospect"]["profile_fields"]
                assert len(profile) == 14
                assert profile["industry"] == {"state": "unknown", "reason": "not_asked"}
                assert profile["city"] == {
                    "state": "known",
                    "value": fields["city"],
                    "basis": "person",
                    "locked": True,
                    "set_by": str(setup.state.person_id),
                    "set_at": setup.clock[0].isoformat(),
                }
                assert (await client.get(path)).json()["prospect"]["profile_fields"] == profile
                async with client_for(setup) as second_client:
                    assert (await second_client.get(path)).json()["prospect"][
                        "profile_fields"
                    ] == profile
                assert (await client.get(PREFIX)).json()["prospects"][0][
                    "profile_fields"
                ] == profile
                before = await saved(setup, identifier)
                private(
                    await client.put(
                        path + "/fields", json={"expected_revision": 2, "fields": fields}
                    ),
                    200,
                )
                private(
                    await client.put(
                        path + "/fields", json={"expected_revision": 1, "fields": fields}
                    ),
                    409,
                )
                assert await saved(setup, identifier) == before
                races = await asyncio.gather(
                    *[
                        client.put(
                            path + "/fields",
                            json={"expected_revision": 2, "fields": {"city": value(name)}},
                        )
                        for name in ("Delhi", "Mumbai")
                    ]
                )
                assert sorted(r.status_code for r in races) == [200, 409]
                winner = next(r.json()["prospect"] for r in races if r.status_code == 200)
                assert (await client.get(path)).json()["prospect"]["profile_fields"] == winner[
                    "profile_fields"
                ]
                for fields_value in (
                    {},
                    {"city": None},
                    {"city": value(" ")},
                    {"fake": value("x")},
                    {"city": {"kind": "text", "text": "x", "tenant_id": str(uuid4())}},
                ):
                    private(
                        await client.put(
                            path + "/fields", json={"expected_revision": 3, "fields": fields_value}
                        ),
                        422,
                    )
                private(
                    await client.put(
                        path + "/fields?workspace=other",
                        json={"expected_revision": 3, "fields": fields},
                    ),
                    422,
                )
                private(
                    await client.put(
                        path + "/fields", json={"expected_revision": True, "fields": fields}
                    ),
                    422,
                )
                private(
                    await client.put(
                        path + "/fields",
                        json={"expected_revision": 3, "fields": fields},
                        headers={"Origin": "https://evil.example.test"},
                    ),
                    403,
                )
                for other in (
                    await seed(setup.engine),
                    await seed(setup.engine, tenant_id=setup.state.tenant_id),
                ):
                    async with setup.sessions() as db, db.begin():
                        other_row = ConversationProspect(
                            id=uuid4(),
                            tenant_id=other.tenant_id,
                            display_name="Foreign Fictional",
                            created_by_person_id=other.person_id,
                            owner_person_id=other.person_id,
                            revision=1,
                            created_at=setup.clock[0],
                            updated_at=setup.clock[0],
                        )
                        db.add(other_row)
                    private(
                        await client.put(
                            f"{PREFIX}/{other_row.id}/fields",
                            json={"expected_revision": 1, "fields": fields},
                        ),
                        404,
                    )
                stable = await saved(setup, identifier)

                async def fail_audit(*args: Any, **kwargs: Any) -> None:
                    raise RuntimeError("Fictional audit failure")

                with monkeypatch.context() as patch:
                    patch.setattr(ProspectStore, "_audit", fail_audit)
                    with pytest.raises(RuntimeError, match="Fictional audit failure"):
                        await client.put(
                            path + "/fields",
                            json={"expected_revision": 3, "fields": {"city": value("Rollback")}},
                        )
                assert await saved(setup, identifier) == stable
                event.listen(setup.engine.sync_engine, "before_cursor_execute", count)
                measurements = []
                for size, revision in ((1, 3), (20, 4)):
                    if size == 20:
                        for _ in range(19):
                            extra = await direct_call(setup)
                            async with setup.sessions() as db, db.begin():
                                await store(setup, db).confirm_link(
                                    setup.state.actor,
                                    extra,
                                    UUID(identifier),
                                    expected_membership_id=None,
                                )
                    statements.clear()
                    private(
                        await client.put(
                            path + "/fields",
                            json={
                                "expected_revision": revision,
                                "fields": {"city": value(f"Fictional {size}")},
                            },
                        ),
                        200,
                    )
                    writes = len(statements)
                    statements.clear()
                    private(await client.get(path), 200)
                    measurements.append((writes, len(statements)))
                assert measurements[0] == measurements[1]
                print(f"field PUT/detail SQL statements (1/20 calls): {measurements}")
                async with setup.sessions() as db:
                    events = (
                        await db.scalars(
                            select(AuditEvent).where(
                                AuditEvent.action == "conversation.prospect_fields_changed"
                            )
                        )
                    ).all()
                    assert len(events) == 4
                    for change in events:
                        assert set(change.payload) == {
                            "field_count",
                            "previous_revision",
                            "current_revision",
                        }
                    assert (await verify_audit_chain(db, setup.state.tenant_id)).valid
                    context = await previous_call_context(
                        store(setup, db).ownership,
                        setup.state.actor,
                        call,
                        report_created_at=setup.clock[0],
                    )
                    assert "phone" not in str(context) and "email" not in str(context)
                    assert "+15555550123" not in str(
                        context
                    ) and "fictional@example.test" not in str(context)
        finally:
            if event.contains(setup.engine.sync_engine, "before_cursor_execute", count):
                event.remove(setup.engine.sync_engine, "before_cursor_execute", count)
            await setup.engine.dispose()

    run(exercise())


def test_detected_person_lock_disagreement_source_and_history_guards(
    postgres_harness: Any, tmp_path: Path
) -> None:
    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path)
        try:
            call = await direct_call(setup)
            await snapshot(setup, call)
            async with setup.sessions() as db, db.begin():
                service = store(setup, db)
                prospect = await service.create_from_call(
                    setup.state.actor, call, display_name="Fictional Prospect"
                )
                identifier = prospect.id
                link = await db.get(ConversationGuestSubmission, (setup.state.tenant_id, call))
                recording_id = link.recording_id
                checkpoint = await db.scalar(
                    select(ConversationCheckpoint).where(
                        ConversationCheckpoint.recording_id == recording_id,
                        ConversationCheckpoint.stage == "C2",
                    )
                )
                segment = checkpoint.payload["segments"][0]
                ref = {
                    "segment_id": segment["id"],
                    "quote": segment["text"],
                    "start_ms": segment["start_ms"],
                    "end_ms": segment["end_ms"],
                }
                transcript_revision = checkpoint.payload["revision"]
                await service.record_detected(
                    setup.state.actor,
                    identifier,
                    submission_id=call,
                    fields={"business": value("Heard Example"), "city": value("Heard City")},
                    evidence={"business": ref, "city": ref},
                    extractor_revision="prospect-profile/1",
                )
            async with client_for(setup) as client:
                path = f"{PREFIX}/{identifier}"
                detected = (await client.get(path)).json()["prospect"]["profile_fields"]
                assert (
                    detected["business"]["basis"] == "heard_in_call"
                    and not detected["business"]["locked"]
                )
                assert detected["business"]["evidence"]["submission_id"] == str(call)
                private(
                    await client.put(
                        path + "/fields",
                        json={
                            "expected_revision": 2,
                            "fields": {"business": value("Person Example")},
                        },
                    ),
                    200,
                )
                setup.clock[0] += timedelta(seconds=1)
                async with setup.sessions() as db, db.begin():
                    await store(setup, db).record_detected(
                        setup.state.actor,
                        identifier,
                        submission_id=call,
                        fields={"business": value("Heard Differently")},
                        evidence={"business": ref},
                        extractor_revision="prospect-profile/1",
                    )
                locked = (await client.get(path)).json()["prospect"]["profile_fields"]["business"]
                assert locked["value"] == value("Person Example") and locked["locked"]
                assert locked["heard_differently"][0]["value"] == value("Heard Differently")
                for kwargs in (
                    {"fields": {"phone": value("private")}, "evidence": {"phone": ref}},
                    {
                        "fields": {"city": value("Invalid")},
                        "evidence": {"city": {**ref, "quote": "not in transcript"}},
                    },
                    {"fields": {"city": value("Invalid")}, "evidence": {}},
                ):
                    async with setup.sessions() as db, db.begin():
                        with pytest.raises(ConversationError):
                            await store(setup, db).record_detected(
                                setup.state.actor,
                                identifier,
                                submission_id=call,
                                extractor_revision="prospect-profile/1",
                                **kwargs,
                            )
                async with setup.sessions() as db, db.begin():
                    await SensitiveSegmentsStore(db).mark(
                        setup.state.actor,
                        recording_id=recording_id,
                        transcript_revision=transcript_revision,
                        segments=[(ref["segment_id"], "SENSITIVE_FINANCIAL")],
                        reason_ref="AUT-1585",
                        idempotency_key="fictional-profile-mark",
                    )
                withheld = (await client.get(path)).json()["prospect"]["profile_fields"]
                assert (
                    withheld["business"]["value"] == value("Person Example")
                    and "heard_differently" not in withheld["business"]
                )
                assert withheld["city"]["state"] == "unknown"
                async with setup.sessions() as db, db.begin():
                    await db.execute(
                        update(ConversationRecording)
                        .where(ConversationRecording.id == recording_id)
                        .values(state="deleted")
                    )
                assert (await client.get(path)).json()["prospect"]["profile_fields"]["city"][
                    "state"
                ] == "unknown"
                for statement in (
                    delete(FieldRevision).where(FieldRevision.entity_id == identifier),
                    update(FieldRevision)
                    .where(FieldRevision.entity_id == identifier)
                    .values(state="detected"),
                ):
                    async with setup.sessions() as db, db.begin():
                        with pytest.raises(DBAPIError, match="preserve history"):
                            async with db.begin_nested():
                                await db.execute(statement)
        finally:
            await setup.engine.dispose()

    run(exercise())


def test_populated_0077_upgrade_preserves_prospects_links_tags_and_audit(
    tmp_path: Path, monkeypatch: Any
) -> None:
    original = subprocess.run
    invocation: list[Any] = []

    def parent_first(args: Any, **kwargs: Any) -> Any:
        if args[-1] == "head":
            invocation[:] = [args, kwargs]
            args = [*args[:-1], "20261007_0077"]
        return original(args, **kwargs)

    harness = cast(Any, _postgres_harness).__wrapped__()
    with monkeypatch.context() as patch:
        patch.setattr(subprocess, "run", parent_first)
        engine = next(harness)

    # Populate 0077 with its historical submission mapping; capture_source arrives
    # in companion-device 0078 before the prospect-field 0079 migration.
    legacy_registry = registry()
    legacy_table = Table("conversation_guest_submissions", MetaData(), autoload_with=engine)

    class LegacySubmission:
        pass

    legacy_registry.map_imperatively(LegacySubmission, legacy_table)

    async def populate() -> tuple[Any, UUID, Any]:
        setup = await _setup(engine, tmp_path)
        call, identifier, membership = await direct_call(setup), uuid4(), uuid4()
        async with setup.sessions() as db, db.begin():
            await db.execute(
                text(
                    "INSERT INTO conversation_prospects (id, tenant_id, display_name, "
                    "created_by_person_id, owner_person_id, revision, created_at, updated_at, "
                    "tags) VALUES (:id, :tenant, 'Legacy Fictional', :person, :person, "
                    "4, :now, :now, '[\"QA\"]')"
                ),
                {
                    "id": identifier,
                    "tenant": setup.state.tenant_id,
                    "person": setup.state.person_id,
                    "now": setup.clock[0],
                },
            )
            await db.execute(
                text(
                    "INSERT INTO conversation_prospect_memberships (id, tenant_id, "
                    "prospect_id, submission_id, linked_by_person_id, created_at) "
                    "VALUES (:id, :tenant, :prospect, :call, :person, :now)"
                ),
                {
                    "id": membership,
                    "tenant": setup.state.tenant_id,
                    "prospect": identifier,
                    "call": call,
                    "person": setup.state.person_id,
                    "now": setup.clock[0],
                },
            )
            await store(setup, db)._audit(
                setup.state.actor, identifier, "created", {}, setup.clock[0]
            )
        async with setup.sessions() as db:
            row = (
                (
                    await db.execute(
                        text("SELECT * FROM conversation_prospects WHERE id=:id"),
                        {"id": identifier},
                    )
                )
                .mappings()
                .one()
            )
            links = (
                (await db.execute(text("SELECT * FROM conversation_prospect_memberships")))
                .mappings()
                .all()
            )
            audit = (await db.execute(select(AuditEvent.id, AuditEvent.event_hash))).all()
            preserved = dict(row), [dict(link) for link in links], audit
        await setup.engine.dispose()
        return setup, identifier, preserved

    try:
        with monkeypatch.context() as patch:
            patch.setattr(guest_models, "ConversationGuestSubmission", LegacySubmission)
            patch.setattr(guest_ownership, "ConversationGuestSubmission", LegacySubmission)
            _setup_result, identifier, preserved = run(populate())
        migrated = original(invocation[0], **invocation[1])
        if migrated.returncode:
            pytest.fail(
                "Isolated 0079 migration failed; environment/output withheld.", pytrace=False
            )
        with engine.connect() as db:
            assert db.scalar(text("SELECT version_num FROM alembic_version")) == "20261009_0079"
            assert compare_metadata(MigrationContext.configure(db), model_metadata()) == []
            row = dict(
                db.execute(
                    text("SELECT * FROM conversation_prospects WHERE id=:id"), {"id": identifier}
                )
                .mappings()
                .one()
            )
            assert row.pop("origin") == "person"
            assert row.pop("confirmed_at") is row.pop("confirmed_by_person_id") is None
            assert row == preserved[0]
            links = [
                dict(link)
                for link in db.execute(text("SELECT * FROM conversation_prospect_memberships"))
                .mappings()
                .all()
            ]
            assert all(link.pop("link_kind") == "person" for link in links)
            assert links == preserved[1]
            assert list(db.execute(select(AuditEvent.id, AuditEvent.event_hash))) == preserved[2]
            revision = db.execute(select(FieldRevision.__table__)).mappings().one()
            assert revision["value"] == value("Legacy Fictional") and revision["revision"] == 4
    finally:
        legacy_registry.dispose()
        harness.close()
