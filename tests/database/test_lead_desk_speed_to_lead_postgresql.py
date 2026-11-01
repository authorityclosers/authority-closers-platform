"""Speed to lead on PostgreSQL (competitor teardown #4, 1 Nov 2026): a new Inbound enquiry nobody
has called, received in the last 24 hours, is the top of To Call, newest first, ahead of what is
due and of older never-called leads; a missed call not yet returned still goes before it; a Cold
list's fresh import never jumps the queue. Home's next lead is the list's first row. Made-up
people and numbers only."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Engine, update

from ac_platform.lead_desk.hours import IST
from ac_platform.lead_desk.models import Lead, LeadEvent
from tests.database.conversation_harness import conversation_harness
from tests.database.test_conversation_postgresql import run
from tests.database.test_lead_os_acceptance_postgresql import BASE, ROOT, world


@pytest.fixture(scope="module")
def postgres_harness() -> Iterator[Engine]:
    yield from conversation_harness(ROOT)


def test_a_fresh_enquiry_tops_to_call(postgres_harness: Any, tmp_path: Path) -> None:
    async def exercise() -> None:
        async with world(postgres_harness, tmp_path) as here:
            now = datetime.now(UTC)
            if (now - timedelta(minutes=10)).astimezone(IST).date() != now.astimezone(IST).date():
                pytest.skip("the follow-up due would be yesterday's, just after midnight")
            # name: (stage, next action, arrived, side)
            shapes: dict[str, tuple[str, datetime | None, datetime, str]] = {
                "Fictional untouched": ("new", None, now - timedelta(days=3), "live"),
                "Fictional due": (
                    "interested",
                    now - timedelta(minutes=10),
                    now - timedelta(days=6),
                    "live",
                ),
                "Fictional enquiry 40 min": ("new", None, now - timedelta(minutes=40), "live"),
                "Fictional enquiry 5 min": ("new", None, now - timedelta(minutes=5), "live"),
                "Fictional rang back": ("new", None, now - timedelta(days=2), "live"),
                "Fictional cold import": ("new", None, now - timedelta(minutes=1), "cold"),
            }
            ids: dict[str, UUID] = {}
            for n, name in enumerate(shapes):
                ids[name] = UUID(await here.add(name, f"98760 6{n:04d}"))
            async with here.setup.sessions() as db, db.begin():
                for name, (stage, at, arrived, side) in shapes.items():
                    await db.execute(
                        update(Lead)
                        .where(Lead.id == ids[name])
                        .values(
                            stage=stage,
                            step=None,
                            next_action_at=at,
                            created_at=arrived,
                            received_at=None,
                            pipeline=side,
                        )
                    )
                # They rang ten minutes ago and nobody picked up.
                db.add(
                    LeadEvent(
                        id=uuid4(),
                        tenant_id=here.tenant_id,
                        lead_id=ids["Fictional rang back"],
                        kind="call",
                        actor_person_id=here.seller.person_id,
                        data={
                            "via": "phone",
                            "direction": "missed",
                            "duration_seconds": 0,
                            "connected": False,
                        },
                        created_at=now - timedelta(minutes=10),
                    )
                )
            here.as_seller()
            listed = await here.client.get(
                f"{BASE}/leads", params={"scope": "mine", "side": "inbound", "view": "to_call"}
            )
            assert listed.status_code == 200, listed.text
            assert [row["name"] for row in listed.json()["leads"]] == [
                "Fictional rang back",
                "Fictional enquiry 5 min",
                "Fictional enquiry 40 min",
                "Fictional due",
                "Fictional untouched",
            ]
            desk = (await here.client.get(BASE)).json()
            assert desk["sides"]["inbound"]["next_lead"]["name"] == "Fictional rang back"
            # A Cold list's fresh import keeps its place on Cold.
            assert desk["sides"]["cold"]["next_lead"]["name"] == "Fictional cold import"

    run(exercise())
