"""Nudges on PostgreSQL (team engine, docs/product/lead-desk/team-engine.md, section 3 and
scenarios 10 to 14): off until an owner turns them on; a seller behind pace with a phone gets
one urgent push in a window, with no lead in it, and its words on their own session; none
after work; none for a seller the owner turned them off for."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime, time, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import Engine

from ac_platform.lead_desk import nudge_push
from tests.database.conversation_harness import conversation_harness
from tests.database.test_conversation_postgresql import run
from tests.database.test_lead_os_acceptance_postgresql import BASE, ROOT, WRITE, World, world

IST = ZoneInfo("Asia/Kolkata")


@pytest.fixture(scope="module")
def postgres_harness() -> Iterator[Engine]:
    yield from conversation_harness(ROOT)


async def nudged(here: World, now: datetime) -> list[nudge_push.NudgeAlert]:
    async with here.setup.sessions() as db, db.begin():
        alerts = await nudge_push.collect(db, now, every=timedelta(0))
    return [alert for alert in alerts if alert.tenant_id == here.tenant_id]


def test_nudges_once_a_window_in_work_hours_only(postgres_harness: Any, tmp_path: Path) -> None:
    async def exercise() -> None:
        async with world(postgres_harness, tmp_path) as here:
            today = datetime.now(IST).date()
            afternoon = datetime.combine(today, time(14, 30), tzinfo=IST)
            token = "fictional-phone-" + uuid4().hex
            registered = await here.client.post(
                f"{BASE}/devices", json={"token": token}, headers=WRITE
            )
            assert registered.status_code == 200, registered.text

            here.as_admin()
            revision = (await here.client.get(f"{BASE}/team")).json()["settings"]["revision"]
            hours = await here.client.put(
                f"{BASE}/work-hours",
                json={
                    "expected_revision": revision,
                    "days": [0, 1, 2, 3, 4, 5, 6],
                    "start": "10:00",
                    "end": "19:00",
                },
                headers=WRITE,
            )
            assert hours.status_code == 200, hours.text
            target = await here.client.put(
                f"{BASE}/targets",
                json={
                    "command_id": str(uuid4()),
                    "person_id": str(here.seller.person_id),
                    "targets": [{"metric": "calls", "period": "day", "value": 50}],
                },
                headers=WRITE,
            )
            assert target.status_code == 200, target.text

            # Off by default: behind pace with a phone, and still nothing.
            assert await nudged(here, afternoon) == []

            # A seller may not turn them on; an owner or manager may.
            here.as_seller()
            refused = await here.client.put(
                f"{BASE}/nudges",
                json={"expected_revision": revision + 1, "enabled": True},
                headers=WRITE,
            )
            assert refused.status_code == 403
            here.as_admin()
            on = await here.client.put(
                f"{BASE}/nudges",
                json={"expected_revision": revision + 1, "enabled": True},
                headers=WRITE,
            )
            assert on.status_code == 200, on.text
            assert on.json()["settings"]["nudges"] is True

            # 10. Behind at 14:30 (25 of 50 expected, none done): one urgent push, no lead.
            sent = await nudged(here, afternoon)
            assert len(sent) == 1
            assert sent[0].person_id == here.seller.person_id
            assert sent[0].tokens == [token]
            data = sent[0].data()
            assert data["kind"] == "nudge" and data["urgency"] == "urgent"
            assert "lead" not in data
            # 14. Not again in the same window, from this sender or another.
            assert await nudged(here, afternoon + timedelta(minutes=10)) == []

            # The words, on the seller's own session.
            here.as_seller()
            words = await here.client.get(f"{BASE}/alert", params={"kind": "nudge"})
            assert words.status_code == 200, words.text
            body = words.json()
            assert body["urgency"] == "urgent" and body["url"] == "/leads"
            assert body["lead_id"] is None
            assert "behind today's pace" in body["body"]

            # 11. Quiet after work.
            evening = datetime.combine(today, time(20, 0), tzinfo=IST)
            assert await nudged(here, evening) == []

            # Off for this seller: the next window brings nothing.
            here.as_admin()
            off = await here.client.put(
                f"{BASE}/nudges",
                json={
                    "expected_revision": revision + 2,
                    "enabled": True,
                    "off_for": [str(here.seller.person_id)],
                },
                headers=WRITE,
            )
            assert off.status_code == 200, off.text
            assert off.json()["settings"]["nudges_off_for"] == [str(here.seller.person_id)]
            assert await nudged(here, afternoon + timedelta(hours=2)) == []

    run(exercise())
