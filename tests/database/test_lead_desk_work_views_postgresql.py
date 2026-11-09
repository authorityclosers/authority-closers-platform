"""The seller's work views and the owner's stage filter through the HTTP API on PostgreSQL
(Dipak's Home + Leads handoff, 31 Oct 2026): To Call is what is due on the side today with
the next lead first, Follow-ups the leads with planned or overdue contact (split into Due
Today, Overdue and Upcoming), and a stage filter that keeps leads with no step in their
kind's stage."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Engine, inspect, update

from ac_platform.lead_desk import store
from ac_platform.lead_desk.hours import IST
from ac_platform.lead_desk.models import Lead
from tests.database.conversation_harness import conversation_harness
from tests.database.test_conversation_postgresql import run
from tests.database.test_lead_os_acceptance_postgresql import BASE, ROOT, World, world


@pytest.fixture(scope="module")
def postgres_harness() -> Iterator[Engine]:
    yield from conversation_harness(ROOT)


def shapes(now: datetime) -> list[tuple[str, str, datetime | None, datetime]]:
    """name, stage, next action, arrived; times from the moment the leads are built."""
    return [
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


def ist_day(at: datetime) -> date:
    return at.astimezone(IST).date()


async def worklist(here: World, now: datetime) -> None:
    """The seller's fictional leads, none with a step: what to call, follow-ups, a closed one."""
    first = UUID(await here.add("Fictional won", "98760 42000"))
    base = await here.stored(str(first))
    keys = [attribute.key for attribute in inspect(Lead).column_attrs]
    async with here.setup.sessions() as db, db.begin():
        await db.execute(
            update(Lead).where(Lead.id == first).values(stage="won", next_action_at=None, step=None)
        )
        for n, (name, stage, at, arrived) in enumerate(shapes(now)):
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
        # A Cold lead: All Leads lists it beside the Inbound ones (owner, 2 Nov 2026).
        values = {key: getattr(base, key) for key in keys}
        values.update(
            id=uuid4(),
            name="Fictional cold unworked",
            phone="+919870060001",
            source_ref=None,
            pipeline="cold",
            stage="new",
            step=None,
            next_action_at=None,
            created_at=now - timedelta(days=2),
        )
        db.add(Lead(**values))


# Where the desk's clock stands: noon in India, and either side of midnight, where a time
# a few minutes back is yesterday's (the v1.48 cut ran this at 00:02-00:06 IST and counted
# the follow-up due 10 minutes before as overdue). Each lead's day is worked out the way
# the desk does it, so the test holds at any hour.
CLOCKS = {"noon IST": time(12, 0), "00:05 IST": time(0, 5), "23:55 IST": time(23, 55)}


@pytest.mark.parametrize("clock", list(CLOCKS))
def test_work_views_and_the_stage_filter(
    postgres_harness: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, clock: str
) -> None:
    # The leads are built a second before the desk reads its clock.
    now = datetime.combine(datetime.now(IST).date(), CLOCKS[clock], tzinfo=IST).astimezone(UTC)
    desk_now = now + timedelta(seconds=1)
    monkeypatch.setattr(store, "utcnow", lambda: desk_now)
    planned = {name: at for name, _, at, _ in shapes(now) if at is not None}
    # Planned before today, India time: overdue, and the backlog in To Call.
    late = [
        name
        for name, at in sorted(planned.items(), key=lambda item: item[1])
        if ist_day(at) < ist_day(desk_now)
    ]
    near = ["Fictional retry late", "Fictional follow-up due"]

    async def exercise() -> None:
        async with world(postgres_harness, tmp_path) as here:
            await worklist(here, now)
            here.as_seller()

            async def names(**query: str) -> list[str]:
                answer = await here.client.get(f"{BASE}/leads", params=query)
                assert answer.status_code == 200, answer.text
                return [row["name"] for row in answer.json()["leads"]]

            # To Call in its calling order, next lead first (Dipak's handoff p.12, one rule
            # with Home's next lead): due today and already due, then new leads never called
            # (oldest first), then the older backlog (phone personas, 1 Nov 2026: Home said
            # Kiara while Leads dialled Krishna). Just after midnight India time the retry
            # and the follow-up due are yesterday's: the backlog.
            to_call = await names(scope="mine", side="inbound", view="to_call")
            assert to_call == [
                *(name for name in near if name not in late),
                "Fictional new older",
                "Fictional new newer",
                *late,
            ]
            # Home's next Inbound lead is that list's first row.
            desk = await here.client.get(BASE)
            assert desk.status_code == 200, desk.text
            assert desk.json()["sides"]["inbound"]["next_lead"]["name"] == to_call[0]
            # Follow-ups: every planned contact, soonest first, the retry after no answer
            # too (phone personas, 1 Nov 2026, ph2-14: it showed only in All Leads).
            assert await names(scope="mine", side="inbound", view="follow_ups") == [
                "Fictional follow-up old",
                "Fictional retry late",
                "Fictional follow-up due",
                "Fictional follow-up later",
            ]
            overdue = await names(scope="mine", side="inbound", view="follow_ups", when="overdue")
            assert overdue == late
            assert await names(
                scope="mine", side="inbound", view="follow_ups", when="upcoming"
            ) == ["Fictional follow-up later"]
            # A side without a work view (Home's counts) is still that side only.
            assert len(await names(scope="mine", side="inbound")) == 7
            # All Leads: every lead the seller may see on both sides, the closed one and the
            # Cold one too (owner, 2 Nov 2026), and its tab counts the same leads; To Call and
            # Follow-ups keep to the side picked.
            every = await here.client.get(
                f"{BASE}/leads", params={"scope": "mine", "side": "inbound", "view": "all"}
            )
            assert every.status_code == 200, every.text
            page = every.json()
            assert len(page["leads"]) == page["total"] == 8
            cold = next(row for row in page["leads"] if row["name"] == "Fictional cold unworked")
            assert cold["side"] == "cold"
            assert page["view_counts"] == {"to_call": len(to_call), "follow_ups": 4, "all": 8}
            assert sum(page["step_counts"].values()) == 8
            calling = await here.client.get(
                f"{BASE}/leads", params={"scope": "mine", "side": "inbound", "view": "to_call"}
            )
            assert calling.status_code == 200, calling.text
            assert calling.json()["view_counts"]["all"] == 8

            # The stage filter: the owner's first New stage takes the new leads with no step.
            journey = await here.client.get(f"{BASE}/journey")
            assert journey.status_code == 200, journey.text
            stages = journey.json()["stages"]
            new_key = next(stage["key"] for stage in stages if stage["kind"] == "new")
            # Which leads, not their order: these two share their times.
            assert sorted(await names(scope="mine", side="inbound", step=new_key)) == [
                "Fictional new newer",
                "Fictional new older",
            ]
            assert await names(scope="mine", side="inbound", step="no_such_stage") == []
            # On All Leads (both sides), New shows the newest first unless a sort is picked
            # (bug 127); To Call keeps its calling order (oldest new lead first).
            assert await names(scope="mine", side="inbound", view="all", step=new_key) == [
                "Fictional new newer",
                "Fictional cold unworked",
                "Fictional new older",
            ]
            assert await names(scope="mine", side="inbound", view="to_call", step=new_key) == [
                "Fictional new older",
                "Fictional new newer",
            ]

            # The stage picker's numbers: each stage's leads before the stage pick, filed
            # as the stage filter files them, on a side's first page only.
            async def counted(**query: str) -> dict[str, int]:
                answer = await here.client.get(f"{BASE}/leads", params=query)
                assert answer.status_code == 200, answer.text
                return dict(answer.json()["step_counts"])

            counts = await counted(scope="mine", side="inbound")
            assert counts[new_key] == 2
            assert sum(counts.values()) == 7
            assert await counted(scope="mine", side="inbound", step=new_key) == counts
            assert await counted(scope="mine", side="inbound", offset="1") == {}
            assert await counted(scope="mine") == {}
            refused = await here.client.get(
                f"{BASE}/leads", params={"scope": "mine", "view": "today"}
            )
            assert refused.status_code == 422

    run(exercise())
