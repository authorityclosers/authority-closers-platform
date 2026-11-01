"""The Performance page's read on PostgreSQL (owner and Dipak, 30 Oct 2026, Leads redesign
section 6 and Dipak's table): Inbound and Cold leads are measured apart, so an uploaded list
never moves an Inbound number; a seller sees their own, owners and admins the team."""

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
from tests.database.test_lead_os_acceptance_postgresql import BASE, ROOT, WRITE, world


@pytest.fixture(scope="module")
def postgres_harness() -> Iterator[Engine]:
    yield from conversation_harness(ROOT)


def test_inbound_and_cold_are_measured_apart(postgres_harness: Any, tmp_path: Path) -> None:
    async def exercise() -> None:
        async with world(postgres_harness, tmp_path) as here:
            inbound = await here.add("Fictional Effort Inbound", "98760 67031")
            cold = await here.add("Fictional Effort Cold", "98760 67032")
            other = await here.add("Fictional Effort Cold Two", "98760 67033")
            # Two leads from an uploaded list are Cold (the test's own rows).
            async with here.setup.sessions() as db, db.begin():
                await db.execute(
                    update(Lead)
                    .where(Lead.id.in_([UUID(cold), UUID(other)]))
                    .values(pipeline="cold")
                )
            # Calls from the app's Call button: 95 s away from the app on the Inbound lead
            # (an estimate, never talk time); nobody answered the Cold one.
            for lead_id, seconds in ((inbound, 95), (cold, 0)):
                placed = await here.client.post(
                    f"{BASE}/leads/{lead_id}/calls/phone",
                    json={"command_id": str(uuid4()), "duration_seconds": seconds},
                    headers=WRITE,
                )
                assert placed.status_code == 200, placed.text
            moved = await here.dispose(
                inbound,
                connected=True,
                stage="interested",
                follow_up_at=(datetime.now(UTC) + timedelta(days=1)).isoformat(),
            )
            assert moved.status_code == 200, moved.text

            mine = (await here.client.get(f"{BASE}/performance/sellers?days=1")).json()
            assert mine["team"] is False and len(mine["sellers"]) == 1
            own = mine["sellers"][0]
            assert own["person_id"] == str(here.seller.person_id)
            hot, cool = own["inbound"], own["cold"]
            assert (hot["attempted"], hot["connected"], hot["talk_seconds"]) == (1, 1, 0)
            assert hot["talk_estimated_seconds"] == 95
            assert (hot["reached"], hot["interested"], hot["worked_interested"]) == (1, 1, 1)
            assert hot["first_call_minutes"] is not None
            assert (cool["attempted"], cool["connected"], cool["leads_attempted"]) == (1, 0, 1)
            # Both Cold leads are still in the first stage, as Leads counts Unworked (a call
            # nobody answered and no answer after it leaves a lead there; ph1-31, 1 Nov 2026);
            # coverage's whole is both Cold leads.
            assert (cool["backlog"], cool["eligible"]) == (2, 2)
            # First-call speed is Inbound's only: a list's import time says nothing.
            assert cool["first_call_minutes"] is None
            assert mine["inbound"] == hot and mine["cold"] == cool

            here.as_admin()
            team = (await here.client.get(f"{BASE}/performance/sellers?days=1")).json()
            assert team["team"] is True
            assert (team["inbound"]["attempted"], team["cold"]["attempted"]) == (1, 1)
            assert str(here.seller.person_id) in {seller["person_id"] for seller in team["sellers"]}
            refused = await here.client.get(f"{BASE}/performance/sellers?days=3")
            assert refused.status_code == 422

    run(exercise())
