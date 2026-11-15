"""Home's date reads one chosen day (owner, 15 Nov 2026), each seller carries their photo
(initials when there is none), and the sellers are the people who take leads: an admin
who sells nothing is no seller, until they say they also sell; through the HTTP API on
PostgreSQL."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime, time, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import Engine

from tests.database.conversation_harness import conversation_harness
from tests.database.test_conversation_postgresql import run
from tests.database.test_lead_os_acceptance_postgresql import BASE, ROOT, WRITE, world

IST = ZoneInfo("Asia/Kolkata")


@pytest.fixture(scope="module")
def postgres_harness() -> Iterator[Engine]:
    yield from conversation_harness(ROOT)


def test_a_chosen_day_reads_that_day_and_sellers_are_who_take_leads(
    postgres_harness: Any, tmp_path: Path
) -> None:
    async def exercise() -> None:
        async with world(postgres_harness, tmp_path) as here:
            here.as_admin()
            url = f"{BASE}/performance/sellers"
            today = datetime.now(IST).date()
            yesterday = today - timedelta(days=1)

            # Yesterday, India time: from its midnight to the next.
            day = await here.client.get(url, params={"days": 1, "on": yesterday.isoformat()})
            assert day.status_code == 200, day.text
            body = day.json()
            start = datetime.fromisoformat(body["start"]).astimezone(IST)
            end = datetime.fromisoformat(body["end"]).astimezone(IST)
            assert start == datetime.combine(yesterday, time.min, tzinfo=IST)
            assert end == datetime.combine(today, time.min, tzinfo=IST)

            # Today keeps ending now.
            now = await here.client.get(url, params={"days": 1, "on": today.isoformat()})
            assert now.status_code == 200, now.text
            assert datetime.fromisoformat(now.json()["end"]).astimezone(IST).date() == today

            # Never ahead, never past 90 days, and a chosen day is one day.
            ahead = await here.client.get(
                url, params={"days": 1, "on": (today + timedelta(days=1)).isoformat()}
            )
            assert ahead.status_code == 422
            old = await here.client.get(
                url, params={"days": 1, "on": (today - timedelta(days=91)).isoformat()}
            )
            assert old.status_code == 422
            week = await here.client.get(url, params={"days": 7, "on": yesterday.isoformat()})
            assert week.status_code == 422

            # Each seller says their photo: none here, so initials.
            plain = await here.client.get(url, params={"days": 1})
            assert plain.status_code == 200, plain.text
            sellers = plain.json()["sellers"]
            assert sellers, "the fictional world has sellers"
            assert all("photo_url" in seller and seller["photo_url"] is None for seller in sellers)

            # The sellers are who take leads: the seller, not the admin who took none and
            # called nobody (15 Nov 2026).
            admin = str(here.setup.state.person_id)
            listed = {seller["person_id"] for seller in sellers}
            assert str(here.seller.person_id) in listed
            assert admin not in listed

            # Once the admin says they also sell (Taking new leads on), they count.
            switched = await here.client.put(
                f"{BASE}/team/{admin}",
                json={"expected_revision": 1, "available": True, "max_open": 50},
                headers=WRITE,
            )
            assert switched.status_code == 200, switched.text
            again = (await here.client.get(url, params={"days": 1})).json()["sellers"]
            assert admin in {seller["person_id"] for seller in again}

    run(exercise())
