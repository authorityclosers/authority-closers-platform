"""Real PostgreSQL: Admin Health's stuck lead calls (no recording 30 minutes after the call)."""

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Engine

from ac_platform.lead_desk.capture_stuck import stuck_calls
from ac_platform.lead_desk.models import LeadEvent
from ac_platform.lead_desk.store import PRIVATE_CALL
from tests.database.conversation_harness import conversation_harness
from tests.database.test_conversation_postgresql import run
from tests.database.test_lead_os_acceptance_postgresql import ROOT, world


@pytest.fixture(scope="module")
def postgres_harness() -> Iterator[Engine]:
    yield from conversation_harness(ROOT)


def test_stuck_calls_are_connected_late_unrecorded_and_not_private(
    postgres_harness: Any, tmp_path: Path
):
    async def exercise():
        async with world(postgres_harness, tmp_path) as here:
            lead = UUID(await here.add("Alex Example", "+12025550123"))
            now = datetime.now(UTC)
            late = now - timedelta(minutes=45)
            stuck, recorded, private, missed, recent, sample, attachment, marker = [
                uuid4() for _ in range(8)
            ]
            rows = [
                (stuck, "call", {"via": "phone", "duration_seconds": 45}, late),
                (recorded, "call", {"via": "phone", "duration_seconds": 30}, late),
                (private, "call", {"via": "phone", "duration_seconds": 20}, late),
                (missed, "call", {"via": "phone", "direction": "missed"}, late),
                (recent, "call", {"via": "phone", "duration_seconds": 20}, now),
                (sample, "call", {"simulated": True, "duration_seconds": 20}, late),
                (
                    attachment,
                    "call",
                    {"recording": True, "for_call": str(recorded), "submission_id": str(uuid4())},
                    late + timedelta(minutes=2),
                ),
                (marker, "edited", {PRIVATE_CALL: str(private), "private": True}, late),
            ]
            async with here.setup.sessions() as db, db.begin():
                for eid, kind, data, at in rows:
                    db.add(
                        LeadEvent(
                            id=eid,
                            tenant_id=here.tenant_id,
                            lead_id=lead,
                            kind=kind,
                            actor_person_id=here.seller.person_id,
                            command_id=uuid4(),
                            data=data,
                            created_at=at,
                        )
                    )
            async with here.setup.sessions() as db, db.begin():
                result = await stuck_calls(db, now=now)
            ours = [call for call in result["calls"] if call["tenant_id"] == str(here.tenant_id)]
            assert [call["event_id"] for call in ours] == [str(stuck)]
            assert ours[0]["reason"] == "no_recording"
            assert ours[0]["seconds"] == 45
            # Workspace and seller only: never the lead's name or number.
            assert set(ours[0]) == {
                "event_id",
                "tenant_id",
                "workspace",
                "seller",
                "at",
                "seconds",
                "reason",
            }
            assert result["truncated"] is False

    run(exercise())
