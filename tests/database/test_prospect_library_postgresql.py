"""Fictional prospect HTTP proof: aggregation, access, pagination and source notes."""

from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import event, select, update

from ac_platform.conversation_intelligence.checkpoints import build_checkpoint, content_hash
from ac_platform.conversation_intelligence.inference import binding_for, verified_checkpoint
from ac_platform.conversation_intelligence.models import (
    ConversationCheckpoint,
    ConversationPermission,
    ConversationRecording,
)
from ac_platform.conversation_intelligence.prospect_library import SCHEMA
from ac_platform.conversation_intelligence.prospect_models import (
    ConversationProspect,
    ConversationProspectMembership,
)
from ac_platform.conversation_intelligence.reports import parse_report_draft
from ac_platform.conversation_intelligence.sensitive_segments import WITHHELD_MARKER
from ac_platform.conversation_intelligence.sensitive_segments_store import SensitiveSegmentsStore
from tests.conversation_overview_fixtures import overview_for
from tests.database.test_conversation_account_library_postgresql import _session
from tests.database.test_conversation_postgresql import postgres_harness as _postgres_harness
from tests.database.test_conversation_postgresql import run, seed
from tests.database.test_conversation_submission_http_postgresql import ORIGIN, _setup
from tests.database.test_prospect_store_postgresql import direct_call, store
from tests.unit.conversation_intelligence.test_reports import _payload, _transcript

PREFIX = "/v1/conversation/prospects"


@pytest.fixture
def postgres_harness() -> Any:
    yield from cast(Any, _postgres_harness).__wrapped__()


def test_http_pages_search_missing_fields_and_constant_queries(
    postgres_harness: Any, tmp_path: Path
) -> None:
    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path)
        try:
            call = await direct_call(setup)
            async with setup.sessions() as db, db.begin():
                first = await store(setup, db).create_from_call(
                    setup.state.actor, call, display_name="Asha % Example"
                )
                first_id = first.id
            counts: list[int] = []
            statements: list[str] = []

            def count(
                _conn: Any,
                _cursor: Any,
                statement: str,
                _parameters: Any,
                _context: Any,
                _many: Any,
            ) -> None:
                statements.append(statement)

            event.listen(setup.engine.sync_engine, "before_cursor_execute", count)
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=setup.app), base_url=ORIGIN
            ) as client:
                assert (await client.get(PREFIX)).status_code == 401
                client.cookies.set(setup.settings.session_cookie_name, setup.token)
                statements.clear()
                response = await client.get(PREFIX)
                assert response.status_code == 200, response.text
                counts.append(len(statements))
                data = response.json()
                assert data["schema"] == SCHEMA and data["total"] == 1
                row = data["prospects"][0]
                assert row["call_count"] == 1 and row["last_call"] is not None
                assert row["stage"] is None and row["tags"] == []
                assert row["next_step"] is None and row["last_promise"] is None
                assert row["buyer_intent"] is None and row["contact"] is None
                async with setup.sessions() as db, db.begin():
                    for i in range(22):
                        db.add(
                            ConversationProspect(
                                id=uuid4(),
                                tenant_id=setup.state.tenant_id,
                                display_name=f"Fictional {i:02}",
                                created_by_person_id=setup.state.person_id,
                                owner_person_id=setup.state.person_id,
                                revision=1,
                                created_at=setup.state.now,
                                updated_at=setup.state.now,
                            )
                        )
                statements.clear()
                response = await client.get(PREFIX)
                counts.append(len(statements))
                data = response.json()
                assert (
                    data["total"] == 23
                    and len(data["prospects"]) == 20
                    and data["next_offset"] == 20
                )
                page = (await client.get(PREFIX, params={"offset": 20})).json()
                assert len(page["prospects"]) == 3 and page["next_offset"] is None
                assert (await client.get(PREFIX, params={"search": "%"})).json()["total"] == 1
                assert (await client.get(PREFIX, params={"search": "aShA"})).json()["total"] == 1
                assert (await client.get(PREFIX, params={"stage": "invented-stage"})).json()[
                    "prospects"
                ] == []
                assert (await client.get(PREFIX, params={"stage": "__missing__"})).json()[
                    "total"
                ] == 23
                statements.clear()
                detail = await client.get(PREFIX + f"/{first_id}")
                detail_count = len(statements)
                assert detail.status_code == 200, detail.text
                assert len(detail.json()["calls"]) == 1
                assert detail.json()["calls"][0]["score"] is None
                assert detail.json()["calls"][0]["snapshot"] is None
                statements.clear()
                empty = await client.get(PREFIX + f"/{page['prospects'][0]['prospect_id']}")
                assert detail_count == len(statements) and detail_count <= 25
                assert empty.status_code == 200 and empty.json()["calls"] == []
                assert (
                    empty.json()["prospect"]["call_count"] == 0
                    and empty.json()["prospect"]["last_call"] is None
                )
                assert (
                    await client.get(PREFIX, params={"workspace": str(uuid4())})
                ).status_code == 422
                assert (await client.get(PREFIX + "?search=x&search=y")).status_code == 422
                assert (await client.get(PREFIX, params={"offset": -1})).status_code == 422
                assert (await client.get(PREFIX + f"/{uuid4()}")).status_code == 404
                assert (
                    detail.headers["cache-control"] == "private, no-store"
                    and detail.headers["vary"] == "Cookie"
                )
                assert (
                    await client.get("https://learner.example.test" + PREFIX)
                ).status_code == 404
            assert counts[0] == counts[1] and counts[0] <= 20
        finally:
            await setup.engine.dispose()

    run(exercise())


def test_detail_counts_only_visible_active_calls_and_denies_other_workspaces(
    postgres_harness: Any, tmp_path: Path
) -> None:
    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path)
        try:
            own = await direct_call(setup)
            setup.clock[0] += timedelta(seconds=1)
            second = await direct_call(setup)
            other = await seed(setup.engine, tenant_id=setup.state.tenant_id, role="member")
            foreign = await seed(setup.engine)
            hidden = await direct_call(setup, other.actor)
            async with setup.sessions() as db, db.begin():
                service = store(setup, db)
                prospect = await service.create_from_call(
                    setup.state.actor, own, display_name="Shared Example"
                )
                await service.confirm_link(
                    setup.state.actor, second, prospect.id, expected_membership_id=None
                )
                db.add(
                    ConversationProspectMembership(
                        id=uuid4(),
                        tenant_id=setup.state.tenant_id,
                        prospect_id=prospect.id,
                        submission_id=hidden,
                        linked_by_person_id=other.person_id,
                        created_at=setup.state.now,
                    )
                )
                prospect_id = prospect.id
            transport = httpx.ASGITransport(app=setup.app)
            async with httpx.AsyncClient(transport=transport, base_url=ORIGIN) as client:
                client.cookies.set(setup.settings.session_cookie_name, setup.token)
                detail = (await client.get(PREFIX + f"/{prospect_id}")).json()
                assert detail["prospect"]["call_count"] == 2
                assert [c["submission_id"] for c in detail["calls"]] == [str(second), str(own)]
                assert (await client.get(PREFIX + f"/{prospect_id}")).json() == detail
                client.cookies.set(setup.settings.session_cookie_name, await _session(setup, other))
                shared = (await client.get(PREFIX + f"/{prospect_id}")).json()
                assert shared["prospect"]["call_count"] == 1 and shared["calls"][0][
                    "submission_id"
                ] == str(hidden)
                async with setup.sessions() as db, db.begin():
                    await store(setup, db).unlink(
                        other.actor,
                        hidden,
                        expected_membership_id=(
                            await store(setup, db).read_memberships(other.actor, prospect_id)
                        )[0].id,
                    )
                assert (await client.get(PREFIX + f"/{prospect_id}")).status_code == 404
                assert (await client.get(PREFIX)).json()["prospects"] == []
                client.cookies.set(
                    setup.settings.session_cookie_name, await _session(setup, foreign)
                )
                assert (await client.get(PREFIX + f"/{prospect_id}")).status_code in (403, 404)
                client.cookies.set(setup.settings.session_cookie_name, setup.token)
                async with setup.sessions() as db, db.begin():
                    # Select the exact guest-submission binding instead of guessing an identity.
                    from ac_platform.conversation_intelligence.guest_models import (
                        ConversationGuestSubmission,
                    )

                    recording_id = await db.scalar(
                        select(ConversationGuestSubmission.recording_id).where(
                            ConversationGuestSubmission.submission_id == own
                        )
                    )
                    recording = await db.get(ConversationRecording, recording_id)
                    assert recording is not None
                    await db.execute(
                        update(ConversationPermission)
                        .where(ConversationPermission.id == recording.permission_id)
                        .values(revoked_at=setup.state.now)
                    )
                redacted = (await client.get(PREFIX + f"/{prospect_id}")).json()
                assert redacted["prospect"]["call_count"] == 1 and redacted["calls"][0][
                    "submission_id"
                ] == str(second)
        finally:
            await setup.engine.dispose()

    run(exercise())


async def snapshot(setup: Any, submission: UUID) -> UUID:
    from ac_platform.conversation_intelligence.guest_models import ConversationGuestSubmission

    async with setup.sessions() as db, db.begin():
        identifier = await db.scalar(
            select(ConversationGuestSubmission.recording_id).where(
                ConversationGuestSubmission.submission_id == submission
            )
        )
        recording = await db.get(ConversationRecording, identifier)
        assert recording is not None
        transcript = _transcript(count=1)
        transcript["source_sha256"] = recording.source_sha256
        payload = _payload(transcript)
        payload["overview"] = overview_for(payload)
        payload["overview"]["prospect_interpretations"] = [
            {
                "source": {
                    "text": "The buyer asks about timing.",
                    "evidence": payload["strengths"][0]["evidence"],
                },
                "possible_concern": "The buyer may need more time.",
                "interpretation_kind": "inference",
            }
        ]
        report = parse_report_draft(payload, transcript).model_dump(mode="json")
        built = {}
        for stage, parents, value in [
            ("C0", [], {}),
            ("C1", ["C0"], {}),
            ("C2", ["C0"], transcript),
            ("C3", ["C1", "C2"], {}),
            ("C4", ["C2", "C3"], {}),
            ("C5", ["C4"], report),
        ]:
            cp = build_checkpoint(
                binding_for(recording),
                stage,
                "fictional-snapshot-v1",
                {},
                [built[p] for p in parents],
                content_hash(value),
            )
            built[stage] = cp
            row = ConversationCheckpoint(
                id=uuid4(),
                tenant_id=recording.tenant_id,
                person_id=recording.person_id,
                recording_id=recording.id,
                stage=stage,
                cache_key=cp.cache_key,
                manifest_sha256=cp.manifest_sha256,
                payload_sha256=cp.payload_sha256,
                feature_blob_id=None,
                manifest=cp.as_dict(),
                payload=value,
                created_at=setup.state.now,
            )
            db.add(row)
            if stage == "C5":
                checkpoint_id = row.id
        return checkpoint_id


def test_snapshot_interpretations_keep_provenance_and_reject_corruption(
    postgres_harness: Any, tmp_path: Path
) -> None:
    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path)
        try:
            call = await direct_call(setup)
            async with setup.sessions() as db, db.begin():
                prospect = await store(setup, db).create_from_call(
                    setup.state.actor, call, display_name="Snapshot Example"
                )
                prospect_id = prospect.id
            checkpoint_id = await snapshot(setup, call)
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=setup.app), base_url=ORIGIN
            ) as client:
                client.cookies.set(setup.settings.session_cookie_name, setup.token)
                response = await client.get(PREFIX + f"/{prospect_id}")
                assert response.status_code == 200, response.text
                data = response.json()
                source = data["calls"][0]["snapshot"]
                assert (
                    source["snapshot_id"] == str(checkpoint_id) and source["source_revision"] == 1
                )
                assert source["interpretations"][0]["interpretation_kind"] == "inference"
                assert source["interpretations"][0]["source"]["evidence"][0]["quote"]
                assert data["prospect"]["fields"] == [] and data["buyer_intent_history"] == []
                assert data["promises"] == [] and data["next_steps"] == []
                async with setup.sessions() as db, db.begin():
                    await SensitiveSegmentsStore(db).mark(
                        setup.state.actor,
                        recording_id=UUID(data["calls"][0]["recording_id"]),
                        transcript_revision=source["transcript_revision"],
                        segments=[("s1", "SENSITIVE_FINANCIAL")],
                        reason_ref="AUT-1068",
                        idempotency_key="fictional-prospect-sensitive",
                    )
                withheld = (await client.get(PREFIX + f"/{prospect_id}")).json()
                assert (
                    withheld["calls"][0]["snapshot"]["interpretations"][0]["source"]["evidence"][0][
                        "quote"
                    ]
                    == WITHHELD_MARKER
                )
                async with setup.sessions() as db, db.begin():
                    original = await db.get(ConversationCheckpoint, checkpoint_id)
                    recording = await db.get(ConversationRecording, original.recording_id)
                    cp = replace(
                        verified_checkpoint(original, binding_for(recording)),
                        replicate="corrupt-fictional",
                    )
                    db.add(
                        ConversationCheckpoint(
                            id=uuid4(),
                            tenant_id=original.tenant_id,
                            person_id=original.person_id,
                            recording_id=original.recording_id,
                            stage=cp.stage,
                            cache_key=cp.cache_key,
                            manifest_sha256=cp.manifest_sha256,
                            payload_sha256=cp.payload_sha256,
                            feature_blob_id=None,
                            manifest=cp.as_dict(),
                            payload={"extra": "must never be returned"},
                            created_at=setup.clock[0] + timedelta(seconds=1),
                        )
                    )
                assert (await client.get(PREFIX + f"/{prospect_id}")).json()["calls"][0][
                    "snapshot"
                ] is None
        finally:
            await setup.engine.dispose()

    run(exercise())
