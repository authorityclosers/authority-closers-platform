"""An undone answer counts nowhere, on PostgreSQL (hardcore phone QA ph1-40 and ph1-41, 1 Nov
2026: Home's 7 days rose by two while Cold today said Connected 0, one of the two "We talked"
answers undone; Growth said To Interested 1 beside Leads reached 0). A Call-button dial whose "We
talked" was undone is a call nobody answered, and the lead it moved to Interested moved nowhere:
on Home, each side's day, Growth, Home's outcomes and Reports' first talk. The call itself stays
a call. An answer logged without a call is a call, reached when they talked (ph1-58).
Made-up people only."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Engine, update

from ac_platform.lead_desk.models import Lead
from tests.database.conversation_harness import conversation_harness
from tests.database.test_conversation_postgresql import run
from tests.database.test_lead_os_acceptance_postgresql import BASE, ROOT, WRITE, World, world


@pytest.fixture(scope="module")
def postgres_harness() -> Iterator[Engine]:
    yield from conversation_harness(ROOT)


async def read(here: World, path: str, *, admin: bool = False) -> dict[str, Any]:
    if admin:
        here.as_admin()
    found = await here.client.get(f"{BASE}{path}")
    here.as_seller()
    assert found.status_code == 200, found.text
    body: dict[str, Any] = found.json()
    return body


def pick(side: dict[str, Any], *keys: str) -> tuple[int, ...]:
    return tuple(int(side[key]) for key in keys)


def test_an_undone_answer_counts_nowhere(postgres_harness: Any, tmp_path: Path) -> None:
    async def exercise() -> None:
        async with world(postgres_harness, tmp_path) as here:
            cold = await here.add("Fictional Undone Cold", "98760 68001")
            warm = await here.add("Fictional Undone Inbound", "98760 68002")
            async with here.setup.sessions() as db, db.begin():
                await db.execute(update(Lead).where(Lead.id == UUID(cold)).values(pipeline="cold"))
            # The Call button on the Cold lead, then "We talked" and Interested.
            placed = await here.client.post(
                f"{BASE}/leads/{cold}/calls/phone",
                json={"command_id": str(uuid4()), "duration_seconds": 40},
                headers=WRITE,
            )
            assert placed.status_code == 200, placed.text
            later = (datetime.now(UTC) + timedelta(days=1)).isoformat()
            saved = await here.dispose(cold, connected=True, step="interested", follow_up_at=later)
            assert saved.status_code == 200, saved.text
            # Interested on the Inbound lead with no call from the app (a chat, say).
            chat = await here.dispose(warm, connected=True, step="interested", follow_up_at=later)
            assert chat.status_code == 200, chat.text

            desk = await read(here, "")
            # The Cold dial and the Inbound answer logged without a call (ph1-58).
            assert pick(desk["numbers"], "calls", "connected") == (2, 2)
            assert pick(desk["sides"]["cold"]["numbers"], "calls", "connected") == (1, 1)
            effort = await read(here, "/performance/sellers?days=1")
            keys = ("attempted", "connected", "reached", "interested")
            assert pick(effort["cold"], *keys) == (1, 1, 1, 1)
            # Logged without a call from the app: a call, connected and reached (ph1-58).
            assert pick(effort["inbound"], *keys) == (1, 1, 1, 1)
            outcomes = (await read(here, "/reports/performance?days=1", admin=True))["current"]
            assert pick(outcomes, "calls", "connected", "interested") == (2, 2, 2)
            talked = (await read(here, "/reports/pipeline?days=30", admin=True))["first_connect"]

            # The seller undoes the Cold answer.
            body = saved.json()
            undone = await here.client.post(
                f"{BASE}/leads/{cold}/results/{body['undo_result']['event_id']}/undo",
                json={"command_id": str(uuid4()), "expected_revision": body["lead"]["revision"]},
                headers=WRITE,
            )
            assert undone.status_code == 200, undone.text

            desk = await read(here, "")
            assert pick(desk["numbers"], "calls", "connected") == (2, 1)
            assert pick(desk["sides"]["cold"]["numbers"], "calls", "connected") == (1, 0)
            effort = await read(here, "/performance/sellers?days=1")
            assert pick(effort["cold"], *keys) == (1, 0, 0, 0)
            assert pick(effort["inbound"], *keys) == (1, 1, 1, 1)
            outcomes = (await read(here, "/reports/performance?days=1", admin=True))["current"]
            assert pick(outcomes, "calls", "connected", "interested") == (2, 1, 1)
            after = (await read(here, "/reports/pipeline?days=30", admin=True))["first_connect"]
            assert after["passed"] == talked["passed"] - 1

    run(exercise())
