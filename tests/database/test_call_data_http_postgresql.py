"""Call data engine through its HTTP API on PostgreSQL: a lead's facts and the questions.

A seller's call on a lead is transcribed (a fictional C2 transcript), the fast
pipeline runs with a local fake model, and the lead screen's API shows what was
filled and asks the rest one at a time; an edit is saved as the person's word.
Disposable loopback PostgreSQL, fictional rows only.
"""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import insert, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import sessionmaker

from ac_platform.call_data import engine as call_engine
from ac_platform.call_data.http import install_call_data_http
from ac_platform.call_data.runner import process_call
from ac_platform.conversation_intelligence.models import (
    ConversationCheckpoint,
    ConversationRecording,
)
from ac_platform.http.routes import RouteContext
from ac_platform.lead_desk.models import Lead, LeadEvent
from tests.database.test_call_data_postgresql import ANSWER, SEGMENTS, FakeModel
from tests.database.test_conversation_postgresql import application, run
from tests.database.test_conversation_postgresql import postgres_harness as _postgres_harness
from tests.database.test_conversation_submission_http_postgresql import ORIGIN, _setup
from tests.database.test_lead_desk_postgresql import _organisation

WRITE = {"Origin": ORIGIN, "Content-Type": "application/json"}
# The fixture call plus a city said once, not confidently: asked, not filled.
WITH_CITY = {
    **ANSWER,
    "facts": [
        *ANSWER["facts"],
        {
            "type": "company.location",
            "value": {"text": "Pune"},
            "confidence": 0.7,
            "basis": "observed",
            "segments": ["s3"],
        },
    ],
}
BASE = "/v1/sales-xray/call-data"


@pytest.fixture
def postgres_harness() -> Any:
    yield from cast(Any, _postgres_harness).__wrapped__()


async def _call_on_lead(setup: Any, lead_id: UUID) -> tuple[UUID, UUID]:
    async with AsyncSession(setup.engine) as database, database.begin():
        record = await application(database, setup.state).register(
            setup.state.actor, setup.state.recording_intent, key="call-data-http"
        )
    recording_id, submission_id = UUID(record["id"]), uuid4()
    now = datetime.now(UTC)
    async with setup.sessions() as db, db.begin():
        await db.execute(
            update(ConversationRecording)
            .where(ConversationRecording.id == recording_id)
            .values(state="ready")
        )
        await db.execute(
            insert(ConversationCheckpoint).values(
                id=uuid4(),
                tenant_id=setup.state.tenant_id,
                person_id=setup.state.person_id,
                recording_id=recording_id,
                cache_key="c" * 64,
                manifest_sha256="a" * 64,
                payload_sha256="b" * 64,
                stage="C2",
                manifest={"stage": "C2"},
                payload={
                    "segments": SEGMENTS,
                    "revision": "e" * 64,
                    "source_sha256": setup.state.source_sha256,
                    "duration_ms": 24000,
                },
                created_at=now,
            )
        )
        await db.execute(
            insert(LeadEvent).values(
                id=uuid4(),
                tenant_id=setup.state.tenant_id,
                lead_id=lead_id,
                kind="call",
                data={"submission_id": str(submission_id)},
                created_at=now,
            )
        )
    return recording_id, submission_id


def _run_fast(postgres_harness: Any, recording_id: UUID, submission_id: UUID) -> dict[str, Any]:
    sync = sessionmaker(postgres_harness, expire_on_commit=False)
    with sync() as session:
        calls = call_engine.candidates(
            session.connection(),
            not_before=datetime.now(UTC) - timedelta(hours=1),
            hours=48,
            limit=5,
            recording_id=recording_id,
        )
        settings_now, _ = call_engine.read_settings(session.connection())
    calls[0].submission_id = submission_id
    return process_call(
        sync,
        calls[0],
        settings=settings_now,
        apply=True,
        trigger="operator",
        created_by="test:call-data",
        model_client=FakeModel(WITH_CITY),
        test_sources=set(),
    )


def test_a_call_fills_its_lead_and_asks_the_seller(postgres_harness: Any, tmp_path: Path) -> None:
    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path)
        try:
            await _organisation(setup)
            settings = setup.settings.model_copy(update={"public_learner_tenant_id": uuid4()})
            install_call_data_http(
                setup.app, RouteContext(settings, setup.require_actor, setup.sessions)
            )
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=setup.app), base_url=ORIGIN
            ) as client:
                client.cookies.set(setup.settings.session_cookie_name, setup.token)
                added = await client.post(
                    "/v1/lead-desk/leads",
                    json={
                        "command_id": str(uuid4()),
                        "name": "Unnamed lead",
                        "phone": "9876500011",
                    },
                    headers=WRITE,
                )
                assert added.status_code == 201, added.text
                lead_id = UUID(added.json()["lead"]["lead_id"])
                recording_id, submission_id = await _call_on_lead(setup, lead_id)
                line = _run_fast(postgres_harness, recording_id, submission_id)
                assert line["outcome"] == "succeeded", line

                view = await client.get(f"{BASE}/leads/{lead_id}")
                assert view.status_code == 200, view.text
                body = view.json()
                assert view.headers["cache-control"] == "private, no-store"
                assert {f["field"] for f in body["filled"]} == {"name", "company"}
                assert len(body["questions"]) == 4
                pain = next(q for q in body["questions"] if q["type"] == "need.primary_pain")
                assert pain["question"] == "confirm"
                assert pain["evidence"][0]["quote"] == SEGMENTS[2]["text"]
                decide = f"{BASE}/objects/{pain['object_id']}/decision"

                # Writes need the Sales Xray origin.
                refused = await client.post(
                    decide, json={"command_id": str(uuid4()), "decision": "accepted"}
                )
                assert refused.status_code == 403
                command = {
                    "command_id": str(uuid4()),
                    "decision": "edited",
                    "value": {"text": "Every sale needs Amit"},
                }
                answered = await client.post(decide, json=command, headers=WRITE)
                assert answered.status_code == 200, answered.text
                assert len(answered.json()["questions"]) == 3
                again = await client.post(decide, json=command, headers=WRITE)
                assert again.status_code == 200  # the same command replays

                facts = await client.get(f"{BASE}/prospect-facts", params={"lead_id": str(lead_id)})
                assert facts.status_code == 200, facts.text
                shown = {f["type"]: f for f in facts.json()["facts"]}
                assert shown["need.primary_pain"]["basis"] == "edited"
                assert shown["person.name"]["prospect_field"] == "name"
                both = await client.get(
                    f"{BASE}/prospect-facts",
                    params={"lead_id": str(lead_id), "call_id": str(submission_id)},
                )
                assert both.status_code == 422
                by_call = await client.get(
                    f"{BASE}/prospect-facts", params={"call_id": str(submission_id)}
                )
                assert len(by_call.json()["facts"]) == 6
                city = next(q for q in body["questions"] if q["type"] == "company.location")
                assert (city["question"], city["lead_field"]) == ("fill", "city")
                kept = await client.post(
                    f"{BASE}/objects/{city['object_id']}/decision",
                    json={"command_id": str(uuid4()), "decision": "accepted"},
                    headers=WRITE,
                )
                assert kept.status_code == 200, kept.text
                desk = (await client.get(f"/v1/lead-desk/leads/{lead_id}")).json()
                assert desk["lead"]["city"] == "Pune"
                edited = [e for e in desk["events"] if e["kind"] == "edited"]
                assert edited and edited[0]["changed"] == ["city"]
                assert body["reply"]["language"] == "hinglish"

                # One tap puts back what the call filled: the company was empty before.
                now_view = (await client.get(f"{BASE}/leads/{lead_id}")).json()
                filled = {f["field"]: f for f in now_view["filled"]}
                assert filled["company"]["can_undo"] is True
                undo = f"{BASE}/objects/{filled['company']['object_id']}/undo-fill"
                refused = await client.post(undo, json={"command_id": str(uuid4())})
                assert refused.status_code == 403
                undone = await client.post(undo, json={"command_id": str(uuid4())}, headers=WRITE)
                assert undone.status_code == 200, undone.text
                assert {f["field"] for f in undone.json()["filled"]} == {"name"}
                twice = await client.post(undo, json={"command_id": str(uuid4())}, headers=WRITE)
                assert twice.status_code == 409
                desk = (await client.get(f"/v1/lead-desk/leads/{lead_id}")).json()
                assert desk["lead"]["company"] is None
                # The name's fill says where it came from; the undone one is not shown.
                fills = [e for e in desk["events"] if e.get("via") == "call"]
                assert [(e["changed"], e["fill_object_id"]) for e in fills] == [
                    (["name"], filled["name"]["object_id"])
                ]
                taxonomy = await client.get(f"{BASE}/taxonomy")
                assert taxonomy.json()["version"] == "call-taxonomy/2"
                async with setup.sessions() as db:
                    lead = (await db.execute(select(Lead).where(Lead.id == lead_id))).scalar_one()
                    assert (lead.name, lead.company) == ("Amit Sharma", None)
                # A lead that is not on this desk is not found.
                missing = await client.get(f"{BASE}/leads/{uuid4()}")
                assert missing.status_code == 404
        finally:
            await setup.engine.dispose()

    run(exercise())
