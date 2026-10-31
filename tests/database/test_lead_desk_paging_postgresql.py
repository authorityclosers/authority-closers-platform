"""The Leads list pages each lead once (owner's bug report, 31 Oct 2026: a seller saw leads
repeated after the first page). A thousand fictional leads share their arrival and update times,
as an import's do; paging through the list, in its own order and in To Call's, gives every lead
exactly once."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Engine, inspect, update

from ac_platform.lead_desk.models import Lead
from tests.database.conversation_harness import conversation_harness
from tests.database.test_conversation_postgresql import run
from tests.database.test_lead_os_acceptance_postgresql import BASE, ROOT, World, world

LEADS = 1000


@pytest.fixture(scope="module")
def postgres_harness() -> Iterator[Engine]:
    yield from conversation_harness(ROOT)


async def imported(here: World) -> None:
    """A thousand fictional leads with one arrival and update time, as one import makes them."""
    first = UUID(await here.add("Fictional import 0", "98760 43000"))
    async with here.setup.sessions() as db, db.begin():
        await db.execute(
            update(Lead).where(Lead.id == first).values(next_action_at=None, step=None)
        )
    base = await here.stored(str(first))
    keys = [attribute.key for attribute in inspect(Lead).column_attrs]
    async with here.setup.sessions() as db, db.begin():
        for n in range(1, LEADS):
            values: dict[str, Any] = {key: getattr(base, key) for key in keys}
            values.update(
                id=uuid4(),
                name=f"Fictional import {n}",
                phone=f"+9198701{n:05d}",
                source_ref=None,
            )
            db.add(Lead(**values))


def test_the_list_pages_each_lead_once(postgres_harness: Any, tmp_path: Path) -> None:
    async def exercise() -> None:
        async with world(postgres_harness, tmp_path) as here:
            await imported(here)
            here.as_seller()

            async def every(**query: str) -> list[str]:
                seen: list[str] = []
                offset = 0
                while True:
                    answer = await here.client.get(
                        f"{BASE}/leads", params={**query, "offset": str(offset)}
                    )
                    assert answer.status_code == 200, answer.text
                    page = answer.json()
                    seen.extend(row["lead_id"] for row in page["leads"])
                    if page["next_offset"] is None:
                        return seen
                    offset = page["next_offset"]

            for query in (
                {"scope": "mine", "side": "inbound"},
                {"scope": "mine", "side": "inbound", "view": "to_call"},
            ):
                ids = await every(**query)
                assert len(ids) == LEADS, query
                assert len(set(ids)) == LEADS, query

    run(exercise())
