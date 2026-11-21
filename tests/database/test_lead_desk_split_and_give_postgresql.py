"""Wise Life's lead rules (owner, 19 Nov 2026), through the HTTP API on PostgreSQL.

- A split rule gives new leads by percent (20/40/40 over ten leads is 2/4/4), and each
  hand-over is marked on the lead's history so the split counts it.
- Auto-reassign counts work minutes, and only moves leads that came in lately.
- A seller gives their own lead to a colleague only when the workspace allows it, and
  always with a reason, which the lead's history keeps.

Made-up people only.
"""

from datetime import timedelta
from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ac_platform.lead_desk.models import Lead, LeadDeskSettings, LeadEvent
from ac_platform.lead_desk.store import LeadDesk, Viewer
from tests.database.test_conversation_account_library_postgresql import _session
from tests.database.test_conversation_postgresql import postgres_harness as _postgres_harness
from tests.database.test_conversation_postgresql import run, seed
from tests.database.test_conversation_submission_http_postgresql import ORIGIN, _setup
from tests.database.test_lead_desk_postgresql import _organisation

WRITE = {"Origin": ORIGIN, "Content-Type": "application/json"}
BASE = "/v1/lead-desk"


@pytest.fixture
def postgres_harness() -> Any:
    yield from cast(Any, _postgres_harness).__wrapped__()


async def _config(setup: Any, **values: Any) -> None:
    async with AsyncSession(setup.engine) as db, db.begin():
        row = await db.get(LeadDeskSettings, setup.state.tenant_id)
        if row is None:
            row = LeadDeskSettings(
                tenant_id=setup.state.tenant_id,
                revision=1,
                config={},
                updated_at=setup.state.now,
            )
            db.add(row)
        else:
            row.revision += 1
        row.config = {**(row.config or {}), **values}


def test_a_split_gives_by_percent_and_auto_reassign_counts_work_minutes(
    postgres_harness: Any, tmp_path: Path
) -> None:
    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path)
        try:
            await _organisation(setup)  # the signed-in person is an admin
            sellers = [
                await seed(setup.engine, tenant_id=setup.state.tenant_id, role="member")
                for _ in range(3)
            ]
            dheeraj, aniket, sachin = (seller.person_id for seller in sellers)
            await _config(
                setup,
                routing_rules=[
                    {
                        "id": "wl-split",
                        "name": "Wise Life split",
                        "enabled": True,
                        "when": [],
                        "give_to": [str(dheeraj), str(aniket), str(sachin)],
                        "shares": [20, 40, 40],
                    }
                ],
                auto_reassign=True,
                reassign_minutes=30,
                # Switched on before these leads came (only later givings move).
                auto_reassign_since=(setup.state.now - timedelta(hours=1)).isoformat(),
                # Every day, all day: the work-minute clock without a night in the way.
                work_hours={
                    "days": [0, 1, 2, 3, 4, 5, 6],
                    "start": "00:00",
                    "end": "23:59",
                    "pause_leads": False,
                },
            )
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=setup.app), base_url=ORIGIN
            ) as client:
                client.cookies.set(setup.settings.session_cookie_name, setup.token)
                ids: list[str] = []
                for number in range(10):
                    added = await client.post(
                        f"{BASE}/leads",
                        json={
                            "command_id": str(uuid4()),
                            "name": f"split fictional {number}",
                            "assign": "rules",
                        },
                        headers=WRITE,
                    )
                    assert added.status_code == 201, added.text
                    ids.append(added.json()["lead"]["lead_id"])

            async with AsyncSession(setup.engine) as db:
                leads = (
                    await db.scalars(select(Lead).where(Lead.id.in_([UUID(i) for i in ids])))
                ).all()
                counts = {
                    person: sum(lead.owner_person_id == person for lead in leads)
                    for person in (dheeraj, aniket, sachin)
                }
                assert counts == {dheeraj: 2, aniket: 4, sachin: 4}
                assert all("% share (rule 1)" in (lead.owner_reason or "") for lead in leads)
                marks = (
                    await db.scalars(
                        select(LeadEvent).where(
                            LeadEvent.tenant_id == setup.state.tenant_id,
                            LeadEvent.kind == "assigned",
                        )
                    )
                ).all()
                assert sum(event.data.get("split") == "wl-split" for event in marks) == 10
                given_at = max(lead.assigned_at for lead in leads if lead.assigned_at)

                # The commit below expires these rows, so keep what the sweep is checked against.
                owners = {lead.id: lead.owner_person_id for lead in leads}
                order = [lead.id for lead in leads]

                # One lead came in ten days ago: an old uncalled lead stays where it is.
                old = leads[0]
                await db.execute(
                    update(Lead)
                    .where(Lead.id == old.id)
                    .values(received_at=given_at - timedelta(days=10))
                )
                await db.commit()

            viewer = Viewer(
                person_id=UUID(int=0),
                tenant_id=setup.state.tenant_id,
                role="owner",
                name="Auto-reassign",
            )
            async with AsyncSession(setup.engine) as db, db.begin():
                early = LeadDesk(db, viewer, now=given_at + timedelta(minutes=28))
                assert await early.sweep() == 0
            async with AsyncSession(setup.engine) as db, db.begin():
                due = LeadDesk(db, viewer, now=given_at + timedelta(minutes=32))
                assert await due.sweep() == 9
            async with AsyncSession(setup.engine) as db:
                after = {
                    lead.id: lead
                    for lead in (
                        await db.scalars(select(Lead).where(Lead.id.in_([UUID(i) for i in ids])))
                    ).all()
                }
                assert after[order[0]].owner_person_id == owners[order[0]]
                for lead_id in order[1:]:
                    moved = after[lead_id]
                    assert moved.owner_person_id not in {None, owners[lead_id]}
                    assert (moved.owner_reason or "").startswith("No call in 30 work minutes.")
        finally:
            await setup.engine.dispose()

    run(exercise())


def test_a_seller_gives_their_lead_with_a_reason_only_when_allowed(
    postgres_harness: Any, tmp_path: Path
) -> None:
    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path)
        try:
            await _organisation(setup)  # the signed-in person is an admin
            mansi = await seed(setup.engine, tenant_id=setup.state.tenant_id, role="member")
            aniket = await seed(setup.engine, tenant_id=setup.state.tenant_id, role="member")
            mansi_token = await _session(setup, mansi)
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=setup.app), base_url=ORIGIN
            ) as client:

                def as_(token: str) -> None:
                    client.cookies.clear()
                    client.cookies.set(setup.settings.session_cookie_name, token)

                as_(setup.token)
                added = await client.post(
                    f"{BASE}/leads",
                    json={"command_id": str(uuid4()), "name": "rohit fictional", "assign": "me"},
                    headers=WRITE,
                )
                assert added.status_code == 201, added.text
                lead = added.json()["lead"]
                given = await client.post(
                    f"{BASE}/leads/{lead['lead_id']}/assign",
                    json={
                        "command_id": str(uuid4()),
                        "expected_revision": lead["revision"],
                        "person_id": str(mansi.person_id),
                    },
                    headers=WRITE,
                )
                assert given.status_code == 200, given.text

                async def give(**body: Any) -> httpx.Response:
                    current = await client.get(f"{BASE}/leads/{lead['lead_id']}")
                    assert current.status_code == 200, current.text
                    return await client.post(
                        f"{BASE}/leads/{lead['lead_id']}/assign",
                        json={
                            "command_id": str(uuid4()),
                            "expected_revision": current.json()["lead"]["revision"],
                            **body,
                        },
                        headers=WRITE,
                    )

                # Off (the default): a seller can't give it away, and the page offers nothing.
                as_(mansi_token)
                shown = await client.get(f"{BASE}/leads/{lead['lead_id']}")
                assert shown.json()["can_give"] is False and shown.json()["reps"] == []
                refused = await give(person_id=str(aniket.person_id), reason="escalation")
                assert refused.status_code == 403, refused.text

                # An admin switches it on.
                as_(setup.token)
                team = (await client.get(f"{BASE}/team")).json()
                assert team["settings"]["sellers_reassign"] is False
                saved = await client.put(
                    f"{BASE}/settings",
                    json={
                        "expected_revision": team["settings"]["revision"],
                        "auto_reassign": False,
                        "reassign_minutes": 30,
                        "sellers_reassign": True,
                    },
                    headers=WRITE,
                )
                assert saved.status_code == 200, saved.text
                assert saved.json()["settings"]["sellers_reassign"] is True

                as_(mansi_token)
                shown = await client.get(f"{BASE}/leads/{lead['lead_id']}")
                body = shown.json()
                assert body["can_give"] is True and body["can_assign"] is False
                offered = {rep["person_id"] for rep in body["reps"]}
                assert str(aniket.person_id) in offered and str(mansi.person_id) not in offered

                # A reason is required, and "other" needs a few words.
                no_reason = await give(person_id=str(aniket.person_id))
                assert no_reason.status_code == 422, no_reason.text
                bare_other = await give(person_id=str(aniket.person_id), reason="other")
                assert bare_other.status_code == 422, bare_other.text
                done = await give(
                    person_id=str(aniket.person_id),
                    reason="escalation",
                    note="  needs a   senior ",
                )
                assert done.status_code == 200, done.text
                assert done.json()["lead"]["owner_person_id"] == str(aniket.person_id)
                assert done.json()["owner_reason"].endswith(": Escalation (needs a senior)")
                assert done.json()["owner_reason"].startswith("Given by ")

                # It is Aniket's now: Mansi can't move it again.
                again = await client.post(
                    f"{BASE}/leads/{lead['lead_id']}/assign",
                    json={
                        "command_id": str(uuid4()),
                        "expected_revision": done.json()["lead"]["revision"],
                        "person_id": str(mansi.person_id),
                        "reason": "importance",
                    },
                    headers=WRITE,
                )
                assert again.status_code in {403, 404}, again.text

            async with AsyncSession(setup.engine) as db:
                event = (
                    await db.scalars(
                        select(LeadEvent)
                        .where(
                            LeadEvent.lead_id == UUID(lead["lead_id"]),
                            LeadEvent.kind == "reassigned",
                        )
                        .order_by(LeadEvent.created_at.desc())
                    )
                ).first()
                assert event is not None
                assert event.actor_person_id == mansi.person_id
                assert event.data["rule"] == "given"
                assert event.data["reason"] == "escalation"
                assert event.data["note"] == "needs a senior"
        finally:
            await setup.engine.dispose()

    run(exercise())
