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
from tests.database.test_lead_os_acceptance_postgresql import BASE, ROOT, WRITE, World, world


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

            # The Leads badge is the Inbound To Call list, late as its rows are: a seller's
            # Cold leads are never due or late on it (persona QA, 31 Oct 2026: "99+").
            badge = (await here.client.get(f"{BASE}/badge")).json()
            assert badge["to_call"] == numbers.json()["inbound"]["to_call"]
            assert badge["overdue"] == sum(row["overdue"] for row in inbound["leads"])

            # Home's "Follow-ups late" is the Late list it opens, on Inbound (phone personas,
            # 1 Nov 2026: "2 late" over a list of 0).
            effort = await here.client.get(f"{BASE}/performance/sellers?days=1")
            assert effort.status_code == 200, effort.text
            late_list = await page(scope="mine", stage="open", side="inbound", due="late")
            seller = effort.json()["sellers"][0]
            assert seller["inbound"]["late"] == late_list["total"] == 1
            assert seller["cold"]["late"] == 0

            refused = await here.client.get(
                f"{BASE}/leads", params={"scope": "mine", "side": "warm"}
            )
            assert refused.status_code == 422

            # An admin still sees a worked cold lead late; an untouched one is late for no one.
            here.as_admin()
            # Home's team "Follow-ups late" is the team's Late list on Inbound too.
            report = await here.client.get(f"{BASE}/reports/performance", params={"days": 1})
            assert report.status_code == 200, report.text
            team_late = await page(scope="team", stage="open", side="inbound", due="late")
            assert sum(rep["late"] for rep in report.json()["sellers"]) == team_late["total"]
            # New leads are Inbound arrivals: the three Cold leads are never new leads
            # (ph1-20, 1 Nov 2026: "New leads 903" with 900 Cold imports in it).
            week = await here.client.get(f"{BASE}/reports/performance", params={"days": 7})
            assert week.status_code == 200, week.text
            assert week.json()["current"]["new_leads"] == 3
            team_cold = await page(scope="team", stage="open", side="cold")
            seen = {row["name"]: row["overdue"] for row in team_cold["leads"]}
            assert seen["Fictional Cold tried"] is True
            assert seen["Fictional Cold untouched"] is False

    run(exercise())


def test_a_cold_leads_first_stage_says_its_cold_name(postgres_harness: Any, tmp_path: Path) -> None:
    """Persona QA (31 Oct 2026): a Cold lead said "Unworked" in the list and "New Lead" in its
    sheet. The sheet now says the first stage's Cold name too; an Inbound lead's is unchanged."""

    async def exercise() -> None:
        async with world(postgres_harness, tmp_path) as here:
            here.as_admin()
            picked = await here.client.post(
                f"{BASE}/journey/template",
                json={"expectedVersion": 1, "template": "recommended"},
                headers=WRITE,
            )
            assert picked.status_code == 200, picked.text
            await both_sides(here)
            here.as_seller()
            ids: dict[str, str] = {}
            for side in ("inbound", "cold"):
                answer = await here.client.get(
                    f"{BASE}/leads", params={"scope": "mine", "stage": "open", "side": side}
                )
                assert answer.status_code == 200, answer.text
                ids.update({row["name"]: row["lead_id"] for row in answer.json()["leads"]})

            async def label(name: str) -> str:
                detail = await here.client.get(f"{BASE}/leads/{ids[name]}")
                assert detail.status_code == 200, detail.text
                return str(detail.json()["lead"]["stage_label"])

            assert await label("Fictional Cold untouched") == "Unworked"
            assert await label("Fictional Inbound no side") == "New Lead"

    run(exercise())


def test_follow_ups_hold_every_planned_call_on_its_side(
    postgres_harness: Any, tmp_path: Path
) -> None:
    """Phone personas (1 Nov 2026): ph2-14, a "No answer" retry showed only in All Leads;
    ph2-18, a Cold lead's call-back booked for tomorrow never reached Cold > Follow-ups.
    Follow-ups hold every open lead with a time, on its side."""

    async def exercise() -> None:
        async with world(postgres_harness, tmp_path) as here:
            await both_sides(here)
            async with here.setup.sessions() as db, db.begin():
                # A call-back booked on an untouched Cold lead, for tomorrow.
                await db.execute(
                    update(Lead)
                    .where(Lead.name == "Fictional Cold untouched")
                    .values(next_action_at=datetime.now(UTC) + timedelta(days=1))
                )
            here.as_seller()

            async def names(**query: str) -> list[str]:
                answer = await here.client.get(
                    f"{BASE}/leads", params={"scope": "mine", "stage": "open", **query}
                )
                assert answer.status_code == 200, answer.text
                return sorted(row["name"] for row in answer.json()["leads"])

            # The retry after no answer, the follow-up and the booked call-back.
            assert await names(view="follow_ups", side="cold") == [
                "Fictional Cold talking",
                "Fictional Cold tried",
                "Fictional Cold untouched",
            ]
            assert await names(view="follow_ups", side="cold", when="upcoming") == [
                "Fictional Cold talking",
                "Fictional Cold untouched",
            ]
            # Inbound's own: the late follow-up, never a Cold one.
            assert await names(view="follow_ups", side="inbound") == ["Fictional Inbound late"]

    run(exercise())
