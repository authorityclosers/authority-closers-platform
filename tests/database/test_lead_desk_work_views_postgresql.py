"""The seller's work views and the owner's stage filter through the HTTP API on PostgreSQL
(Dipak's Home + Leads handoff, 31 Oct 2026): To Call is what is due on the side today with
the next lead first, Follow-ups the leads with planned or overdue contact (split into Due
Today, Overdue and Upcoming), and a stage filter that keeps leads with no step in their
kind's stage."""

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


async def worklist(here: World) -> None:
    """The seller's fictional leads, none with a step: what to call, follow-ups, a closed one."""
    first = UUID(await here.add("Fictional won", "98760 42000"))
    base = await here.stored(str(first))
    keys = [attribute.key for attribute in inspect(Lead).column_attrs]
    now = datetime.now(UTC)
    shapes = [
        # name, stage, next action, arrived
        ("Fictional new older", "new", None, now - timedelta(days=3)),
        ("Fictional new newer", "new", None, now - timedelta(days=1)),
        (
            "Fictional retry late",
            "not_connected",
            now - timedelta(hours=2),
            now - timedelta(days=5),
        ),
        (
            "Fictional follow-up due",
            "interested",
            now - timedelta(minutes=10),
            now - timedelta(days=6),
        ),
        ("Fictional follow-up old", "interested", now - timedelta(days=4), now - timedelta(days=6)),
        (
            "Fictional follow-up later",
            "interested",
            now + timedelta(days=3),
            now - timedelta(days=6),
        ),
    ]
    async with here.setup.sessions() as db, db.begin():
        await db.execute(
            update(Lead).where(Lead.id == first).values(stage="won", next_action_at=None, step=None)
        )
        for n, (name, stage, at, arrived) in enumerate(shapes):
            values: dict[str, Any] = {key: getattr(base, key) for key in keys}
            values.update(
                id=uuid4(),
                name=name,
                phone=f"+91987005{n:04d}",
                source_ref=None,
                pipeline="live",
                stage=stage,
                step=None,
                next_action_at=at,
                created_at=arrived,
            )
            db.add(Lead(**values))


def test_work_views_and_the_stage_filter(postgres_harness: Any, tmp_path: Path) -> None:
    async def exercise() -> None:
        async with world(postgres_harness, tmp_path) as here:
            await worklist(here)
            here.as_seller()

            async def names(**query: str) -> list[str]:
                answer = await here.client.get(f"{BASE}/leads", params=query)
                assert answer.status_code == 200, answer.text
                return [row["name"] for row in answer.json()["leads"]]

            # To Call: by when each is due (a new lead from its arrival), the next lead first.
            to_call = await names(scope="mine", side="inbound", view="to_call")
            assert to_call == [
                "Fictional follow-up old",
                "Fictional new older",
                "Fictional new newer",
                "Fictional retry late",
                "Fictional follow-up due",
            ]
            # Follow-ups: planned or overdue contact, soonest first; retries stay in To Call.
            assert await names(scope="mine", side="inbound", view="follow_ups") == [
                "Fictional follow-up old",
                "Fictional follow-up due",
                "Fictional follow-up later",
            ]
            assert await names(scope="mine", side="inbound", view="follow_ups", when="overdue") == [
                "Fictional follow-up old"
            ]
            assert await names(
                scope="mine", side="inbound", view="follow_ups", when="upcoming"
            ) == ["Fictional follow-up later"]
            # All Leads: every lead on the side, the closed one too.
            assert len(await names(scope="mine", side="inbound")) == 7

            # The stage filter: the owner's first New stage takes the new leads with no step.
            journey = await here.client.get(f"{BASE}/journey")
            assert journey.status_code == 200, journey.text
            stages = journey.json()["stages"]
            new_key = next(stage["key"] for stage in stages if stage["kind"] == "new")
            assert await names(scope="mine", side="inbound", step=new_key) == [
                "Fictional new older",
                "Fictional new newer",
            ]
            assert await names(scope="mine", side="inbound", step="no_such_stage") == []
            refused = await here.client.get(
                f"{BASE}/leads", params={"scope": "mine", "view": "today"}
            )
            assert refused.status_code == 422

    run(exercise())
