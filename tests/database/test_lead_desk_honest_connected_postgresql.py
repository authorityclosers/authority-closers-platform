"""Dipak's honest numbers, one rule everywhere, on PostgreSQL (the orchestrator, 3 Nov 2026, after
the v1.36 phone QA day: Home's Attempted 1 opened Calls on "No calls here", and a back-out from
the dialler answered "We talked" read Connected). Attempted counts call events only, so it equals
what Calls lists; Connected needs the phone's own evidence. A Call-button dial its phone's call
history timed is connected with the phone's seconds, never a second call; a dial with only "We
talked" stays outcome-unknown; "We didn't talk" makes it known, not connected. Made-up people
only."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Engine, select, update

from ac_platform.lead_desk.hours import IST
from ac_platform.lead_desk.models import Lead, LeadEvent
from tests.database.conversation_harness import conversation_harness
from tests.database.test_conversation_postgresql import run
from tests.database.test_lead_os_acceptance_postgresql import BASE, ROOT, WRITE, World, world


@pytest.fixture(scope="module")
def postgres_harness() -> Iterator[Engine]:
    yield from conversation_harness(ROOT)


async def all_day(here: World) -> None:
    """Work hours all week, the whole day, so the phone's call history is logged."""
    here.as_admin()
    team = (await here.client.get(f"{BASE}/team")).json()
    hours = await here.client.put(
        f"{BASE}/work-hours",
        json={
            "expected_revision": team["settings"]["revision"],
            "days": [0, 1, 2, 3, 4, 5, 6],
            "start": "00:00",
            "end": "23:59",
            "pause_leads": False,
            "breaks": [],
        },
        headers=WRITE,
    )
    assert hours.status_code == 200, hours.text
    here.as_seller()


async def dial(here: World, lead: str) -> None:
    """The Call button: the dialler opens, and the seller is back 30 s later."""
    placed = await here.client.post(
        f"{BASE}/leads/{lead}/calls/phone",
        json={"command_id": str(uuid4()), "duration_seconds": 30},
        headers=WRITE,
    )
    assert placed.status_code == 200, placed.text


def test_attempted_is_what_calls_lists_and_connected_is_the_phones_word(
    postgres_harness: Any, tmp_path: Path
) -> None:
    async def exercise() -> None:
        async with world(postgres_harness, tmp_path) as here:
            now = datetime.now(UTC)
            if (now - timedelta(minutes=10)).astimezone(IST).date() != now.astimezone(IST).date():
                pytest.skip("the calls would be yesterday's, just after midnight")
            await all_day(here)
            timed = await here.add("Fictional Timed Dial", "98760 69001")
            said = await here.add("Fictional Said Talked", "98760 69002")
            refused = await here.add("Fictional Said Not", "98760 69003")
            answered = await here.add("Fictional Answer Only", "98760 69004")
            async with here.setup.sessions() as db, db.begin():
                await db.execute(
                    update(Lead)
                    .where(Lead.id.in_([UUID(lead) for lead in (timed, said, refused, answered)]))
                    .values(pipeline="cold")
                )
            later_on = (now + timedelta(days=1)).isoformat()

            # 1. A dial its phone's call history timed: 75 s, connected, still one call.
            await dial(here, timed)
            sent = await here.client.post(
                f"{BASE}/phone-log",
                json={
                    "device_id": str(uuid4()),
                    "calls": [
                        {
                            "log_id": "1",
                            "number": "9876069001",
                            "started_at": (datetime.now(UTC) - timedelta(seconds=30)).isoformat(),
                            "duration_seconds": 75,
                            "direction": "outgoing",
                        }
                    ],
                },
                headers=WRITE,
            )
            assert sent.status_code == 200, sent.text
            assert sent.json()["logged"] == 0
            # 2. A dial whose seller said "We talked", the phone never said: unknown.
            await dial(here, said)
            talked = await here.dispose(
                said, connected=True, step="interested", follow_up_at=later_on
            )
            assert talked.status_code == 200, talked.text
            # 3. A dial whose seller said "We didn't talk": known, not connected.
            await dial(here, refused)
            nobody = await here.dispose(refused, connected=False, reason="did_not_pick")
            assert nobody.status_code == 200, nobody.text
            # 4. An answer with no call of its own: no call.
            only = await here.dispose(
                answered, connected=True, step="interested", follow_up_at=later_on
            )
            assert only.status_code == 200, only.text

            async with here.setup.sessions() as db:
                kinds = (
                    await db.scalars(
                        select(LeadEvent.kind).where(
                            LeadEvent.lead_id == UUID(timed), LeadEvent.kind == "call"
                        )
                    )
                ).all()
            assert kinds == ["call"]

            desk = (await here.client.get(BASE)).json()
            numbers = desk["numbers"]
            assert numbers["calls"] == 3, numbers
            assert numbers["connected"] == 1 and numbers["talk_seconds"] == 75, numbers
            assert numbers["unknown"] == 1 and numbers["not_connected"] == 1, numbers
            cold = desk["sides"]["cold"]["numbers"]
            assert (cold["calls"], cold["connected"], cold["unknown"]) == (3, 1, 1)

            # Calls opened from Attempted lists exactly those three, each with its outcome.
            page = (
                await here.client.get(f"{BASE}/activity", params={"day": "today", "kind": "call"})
            ).json()
            outcomes = {
                item["lead_id"]: (item["event"]["outcome"], item["event"]["seconds_from"])
                for item in page["items"]
            }
            assert outcomes == {
                timed: ("connected", "call_log"),
                said: ("unknown", None),
                refused: ("not_connected", None),
            }
            assert len(page["items"]) == numbers["calls"]
            assert page["today_counts"]["call"] == numbers["calls"]
            assert page["today_counts"]["connected"] == numbers["connected"]

            # Growth and Home's outcomes count the same: reached by the timed call alone.
            effort = (await here.client.get(f"{BASE}/performance/sellers?days=1")).json()["cold"]
            keys = ("attempted", "connected", "unknown", "reached", "interested")
            assert tuple(effort[key] for key in keys) == (3, 1, 1, 1, 2)
            here.as_admin()
            report = (await here.client.get(f"{BASE}/reports/performance?days=1")).json()
            assert (report["current"]["calls"], report["current"]["connected"]) == (3, 1)

    run(exercise())
