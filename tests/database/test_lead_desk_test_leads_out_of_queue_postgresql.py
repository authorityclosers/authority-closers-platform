"""Test leads are nobody's work, on PostgreSQL (Redmi tester, 17 Nov 2026: Meta's "<test lead:
dummy data for full_name>" was filed as test data, yet sat in AC's To Call 7 and led Call Next
Lead). Outside a sandbox organisation a lead marked as test data is in no To Call or Follow-ups
list or tab count, not on the badge, not Home's next lead or countdown, and "Start calling"
never dials it. All Leads and the Test data filter still list it. Made-up people only."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import Engine, update

from ac_platform.lead_desk.models import Lead
from tests.database.conversation_harness import conversation_harness
from tests.database.test_conversation_postgresql import run
from tests.database.test_lead_os_acceptance_postgresql import BASE, ROOT, World, world


@pytest.fixture(scope="module")
def postgres_harness() -> Iterator[Engine]:
    yield from conversation_harness(ROOT)


async def set_test(here: World, lead: str, value: bool) -> None:
    async with here.setup.sessions() as db, db.begin():
        await db.execute(update(Lead).where(Lead.id == UUID(lead)).values(test_data=value))


async def listed(here: World, **params: Any) -> tuple[set[str], dict[str, int]]:
    page = await here.client.get(f"{BASE}/leads", params={"scope": "mine", **params})
    assert page.status_code == 200, page.text
    body = page.json()
    return {row["lead_id"] for row in body["leads"]}, body.get("view_counts") or {}


def test_a_test_lead_is_in_no_call_queue(postgres_harness: Any, tmp_path: Path) -> None:
    async def exercise() -> None:
        async with world(postgres_harness, tmp_path) as here:
            real = await here.add("Fictional Real Enquiry", "98760 72001")
            fake = await here.add("<test lead: dummy data for full_name>", "98760 72002")
            await set_test(here, fake, True)

            to_call, counts = await listed(here, side="inbound", view="to_call")
            assert to_call == {real}, to_call
            assert counts["to_call"] == 1, counts
            everything, counts = await listed(here, side="inbound", view="all")
            assert {real, fake} <= everything
            assert counts["all"] >= 2, counts
            tests_only, _ = await listed(here, test="only")
            assert fake in tests_only and real not in tests_only

            badge = (await here.client.get(f"{BASE}/badge")).json()
            assert badge["to_call"] == 1, badge

            desk = (await here.client.get(BASE)).json()
            assert desk["sides"]["inbound"]["next_lead"]["lead_id"] == real
            assert desk["to_call_today"]["left"] == 1, desk["to_call_today"]
            assert fake not in {row["lead_id"] for row in desk["queue"]}

            first = (await here.client.get(f"{BASE}/next")).json()
            assert first["lead"]["lead_id"] == real
            after = await here.client.get(f"{BASE}/next", params={"skip": real})
            assert after.status_code == 200, after.text
            assert after.json() is None

            # Unmarked, it is work again: the flag is the only switch.
            await set_test(here, fake, False)
            to_call, counts = await listed(here, side="inbound", view="to_call")
            assert to_call == {real, fake}, to_call
            assert counts["to_call"] == 2, counts
            badge = (await here.client.get(f"{BASE}/badge")).json()
            assert badge["to_call"] == 2, badge

    run(exercise())
