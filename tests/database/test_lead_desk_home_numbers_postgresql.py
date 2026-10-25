"""Home's zero states on PostgreSQL (owner, 25 Oct 2026: "show the next useful data, the
last days or weeks", and a member with no leads saw "No leads yet" while hundreds waited):
the desk carries yesterday's and the last seven days' numbers beside today's, and the
workspace's open and unassigned leads with whether this person takes new ones."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Engine

from ac_platform.lead_desk.models import LeadEvent
from tests.database.conversation_harness import conversation_harness
from tests.database.test_conversation_postgresql import run
from tests.database.test_lead_os_acceptance_postgresql import BASE, ROOT, later, world


@pytest.fixture(scope="module")
def postgres_harness() -> Iterator[Engine]:
    yield from conversation_harness(ROOT)


def test_yesterday_the_week_and_the_team_pool(postgres_harness: Any, tmp_path: Path) -> None:
    async def exercise() -> None:
        async with world(postgres_harness, tmp_path) as here:
            first = await here.add("Fictional Home One", "98760 67001")
            await here.add("Fictional Home Two", "98760 67002")
            talked = await here.dispose(
                first, connected=True, step="interested", follow_up_at=later(days=1)
            )
            assert talked.status_code == 200, talked.text
            # Yesterday the seller logged one call that connected.
            async with here.setup.sessions() as db, db.begin():
                stored = await here.stored(first)
                yesterday = stored.created_at - timedelta(days=1)
                db.add(
                    LeadEvent(
                        id=uuid4(),
                        tenant_id=here.tenant_id,
                        lead_id=UUID(first),
                        kind="result",
                        actor_person_id=here.seller.person_id,
                        data={"connected": True, "was_due": True},
                        created_at=yesterday,
                    )
                )
            desk = (await here.client.get(f"{BASE}")).json()
            assert desk["numbers"]["calls"] == 1 and desk["numbers"]["connected"] == 1
            assert desk["numbers_yesterday"]["calls"] == 1
            assert desk["numbers_yesterday"]["follow_ups_done"] == 1
            assert desk["numbers_week"]["calls"] == 2
            assert desk["team_pool"] == {"open": 2, "unassigned": 0, "may_take": True}
            # The admin has no leads of their own and takes none: the pool says what's there.
            here.as_admin()
            theirs = (await here.client.get(f"{BASE}")).json()
            assert theirs["numbers"]["calls"] == 0
            assert theirs["team_pool"] == {"open": 2, "unassigned": 0, "may_take": False}

    run(exercise())
