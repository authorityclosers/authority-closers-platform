"""Targets through the HTTP API on PostgreSQL (team engine, docs/product/lead-desk/
team-engine.md, section 2 and scenario 6): an owner sets a seller's targets, a retry sets
nothing twice, a new value supersedes from its day, a zero removes it, progress counts the
seller's real calls and outcomes, and only owners and managers set or read others'."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import Engine, func, select

from ac_platform.lead_desk.models import LeadTarget
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


@pytest.fixture(scope="module")
def postgres_harness() -> Iterator[Engine]:
    yield from conversation_harness(ROOT)


async def put(here: World, command: str, *lines: tuple[str, str, int], **extra: Any) -> Any:
    return await here.client.put(
        f"{BASE}/targets",
        json={
            "command_id": command,
            "person_id": str(here.seller.person_id),
            "targets": [
                {"metric": metric, "period": period, "value": value}
                for metric, period, value in lines
            ],
            **extra,
        },
        headers=WRITE,
    )


async def rows(here: World) -> int:
    async with here.setup.sessions() as db:
        return int(
            await db.scalar(select(func.count()).where(LeadTarget.tenant_id == here.tenant_id)) or 0
        )


def test_targets_set_once_supersede_and_count_real_activity(
    postgres_harness: Any, tmp_path: Path
) -> None:
    async def exercise() -> None:
        async with world(postgres_harness, tmp_path) as here:
            lead_id = await here.add("Fictional Target One", "98760 65001")
            here.as_admin()
            command = str(uuid4())
            lines = (("calls", "day", 10), ("connects", "day", 4), ("follow_ups", "week", 20))
            first = await put(here, command, *lines)
            assert first.status_code == 200, first.text
            again = await put(here, command, *lines)
            assert again.status_code == 200 and await rows(here) == 3
            assert [(t["metric"], t["period"], t["value"]) for t in first.json()["targets"]] == [
                ("calls", "day", 10),
                ("connects", "day", 4),
                ("follow_ups", "week", 20),
            ]
            # A new value supersedes from its day; a zero removes a target.
            newer = await put(here, str(uuid4()), ("calls", "day", 20), ("connects", "day", 0))
            assert newer.status_code == 200, newer.text
            targets = {(t["metric"], t["period"]): t["value"] for t in newer.json()["targets"]}
            assert targets == {("calls", "day"): 20, ("follow_ups", "week"): 20}
            past = await put(here, str(uuid4()), ("calls", "day", 5), effective_from="2020-01-01")
            assert past.status_code == 422

            # The seller works: one call not reached, one talked with a follow-up.
            here.as_seller()
            missed = await here.dispose(lead_id, connected=False, reason="did_not_pick")
            assert missed.status_code == 200, missed.text
            talked = await here.dispose(
                lead_id, connected=True, step="interested", follow_up_at=later(days=1)
            )
            assert talked.status_code == 200, talked.text
            mine = (await here.client.get(f"{BASE}/targets")).json()
            done = {(p["metric"], p["period"]): p["done"] for p in mine["progress"]}
            # Neither call was a due follow-up: none done yet.
            assert done == {("calls", "day"): 2, ("follow_ups", "week"): 0}

            # Rights: a seller sets nothing and reads only their own.
            refused = await put(here, str(uuid4()), ("calls", "day", 99))
            assert refused.status_code == 403
            other = await here.client.get(
                f"{BASE}/targets", params={"person": str(here.setup.state.person_id)}
            )
            assert other.status_code == 403
            # A manager reads the seller's, and the team's.
            here.as_admin()
            theirs = await here.client.get(
                f"{BASE}/targets", params={"person": str(here.seller.person_id)}
            )
            assert theirs.status_code == 200 and theirs.json()["progress"]
            team = (await here.client.get(f"{BASE}/targets/team")).json()
            assert [seller["person_id"] for seller in team["sellers"]] == [
                str(here.seller.person_id)
            ]

    run(exercise())
