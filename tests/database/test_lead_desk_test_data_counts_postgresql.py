"""Test leads stay out of every number, on PostgreSQL (owner, 17 Nov 2026: "test leads
pollute karuu naye data ... data clean disaayalaa paahije"; QA calls under a real seller
filled her seller bar). A call on a lead marked as test data still lists in the seller's
feed, but Home's numbers, each seller's effort, Team, the calls report, Performance and the
activity summary count only the real lead's call. Made-up people only."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import Engine, update

from ac_platform.lead_desk.hours import IST
from ac_platform.lead_desk.models import Lead
from tests.database.conversation_harness import conversation_harness
from tests.database.test_conversation_postgresql import run
from tests.database.test_lead_desk_honest_connected_postgresql import all_day, dial
from tests.database.test_lead_os_acceptance_postgresql import BASE, ROOT, World, world


@pytest.fixture(scope="module")
def postgres_harness() -> Iterator[Engine]:
    yield from conversation_harness(ROOT)


async def mark_test(here: World, lead: str) -> None:
    async with here.setup.sessions() as db, db.begin():
        await db.execute(update(Lead).where(Lead.id == UUID(lead)).values(test_data=True))


def test_calls_on_test_leads_list_but_never_count(postgres_harness: Any, tmp_path: Path) -> None:
    async def exercise() -> None:
        async with world(postgres_harness, tmp_path) as here:
            now = datetime.now(UTC)
            if (now - timedelta(minutes=10)).astimezone(IST).date() != now.astimezone(IST).date():
                pytest.skip("the calls would be yesterday's, just after midnight")
            await all_day(here)
            real = await here.add("Fictional Real Buyer", "98760 71001")
            fake = await here.add("Fictional QA Lead", "98760 71002")
            await mark_test(here, fake)
            await dial(here, real)
            await dial(here, fake)
            # Team counts saved answers and phone-logged calls: answer both.
            for lead in (real, fake):
                answered = await here.dispose(lead, connected=False, reason="did_not_pick")
                assert answered.status_code == 200, answered.text

            # The seller's own feed still lists both calls.
            page = (
                await here.client.get(f"{BASE}/activity", params={"day": "today", "kind": "call"})
            ).json()
            assert {item["lead_id"] for item in page["items"]} == {real, fake}

            # Home's numbers count the real call only.
            numbers = (await here.client.get(BASE)).json()["numbers"]
            assert numbers["calls"] == 1, numbers

            # Each seller's effort (Home's seller rows, Performance's table).
            sides = (await here.client.get(f"{BASE}/performance/sellers?days=1")).json()
            attempted = sum(
                sides[side]["attempted"] for side in ("inbound", "cold") if side in sides
            )
            assert attempted == 1, sides

            summary = (await here.client.get(f"{BASE}/activity/summary?days=1")).json()
            counted_calls = summary["current"]["calls"]

            here.as_admin()
            team = (await here.client.get(f"{BASE}/team")).json()
            seller = next(
                rep for rep in team["reps"] if rep["person_id"] == str(here.seller.person_id)
            )
            assert seller["calls_today"] == 1, seller

            today = now.astimezone(IST).date().isoformat()
            report = (
                await here.client.get(
                    f"{BASE}/reports/calls", params={"start": today, "end": today}
                )
            ).json()
            row = next(
                item
                for item in report["sellers"]
                if item["person_id"] == str(here.seller.person_id)
            )
            assert row["calls"] == 1, row

            performance = (await here.client.get(f"{BASE}/reports/performance?days=1")).json()
            assert performance["current"]["calls"] == 1, performance["current"]

            # Unmarked again, the call counts again: the flag is the only switch.
            async with here.setup.sessions() as db, db.begin():
                await db.execute(update(Lead).where(Lead.id == UUID(fake)).values(test_data=False))
            again = (await here.client.get(f"{BASE}/reports/performance?days=1")).json()
            assert again["current"]["calls"] == 2, again["current"]
            here.as_seller()
            back = (await here.client.get(f"{BASE}/activity/summary?days=1")).json()
            assert back["current"]["calls"] == counted_calls + 1, (counted_calls, back["current"])

    run(exercise())
