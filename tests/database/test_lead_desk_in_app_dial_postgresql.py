"""The phone's call-history row for its own Call-button dial times that dial, on PostgreSQL (the
orchestrator, 3 Nov 2026: Google approved call history, and the shell dropped these rows, so a
Play seller's Call-button calls stayed "outcome unknown"). A row the phone marks as its own
(``in_app``) gives the seller's dial the phone's seconds, connected, however late the seller came
back to the app to log the dial; it is never a second call, and with no dial yet it is nothing
until it comes again. Made-up people only."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Engine, select

from ac_platform.lead_desk.hours import IST
from ac_platform.lead_desk.models import LeadEvent
from tests.database.conversation_harness import conversation_harness
from tests.database.test_conversation_postgresql import run
from tests.database.test_lead_desk_honest_connected_postgresql import all_day
from tests.database.test_lead_os_acceptance_postgresql import BASE, ROOT, WRITE, world


@pytest.fixture(scope="module")
def postgres_harness() -> Iterator[Engine]:
    yield from conversation_harness(ROOT)


def test_the_phones_row_for_its_own_dial_times_it(postgres_harness: Any, tmp_path: Path) -> None:
    async def exercise() -> None:
        async with world(postgres_harness, tmp_path) as here:
            now = datetime.now(UTC)
            if (now - timedelta(minutes=40)).astimezone(IST).date() != now.astimezone(IST).date():
                pytest.skip("the call would be yesterday's, just after midnight")
            await all_day(here)
            late = await here.add("Fictional Late Return", "98760 69101")
            early = await here.add("Fictional Not Yet", "98760 69102")
            device = str(uuid4())

            def row(log_id: str, number: str, minutes_ago: int, seconds: int) -> dict[str, Any]:
                return {
                    "log_id": log_id,
                    "number": number,
                    "started_at": (now - timedelta(minutes=minutes_ago)).isoformat(),
                    "duration_seconds": seconds,
                    "direction": "outgoing",
                    "in_app": True,
                }

            # The call was 30 min ago; the seller came back to the app only now, and the page
            # logged the dial then: 30 min away.
            placed = await here.client.post(
                f"{BASE}/leads/{late}/calls/phone",
                json={"command_id": str(uuid4()), "duration_seconds": 1800},
                headers=WRITE,
            )
            assert placed.status_code == 200, placed.text
            sent = await here.client.post(
                f"{BASE}/phone-log",
                json={
                    "device_id": device,
                    "calls": [row("701", "9876069101", 30, 95), row("702", "9876069102", 5, 40)],
                },
                headers=WRITE,
            )
            assert sent.status_code == 200, sent.text
            answer = sent.json()
            # The first times its dial; the second has no dial yet, so it is nothing.
            assert (answer["logged"], answer["timed"]) == (0, ["701"])

            async with here.setup.sessions() as db:
                calls = (
                    await db.scalars(
                        select(LeadEvent.lead_id).where(
                            LeadEvent.lead_id.in_([UUID(late), UUID(early)]),
                            LeadEvent.kind == "call",
                        )
                    )
                ).all()
            assert calls == [UUID(late)]

            numbers = (await here.client.get(BASE)).json()["numbers"]
            assert (numbers["calls"], numbers["connected"], numbers["talk_seconds"]) == (1, 1, 95)
            page = (
                await here.client.get(f"{BASE}/activity", params={"day": "today", "kind": "call"})
            ).json()
            assert [
                (item["event"]["outcome"], item["event"]["seconds_from"]) for item in page["items"]
            ] == [("connected", "call_log")]

            # Sent again: known, still timed, so the phone stops sending it; never a second call.
            again = await here.client.post(
                f"{BASE}/phone-log",
                json={"device_id": device, "calls": [row("701", "9876069101", 30, 95)]},
                headers=WRITE,
            )
            assert again.status_code == 200, again.text
            assert (again.json()["logged"], again.json()["timed"]) == (0, ["701"])
            assert (await here.client.get(BASE)).json()["numbers"]["calls"] == 1

    run(exercise())
