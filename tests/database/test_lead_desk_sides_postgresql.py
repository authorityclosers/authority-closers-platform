"""Inbound Leads and Cold Leads through the HTTP API on PostgreSQL (Dipak's final model, the
owner's ruling of 30 Oct 2026): the list's side filter and its stage counts, each side's three
header numbers, and a seller's cold leads never late while an admin still sees them late."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Engine, inspect, update

from ac_platform.lead_desk.models import Lead
from tests.database.conversation_harness import conversation_harness
from tests.database.test_conversation_postgresql import run
from tests.database.test_lead_os_acceptance_postgresql import BASE, ROOT, World, world


@pytest.fixture(scope="module")
def postgres_harness() -> Iterator[Engine]:
    yield from conversation_harness(ROOT)


async def both_sides(here: World) -> None:
    """The seller's fictional leads: one Won and two open on the Inbound side (one with no side
    at all, which reads Inbound), and three open on the Cold side."""
    first = UUID(await here.add("Fictional Inbound won", "98760 41000"))
    base = await here.stored(str(first))
    keys = [attribute.key for attribute in inspect(Lead).column_attrs]
    now = datetime.now(UTC)
    shapes = [
        # name, side, stage, next action, attempts
        ("Fictional Inbound late", "live", "interested", now - timedelta(hours=3), 1),
        ("Fictional Inbound no side", None, "new", None, 0),
        ("Fictional Cold untouched", "cold", "new", None, 0),
        ("Fictional Cold tried", "cold", "not_connected", now - timedelta(hours=5), 2),
        ("Fictional Cold talking", "cold", "follow_up", now + timedelta(days=1), 1),
    ]
    async with here.setup.sessions() as db, db.begin():
        await db.execute(
            update(Lead)
            .where(Lead.id == first)
            .values(pipeline="live", stage="won", next_action_at=None)
        )
        for n, (name, side, stage, at, attempts) in enumerate(shapes):
            values: dict[str, Any] = {key: getattr(base, key) for key in keys}
            values.update(
                id=uuid4(),
                name=name,
                phone=f"+91987004{n:04d}",
                source_ref=None,
                pipeline=side,
                stage=stage,
                next_action_at=at,
                attempts=attempts,
                created_at=now - timedelta(days=2),
            )
            db.add(Lead(**values))


def test_each_side_lists_counts_and_numbers_its_own_leads(
    postgres_harness: Any, tmp_path: Path
) -> None:
    async def exercise() -> None:
        async with world(postgres_harness, tmp_path) as here:
            await both_sides(here)
            here.as_seller()

            async def page(**query: str) -> dict[str, Any]:
                answer = await here.client.get(f"{BASE}/leads", params=query)
                assert answer.status_code == 200, answer.text
                body: dict[str, Any] = answer.json()
                return body

            def names(body: dict[str, Any]) -> list[str]:
                return sorted(row["name"] for row in body["leads"])

            inbound = await page(scope="mine", stage="open", side="inbound")
            cold = await page(scope="mine", stage="open", side="cold")
            assert names(inbound) == ["Fictional Inbound late", "Fictional Inbound no side"]
            assert names(cold) == [
                "Fictional Cold talking",
                "Fictional Cold tried",
                "Fictional Cold untouched",
            ]
            # The stage tabs count one side.
            assert inbound["stage_counts"] == {"new": 1, "interested": 1, "won": 1}
            assert cold["stage_counts"] == {"new": 1, "not_connected": 1, "follow_up": 1}
            # No side asked: every lead, as before.
            assert (await page(scope="mine", stage="open"))["total"] == 5

            # A seller's cold leads are never late; an inbound one still is.
            late = {row["name"]: row["overdue"] for row in [*inbound["leads"], *cold["leads"]]}
            assert late["Fictional Inbound late"] is True
            assert late["Fictional Cold tried"] is False

            numbers = await here.client.get(f"{BASE}/sides", params={"scope": "mine"})
            assert numbers.status_code == 200, numbers.text
            assert numbers.json()["inbound"] == {
                "leads": 3,
                "new": 1,
                "to_call": 2,
                "follow_ups": 1,
            }
            assert numbers.json()["cold"] == {"imported": 3, "unworked": 1, "attempted": 2}

            refused = await here.client.get(
                f"{BASE}/leads", params={"scope": "mine", "side": "warm"}
            )
            assert refused.status_code == 422

            # An admin still sees the cold lead late.
            here.as_admin()
            team_cold = await page(scope="team", stage="open", side="cold")
            assert {row["name"]: row["overdue"] for row in team_cold["leads"]}[
                "Fictional Cold tried"
            ] is True

    run(exercise())
