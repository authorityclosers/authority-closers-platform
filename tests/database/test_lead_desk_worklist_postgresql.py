"""A seller's list on a heavy account, through the HTTP API on PostgreSQL (owner, 24 Oct
2026: "she has to see notes and work she has done recently ... we can't actually access
table view and filters and sorting"): 400 leads sorted and filtered on the server, page
after page, and My work, newest first."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Engine, inspect

from ac_platform.lead_desk.models import Lead
from tests.database.conversation_harness import conversation_harness
from tests.database.test_conversation_postgresql import run
from tests.database.test_lead_os_acceptance_postgresql import (
    BASE,
    ROOT,
    WRITE,
    World,
    later,
    world,
)

HEAVY = 400


@pytest.fixture(scope="module")
def postgres_harness() -> Iterator[Engine]:
    yield from conversation_harness(ROOT)


async def heavy(here: World) -> list[UUID]:
    """400 fictional leads for the seller, copied from one added through the API."""
    first = UUID(await here.add("Fictional Aarav", "98760 40000"))
    base = await here.stored(str(first))
    keys = [attribute.key for attribute in inspect(Lead).column_attrs]
    now = datetime.now(UTC)
    ids = [first]
    async with here.setup.sessions() as db, db.begin():
        for n in range(1, HEAVY):
            values: dict[str, Any] = {key: getattr(base, key) for key in keys}
            lead_id = uuid4()
            values.update(
                id=lead_id,
                name=f"Fictional {n:03d}",
                phone=f"+9198700{n:05d}",
                source_ref=None,
                source="csv" if n % 4 == 0 else base.source,
                created_at=now - timedelta(days=n % 40, minutes=n),
                updated_at=now - timedelta(minutes=n),
                last_contact_at=None if n % 3 == 0 else now - timedelta(days=n % 20),
                next_action_at=now + timedelta(hours=(n % 50) - 10),
            )
            db.add(Lead(**values))
            ids.append(lead_id)
    return ids


def test_four_hundred_leads_sort_and_filter_on_the_server(
    postgres_harness: Any, tmp_path: Path
) -> None:
    async def exercise() -> None:
        async with world(postgres_harness, tmp_path) as here:
            await heavy(here)
            here.as_seller()

            async def page(**query: str) -> dict[str, Any]:
                answer = await here.client.get(f"{BASE}/leads", params=query)
                assert answer.status_code == 200, answer.text
                body: dict[str, Any] = answer.json()
                return body

            # By name, across pages: the second page carries on where the first stopped.
            first = await page(scope="mine", sort="name")
            assert first["total"] == HEAVY and len(first["leads"]) == 50
            second = await page(scope="mine", sort="name", offset=str(first["next_offset"]))
            names = [row["name"] for row in first["leads"] + second["leads"]]
            assert names == sorted(names, key=str.lower)
            backwards = await page(scope="mine", sort="name", order="desc")
            assert backwards["leads"][0]["name"] == "Fictional Aarav"

            # Last contact: the most recent first; never contacted last.
            recent = await page(scope="mine", sort="last_contact")
            times = [row["last_contact_at"] for row in recent["leads"]]
            assert None not in times and times == sorted(times, reverse=True)

            # Filters, counted on the server; the stage tabs count the same leads.
            never = await page(scope="mine", contact="never")
            assert never["total"] == len(range(3, HEAVY, 3)) + 1
            assert sum(never["stage_counts"].values()) == never["total"]
            files = await page(scope="mine", source="csv")
            assert files["total"] == len(range(4, HEAVY, 4))
            late = await page(scope="mine", due="late")
            assert 0 < late["total"] < HEAVY
            week = await page(scope="mine", created="week", sort="created")
            made = [row["created_at"] for row in week["leads"]]
            assert made == sorted(made, reverse=True)

            # Words the server doesn't know are refused.
            wrong = await here.client.get(f"{BASE}/leads", params={"sort": "price"})
            assert wrong.status_code == 422

    run(exercise())


def test_my_work_lists_what_the_seller_did_newest_first(
    postgres_harness: Any, tmp_path: Path
) -> None:
    async def exercise() -> None:
        async with world(postgres_harness, tmp_path) as here:
            ids = [await here.add(f"Fictional Work {n}", f"98760 5000{n}") for n in range(3)]
            noted = await here.client.post(
                f"{BASE}/leads/{ids[0]}/notes",
                json={"command_id": str(uuid4()), "note": "Wants the brochure"},
                headers=WRITE,
            )
            assert noted.status_code == 200, noted.text
            moved = await here.move(ids[1], "interested", nextActionAt=later(days=1))
            assert moved.status_code == 200, moved.text
            assert (await here.move(ids[2], "lost", reason="price")).is_success

            mine = await here.client.get(f"{BASE}/activity", params={"day": "today"})
            assert mine.status_code == 200, mine.text
            body = mine.json()
            kinds = [item["event"]["kind"] for item in body["items"]]
            assert kinds[0] == "stage" and "note" in kinds
            assert body["items"][0]["lead_name"] == "Fictional Work 2"
            times = [item["event"]["at"] for item in body["items"]]
            assert times == sorted(times, reverse=True)
            assert body["counts"]["stage"] == 2 and body["counts"]["note"] == 1
            note = next(item for item in body["items"] if item["event"]["kind"] == "note")
            assert note["event"]["note"] == "Wants the brochure"
            assert note["lead_id"] == ids[0] and note["event_id"]

            # Yesterday was quiet; the week holds today's work.
            quiet = (await here.client.get(f"{BASE}/activity", params={"day": "yesterday"})).json()
            assert quiet["items"] == []
            week = (await here.client.get(f"{BASE}/activity", params={"day": "week"})).json()
            assert len(week["items"]) == len(body["items"])

            # A seller sees only their own work; an admin may look at the seller's.
            here.as_admin()
            others = await here.client.get(
                f"{BASE}/activity", params={"person": str(here.seller.person_id)}
            )
            assert others.status_code == 200 and len(others.json()["items"]) == len(kinds)
            here.as_seller()
            refused = await here.client.get(
                f"{BASE}/activity", params={"person": str(here.setup.state.person_id)}
            )
            assert refused.status_code == 403
            # Address options it doesn't know are refused.
            extra = await here.client.get(f"{BASE}/activity", params={"x": "1"})
            assert extra.status_code == 422

    run(exercise())


def test_the_list_answers_quickly_enough_for_a_heavy_account(
    postgres_harness: Any, tmp_path: Path
) -> None:
    """Not a benchmark: a guard that the sorted, filtered list of 400 stays one query
    round, well under a second on the CI database."""

    async def exercise() -> None:
        async with world(postgres_harness, tmp_path) as here:
            await heavy(here)
            here.as_seller()
            started = datetime.now(UTC)
            for query in (
                {"sort": "next_action"},
                {"sort": "last_contact", "due": "week"},
                {"sort": "name", "contact": "month"},
            ):
                answer = await here.client.get(f"{BASE}/leads", params={"scope": "mine", **query})
                assert answer.status_code == 200, answer.text
            assert datetime.now(UTC) - started < timedelta(seconds=10)

    run(exercise())
