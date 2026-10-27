"""Leads setup, end to end (owner reports #37-#42, 27 Oct 2026: "half things don't work and
not properly tested"). Each control on Organisation → Leads setup is saved through the API,
then a new lead shows what it changed: who owns it, where it lands, and when it moves.
The audit table is in the orchestrator's notes (leads-setup-audit-20261027.md).
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import Engine, update

from ac_platform.lead_desk import hours, reassign
from ac_platform.lead_desk.models import Lead
from tests.database.conversation_harness import conversation_harness
from tests.database.test_conversation_postgresql import run, seed
from tests.database.test_lead_os_acceptance_postgresql import BASE, ROOT, WRITE, world


@pytest.fixture(scope="module")
def postgres_harness() -> Iterator[Engine]:
    yield from conversation_harness(ROOT)


async def _team(here: Any) -> dict[str, Any]:
    here.as_admin()
    found = await here.client.get(f"{BASE}/team")
    assert found.status_code == 200, found.text
    body: dict[str, Any] = found.json()
    return body


async def _rules(here: Any, person: UUID, **rules: Any) -> None:
    reps = {rep["person_id"]: rep for rep in (await _team(here))["reps"]}
    saved = await here.client.put(
        f"{BASE}/team/{person}",
        json={
            "expected_revision": reps[str(person)]["revision"],
            "available": True,
            "max_open": 50,
            **rules,
        },
        headers=WRITE,
    )
    assert saved.status_code == 200, saved.text


async def _add(here: Any, name: str, phone: str, **fields: Any) -> dict[str, Any]:
    here.as_admin()
    added = await here.client.post(
        f"{BASE}/leads",
        json={"command_id": str(uuid4()), "name": name, "phone": phone, **fields},
        headers=WRITE,
    )
    assert added.status_code == 201, added.text
    lead: dict[str, Any] = {**added.json()["lead"], "owner_reason": added.json()["owner_reason"]}
    return lead


async def _second_seller(here: Any) -> UUID:
    other = await seed(here.setup.engine, tenant_id=here.setup.state.tenant_id, role="member")
    here.as_admin()
    saved = await here.client.put(
        f"{BASE}/team/{other.person_id}",
        json={"expected_revision": 0, "available": True, "max_open": 50},
        headers=WRITE,
    )
    assert saved.status_code == 200, saved.text
    return UUID(str(other.person_id))


def test_a_sellers_rules_decide_who_gets_a_new_lead(postgres_harness: Any, tmp_path: Path) -> None:
    async def exercise() -> None:
        async with world(postgres_harness, tmp_path) as here:
            hindi = UUID(str(here.seller.person_id))
            marathi = await _second_seller(here)
            await _rules(here, hindi, languages=["Hindi"], areas=["Pune"])
            await _rules(here, marathi, languages=["Marathi"])

            first = await _add(
                here, "Fictional Hindi", "98760 81001", language="Hindi", city="Pune"
            )
            assert first["owner_person_id"] == str(hindi)
            second = await _add(here, "Fictional Marathi", "98760 81002", language="Marathi")
            assert second["owner_person_id"] == str(marathi)

            # At her limit: nobody free speaks Marathi, so it goes to the least-loaded free
            # seller and says so, rather than going cold (language is relaxed last).
            await _rules(here, marathi, languages=["Marathi"], max_open=1)
            third = await _add(here, "Fictional Gap", "98760 81003", language="Marathi")
            assert third["owner_person_id"] == str(hindi)
            assert third["owner_reason"].startswith("Nobody free speaks Marathi")

            # Away, and the other at her limit: nobody can take it, so it waits for a manager.
            await _rules(here, hindi, available=False, languages=["Hindi"], areas=["Pune"])
            fourth = await _add(here, "Fictional Waiting", "98760 81004", language="Hindi")
            assert fourth["owner_person_id"] is None
            assert "open-lead limit" in fourth["owner_reason"]

    run(exercise())


def test_auto_reassign_moves_an_uncalled_lead_by_itself(
    postgres_harness: Any, tmp_path: Path
) -> None:
    async def exercise() -> None:
        async with world(postgres_harness, tmp_path) as here:
            await _second_seller(here)
            lead = await _add(here, "Fictional Uncalled", "98760 81011")
            first_owner = lead["owner_person_id"]
            assert first_owner is not None
            async with here.setup.sessions() as db, db.begin():
                await db.execute(
                    update(Lead)
                    .where(Lead.id == UUID(lead["lead_id"]))
                    .values(assigned_at=datetime.now(UTC) - timedelta(minutes=10))
                )

            async def pass_now() -> int:
                async with here.setup.sessions() as db, db.begin():
                    return await reassign.reassign_due(db, datetime.now(UTC))

            # Off: nothing moves.
            assert await pass_now() == 0
            team = await _team(here)
            saved = await here.client.put(
                f"{BASE}/settings",
                json={
                    "expected_revision": team["settings"]["revision"],
                    "auto_reassign": True,
                    "reassign_minutes": 5,
                },
                headers=WRITE,
            )
            assert saved.status_code == 200, saved.text
            # On: the minute's pass moves it, with nobody pressing "Check now".
            assert await pass_now() == 1
            stored = await here.stored(lead["lead_id"])
            assert stored.owner_person_id is not None
            assert str(stored.owner_person_id) != first_owner
            assert (stored.owner_reason or "").startswith("No call in 5 minutes.")
            # Just moved: it isn't moved again until another five minutes pass.
            assert await pass_now() == 0

    run(exercise())


def test_a_pipeline_takes_new_leads_from_the_sources_picked_for_it(
    postgres_harness: Any, tmp_path: Path
) -> None:
    async def exercise() -> None:
        async with world(postgres_harness, tmp_path) as here:
            here.as_admin()
            made = await here.client.post(
                f"{BASE}/pipelines",
                json={
                    "name": "Referrals",
                    "template": "inside_sales_demos",
                    "sources": ["referral"],
                },
                headers=WRITE,
            )
            assert made.status_code == 200, made.text
            key = next(
                item["key"] for item in made.json()["pipelines"] if item["name"] == "Referrals"
            )
            referred = await _add(here, "Fictional Referred", "98760 81021", source="referral")
            typed = await _add(here, "Fictional Typed", "98760 81022")
            assert referred["pipeline"] == key
            assert typed["pipeline"] == "main"
            assert referred["stage"] == typed["stage"] == "new"

    run(exercise())


def test_work_hours_hold_new_leads_until_work_starts(postgres_harness: Any, tmp_path: Path) -> None:
    async def exercise() -> None:
        async with world(postgres_harness, tmp_path) as here:
            india = ZoneInfo("Asia/Kolkata")
            tomorrow = datetime.now(india) + timedelta(days=1)

            async def hours_are(**body: Any) -> None:
                team = await _team(here)
                saved = await here.client.put(
                    f"{BASE}/work-hours",
                    json={"expected_revision": team["settings"]["revision"], **body},
                    headers=WRITE,
                )
                assert saved.status_code == 200, saved.text

            # Only tomorrow is a work day, and new leads wait outside work hours.
            await hours_are(days=[tomorrow.weekday()], start="09:30", end="19:00", pause_leads=True)
            held = await _add(here, "Fictional Night Lead", "98760 81031")
            assert held["owner_person_id"] is None
            assert held["owner_reason"].startswith(hours.HELD)
            # Work starts: the minute's pass gives it to a seller.
            starts = tomorrow.replace(hour=10, minute=0, second=0, microsecond=0)
            async with here.setup.sessions() as db, db.begin():
                released = await hours.release_held(db, starts.astimezone(UTC))
            assert released == 1
            assert (await here.stored(held["lead_id"])).owner_person_id is not None

            # Saving work hours that have begun gives the waiting leads out at once.
            later = await _add(here, "Fictional Later Lead", "98760 81032")
            assert later["owner_person_id"] is None
            await hours_are(days=list(range(7)), start="00:00", end="23:59", pause_leads=True)
            assert (await here.stored(later["lead_id"])).owner_person_id is not None

    run(exercise())
