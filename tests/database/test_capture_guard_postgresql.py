"""Real PostgreSQL HTTP contract: missing calls, attachments, scope and privacy."""

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Engine

from ac_platform.lead_desk.models import LeadEvent
from tests.database.conversation_harness import conversation_harness
from tests.database.test_conversation_postgresql import run
from tests.database.test_lead_os_acceptance_postgresql import BASE, ROOT, WRITE, world


@pytest.fixture(scope="module")
def postgres_harness() -> Iterator[Engine]:
    yield from conversation_harness(ROOT)


def test_capture_guard_scope_missing_attachment_and_privacy(postgres_harness: Any, tmp_path: Path):
    async def exercise():
        async with world(postgres_harness, tmp_path) as here:
            lead = UUID(await here.add("Alex Example", "+12025550123"))
            now = datetime.now(UTC)
            old, waiting, other, attachment, simulated = [uuid4() for _ in range(5)]
            async with here.setup.sessions() as db, db.begin():
                for eid, actor, data, at in [
                    (
                        old,
                        here.seller.person_id,
                        {"via": "phone", "duration_seconds": 45},
                        now - timedelta(minutes=31),
                    ),
                    (waiting, here.seller.person_id, {"via": "phone", "duration_seconds": 20}, now),
                    (other, here.setup.state.person_id, {"via": "phone"}, now),
                    (
                        attachment,
                        here.seller.person_id,
                        {"recording": True, "for_call": str(old), "submission_id": str(uuid4())},
                        now,
                    ),
                    (simulated, here.seller.person_id, {"simulated": True}, now),
                ]:
                    db.add(
                        LeadEvent(
                            id=eid,
                            tenant_id=here.tenant_id,
                            lead_id=lead,
                            kind="call",
                            actor_person_id=actor,
                            command_id=uuid4(),
                            data=data,
                            created_at=at,
                        )
                    )
            here.as_seller()
            result = await here.client.get(f"{BASE}/capture-guard")
            assert result.status_code == 200, result.text
            calls = {row["event_id"]: row for row in result.json()["calls"]}
            assert set(calls) == {str(old), str(waiting)}
            assert (
                calls[str(old)]["state"] == "missing"
            )  # A claimed attachment isn't a server receipt.
            assert calls[str(waiting)]["state"] == "waiting"
            assert result.json()["rates"][0]["calls"] == 2
            assert result.json()["rates"][0]["received"] == 0
            hidden = await here.client.get(f"{BASE}/capture-guard?event_id={other}")
            assert hidden.json()["calls"] == []
            assert (await here.client.get(f"{BASE}/capture-guard?days=32")).status_code == 422
            here.as_admin()
            assert len((await here.client.get(f"{BASE}/capture-guard")).json()["calls"]) == 3
            here.as_seller()
            private = await here.client.post(
                f"{BASE}/calls/{old}/private",
                json={"command_id": str(uuid4()), "private": True},
                headers=WRITE,
            )
            assert private.status_code == 200, private.text
            here.as_admin()
            assert str(old) not in {
                c["event_id"]
                for c in (await here.client.get(f"{BASE}/capture-guard")).json()["calls"]
            }
            here.client.cookies.clear()
            assert (await here.client.get(f"{BASE}/capture-guard")).status_code in {401, 403}

    run(exercise())
