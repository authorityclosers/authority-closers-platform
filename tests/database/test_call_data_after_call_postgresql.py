"""The after-call chain on a lead (owner, 25 Oct 2026): fills it can undo, and a reply.

A fill names its fact and the value it replaced; one tap puts the field back while
nobody has changed it since, and never over a person's later change. The lead's facts
carry a WhatsApp or SMS reply in the call's language. Disposable loopback PostgreSQL,
fictional rows only, a local fake model.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Engine, select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from ac_platform.call_data import engine as call_engine
from ac_platform.call_data import facts, undo
from ac_platform.call_data.models import CallObject, CallObjectDecision
from ac_platform.lead_desk.contracts import LeadEdit
from ac_platform.lead_desk.models import Lead, LeadEvent
from ac_platform.lead_desk.store import UNDO_OF, LeadDesk, Viewer
from tests.database.conversation_harness import conversation_harness
from tests.database.test_call_data_postgresql import ROOT, FakeModel, _call, _process
from tests.database.test_conversation_postgresql import run


@pytest.fixture
def postgres_harness() -> Iterator[Engine]:
    yield from conversation_harness(ROOT)


def _filled(postgres_harness: Engine) -> dict[str, Any]:
    """A fictional call that filled the lead's name and company by itself."""
    seeded = _call(postgres_harness)
    assert _process(postgres_harness, seeded, FakeModel())["lead_written"] == 2
    with postgres_harness.connect() as connection:
        objects = dict(
            connection.execute(
                select(CallObject.type_key, CallObject.id).where(
                    CallObject.recording_id == seeded["recording_id"]
                )
            ).all()
        )
    owner = seeded["owner"]
    return {
        **seeded,
        "name_fact": objects["person.name"],
        "company_fact": objects["company.name"],
        "viewer": Viewer(
            person_id=owner.person_id, tenant_id=owner.tenant_id, role="owner", name="Owner"
        ),
    }


def _lead(postgres_harness: Engine, lead_id: UUID) -> Any:
    with postgres_harness.connect() as connection:
        return connection.execute(select(Lead).where(Lead.id == lead_id)).one()


def _view(postgres_harness: Engine, seeded: dict[str, Any]) -> dict[str, Any]:
    lead = _lead(postgres_harness, seeded["lead_id"])
    columns = {"name": lead.name, "company": lead.company, "city": lead.city, "interest": None}
    with postgres_harness.connect() as connection:
        return facts.lead_facts(connection, seeded["owner"].tenant_id, lead.id, columns)


async def _in_session(postgres_harness: Engine, work: Any) -> Any:
    engine = create_async_engine(postgres_harness.url)
    try:
        async with AsyncSession(engine) as database, database.begin():
            return await work(database)
    finally:
        await engine.dispose()


def _undo(postgres_harness: Engine, seeded: dict[str, Any], fact: UUID, command: UUID) -> UUID:
    async def work(database: AsyncSession) -> UUID:
        return await undo.undo_fill(database, seeded["viewer"], fact, command, datetime.now(UTC))

    result: UUID = run(_in_session(postgres_harness, work))
    return result


def test_a_fill_names_its_fact_and_one_tap_puts_the_field_back(postgres_harness: Engine) -> None:
    seeded = _filled(postgres_harness)
    with postgres_harness.connect() as connection:
        fills = {
            row.data["changed"][0]: row
            for row in connection.execute(
                select(LeadEvent.id, LeadEvent.data).where(
                    LeadEvent.lead_id == seeded["lead_id"], LeadEvent.kind == "edited"
                )
            )
        }
    # Provenance: which fact wrote it, what it replaced, what it wrote.
    assert fills["company"].data["object_id"] == str(seeded["company_fact"])
    assert (fills["company"].data["before"], fills["company"].data["value"]) == (
        None,
        "XYZ Digital",
    )
    assert fills["name"].data["before"] == "Unnamed lead"  # the placeholder comes back
    view = _view(postgres_harness, seeded)
    assert {item["field"]: item["can_undo"] for item in view["filled"]} == {
        "name": True,
        "company": True,
    }

    command = uuid4()
    assert _undo(postgres_harness, seeded, seeded["company_fact"], command) == seeded["lead_id"]
    lead = _lead(postgres_harness, seeded["lead_id"])
    assert (lead.name, lead.company, lead.revision) == ("Amit Sharma", None, 4)
    # The same tap again changes nothing.
    _undo(postgres_harness, seeded, seeded["company_fact"], command)
    assert _lead(postgres_harness, seeded["lead_id"]).revision == 4

    with postgres_harness.connect() as connection:
        marker = connection.execute(
            select(LeadEvent.actor_person_id, LeadEvent.data).where(
                LeadEvent.lead_id == seeded["lead_id"],
                LeadEvent.data[UNDO_OF].as_string() == str(fills["company"].id),
            )
        ).one()
        decision = connection.execute(
            select(CallObjectDecision.decision, CallObjectDecision.actor)
            .where(CallObjectDecision.object_id == seeded["company_fact"])
            .order_by(CallObjectDecision.created_at.desc())
            .limit(1)
        ).one()
        state = call_engine.lead_state(connection, seeded["owner"].tenant_id, seeded["lead_id"])
    assert marker.actor_person_id == seeded["owner"].person_id
    assert marker.data == {
        "changed": ["company"],
        "via": "undo_fill",
        UNDO_OF: marker.data[UNDO_OF],
    }
    assert (decision.decision, decision.actor) == ("rejected", "person")
    # The same words never fill it again.
    assert state is not None and ("company.name", "xyz digital") in state.rejected
    assert {item["field"] for item in _view(postgres_harness, seeded)["filled"]} == {"name"}

    # The lead's history: the name's fill says it came from the call; the undone
    # company fill and its undo are not shown.
    async def history(database: AsyncSession) -> Any:
        return await LeadDesk(database, seeded["viewer"]).detail(seeded["lead_id"])

    detail = run(_in_session(postgres_harness, history))
    edits = [event for event in detail.events if event.kind == "edited"]
    assert [(event.changed, event.via, event.fill_object_id) for event in edits] == [
        (("name",), "call", seeded["name_fact"])
    ]


def test_a_persons_later_change_is_never_undone(postgres_harness: Engine) -> None:
    seeded = _filled(postgres_harness)
    lead = _lead(postgres_harness, seeded["lead_id"])

    async def edit(database: AsyncSession) -> None:
        await LeadDesk(database, seeded["viewer"]).edit(
            lead.id,
            LeadEdit(
                command_id=uuid4(), expected_revision=lead.revision, company="XYZ Digital Pvt"
            ),
        )

    run(_in_session(postgres_harness, edit))
    view = _view(postgres_harness, seeded)
    assert {item["field"]: item["can_undo"] for item in view["filled"]} == {
        "name": True,
        "company": False,
    }
    with pytest.raises(facts.FactsError, match="fill_changed"):
        _undo(postgres_harness, seeded, seeded["company_fact"], uuid4())
    after = _lead(postgres_harness, seeded["lead_id"])
    assert (after.company, after.revision) == ("XYZ Digital Pvt", lead.revision + 1)
    # Nothing was decided either: the fill still stands as the engine's.
    with postgres_harness.connect() as connection:
        actors = (
            connection.execute(
                select(CallObjectDecision.actor).where(
                    CallObjectDecision.object_id == seeded["company_fact"]
                )
            )
            .scalars()
            .all()
        )
    assert actors == ["engine"]


def test_the_lead_gets_a_reply_in_the_calls_language(postgres_harness: Engine) -> None:
    seeded = _filled(postgres_harness)
    draft = _view(postgres_harness, seeded)["reply"]
    assert (draft["language"], draft["template"]) == ("hinglish", "after_call")
    # The follow-up the call agreed (Friday 23 Oct 2026) has passed: the door stays open.
    assert draft["follow_up"] is None
    assert draft["text"] == (
        "Namaste Amit ji, aaj call par baat karne ke liye dhanyavaad. Koi bhi sawaal ho to"
        " yahin message kar dijiye. - {my_name}, {org}"
    )
    assert draft["call"]["recording_id"] == str(seeded["recording_id"])
