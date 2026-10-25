"""My day through the HTTP API on PostgreSQL (team engine, docs/product/lead-desk/
team-engine.md, section 4 and scenarios 15 to 17): the seller's work ranked with why, a
promise overdue before a new lead; today without zeros; an empty day with what is next
instead; a manager may read a seller's, a seller not a manager's."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import Engine

from tests.database.conversation_harness import conversation_harness
from tests.database.test_conversation_postgresql import run
from tests.database.test_lead_desk_tasks_postgresql import task
from tests.database.test_lead_os_acceptance_postgresql import BASE, ROOT, later, world


@pytest.fixture(scope="module")
def postgres_harness() -> Iterator[Engine]:
    yield from conversation_harness(ROOT)


def test_my_day_ranks_the_work_and_never_shows_a_wall_of_zeros(
    postgres_harness: Any, tmp_path: Path
) -> None:
    async def exercise() -> None:
        async with world(postgres_harness, tmp_path) as here:
            promised = await here.add("Fictional Day One", "98760 68001")
            fresh = await here.add("Fictional Day Two", "98760 68002")
            await task(here, promised, kind="call_back", starts_at=later(minutes=-30))
            # A task for tomorrow is not work for now.
            await task(here, fresh, kind="whatsapp", starts_at=later(days=1))

            day = (await here.client.get(f"{BASE}/my-day")).json()
            order = [item["lead_id"] for item in day["do_now"]]
            assert order[0] == promised
            assert day["do_now"][0]["because"]
            assert day["today"] == {}
            assert day["fallback"] is None

            # A manager reads the seller's; the seller may not read the manager's.
            here.as_admin()
            theirs = await here.client.get(
                f"{BASE}/my-day", params={"person": str(here.seller.person_id)}
            )
            assert theirs.status_code == 200
            assert [item["lead_id"] for item in theirs.json()["do_now"]] == order
            # The admin's own day is empty: what is next and recent, never zeros.
            own = (await here.client.get(f"{BASE}/my-day")).json()
            assert own["do_now"] == [] and own["today"] == {}
            assert own["fallback"] is not None
            assert all(value > 0 for value in own["fallback"]["week"].values())
            here.as_seller()
            refused = await here.client.get(
                f"{BASE}/my-day", params={"person": str(here.setup.state.person_id)}
            )
            assert refused.status_code == 403

    run(exercise())
