"""A Call-button dial its seller says was never placed ("Didn't call") is no call, on
PostgreSQL (Redmi QA, 13 Nov 2026: on a phone without call history, a back-out from the
dialler counted as Attempted, stayed on Calls as "outcome unknown" and kept its Finish line).
Marked not placed, it leaves the numbers, the Finish line, Calls and the lead's call count, and
marking it again changes nothing; nothing is deleted. Its Undo reverses the marking (the newest
marker wins), so it counts and waits again. Made-up people only."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import Engine

from ac_platform.lead_desk.hours import IST
from tests.database.conversation_harness import conversation_harness
from tests.database.test_conversation_postgresql import run
from tests.database.test_lead_desk_honest_connected_postgresql import all_day
from tests.database.test_lead_os_acceptance_postgresql import BASE, ROOT, WRITE, world


@pytest.fixture(scope="module")
def postgres_harness() -> Iterator[Engine]:
    yield from conversation_harness(ROOT)


def test_a_dial_never_placed_is_no_call(postgres_harness: Any, tmp_path: Path) -> None:
    async def exercise() -> None:
        async with world(postgres_harness, tmp_path) as here:
            now = datetime.now(UTC)
            if (now - timedelta(minutes=5)).astimezone(IST).date() != now.astimezone(IST).date():
                pytest.skip("the dial would be yesterday's, just after midnight")
            await all_day(here)
            lead = await here.add("Fictional Back Out", "98760 69201")

            # The Call button opened the dialler; the seller backed out and came back.
            dialled = await here.client.post(
                f"{BASE}/leads/{lead}/calls/phone",
                json={"command_id": str(uuid4()), "duration_seconds": 6},
                headers=WRITE,
            )
            assert dialled.status_code == 200, dialled.text
            assert dialled.json()["lead"]["calls"] == 1
            # The lead's history knows it for a dial, so it never reads as a call's length.
            [dial] = [event for event in dialled.json()["events"] if event["kind"] == "call"]
            assert dial["estimated"] is True
            desk = (await here.client.get(BASE)).json()
            assert desk["numbers"]["calls"] == 1
            [waiting] = [row for row in desk["unanswered"] if row["lead_id"] == lead]

            mark = {"command_id": str(uuid4()), "private": True, "reason": "not_placed"}
            marked = await here.client.post(
                f"{BASE}/calls/{waiting['event_id']}/private", json=mark, headers=WRITE
            )
            assert marked.status_code == 200, marked.text
            assert marked.json()["lead"]["calls"] == 0
            # The same request again changes nothing.
            again = await here.client.post(
                f"{BASE}/calls/{waiting['event_id']}/private", json=mark, headers=WRITE
            )
            assert again.status_code == 200, again.text
            assert again.json()["lead"]["calls"] == 0

            desk = (await here.client.get(BASE)).json()
            assert desk["numbers"]["calls"] == 0
            assert not [row for row in desk["unanswered"] if row["lead_id"] == lead]
            page = (
                await here.client.get(f"{BASE}/activity", params={"day": "today", "kind": "call"})
            ).json()
            assert not [item for item in page["items"] if item["lead_id"] == lead]
            assert page["today_counts"].get("call", 0) == 0
            # Nor on the lead's own history, for its seller.
            history = (await here.client.get(f"{BASE}/leads/{lead}")).json()["events"]
            assert not [event for event in history if event["kind"] == "call"]

            # Its Undo (13 Nov 2026): the marking reversed, it is the dial it was again.
            undo = {"command_id": str(uuid4()), "private": False, "reason": "not_placed"}
            undone = await here.client.post(
                f"{BASE}/calls/{waiting['event_id']}/private", json=undo, headers=WRITE
            )
            assert undone.status_code == 200, undone.text
            assert undone.json()["lead"]["calls"] == 1
            desk = (await here.client.get(BASE)).json()
            assert desk["numbers"]["calls"] == 1
            assert [row for row in desk["unanswered"] if row["lead_id"] == lead]
            history = (await here.client.get(f"{BASE}/leads/{lead}")).json()["events"]
            assert [event for event in history if event["kind"] == "call"]
            # Put away again, it leaves again.
            remarked = await here.client.post(
                f"{BASE}/calls/{waiting['event_id']}/private",
                json={**mark, "command_id": str(uuid4())},
                headers=WRITE,
            )
            assert remarked.status_code == 200, remarked.text
            assert remarked.json()["lead"]["calls"] == 0
            assert (await here.client.get(BASE)).json()["numbers"]["calls"] == 0

            # A dial the phone's call history timed was placed: it can't be marked.
            timed = await here.add("Fictional Real Call", "98760 69202")
            placed = await here.client.post(
                f"{BASE}/leads/{timed}/calls/phone",
                json={"command_id": str(uuid4()), "duration_seconds": 60},
                headers=WRITE,
            )
            assert placed.status_code == 200, placed.text
            sent = await here.client.post(
                f"{BASE}/phone-log",
                json={
                    "device_id": str(uuid4()),
                    "calls": [
                        {
                            "log_id": "801",
                            "number": "9876069202",
                            "started_at": (now - timedelta(minutes=1)).isoformat(),
                            "duration_seconds": 40,
                            "direction": "outgoing",
                            "in_app": True,
                        }
                    ],
                },
                headers=WRITE,
            )
            assert sent.status_code == 200, sent.text
            assert sent.json()["timed"] == ["801"]
            [real] = [
                item
                for item in (
                    await here.client.get(
                        f"{BASE}/activity", params={"day": "today", "kind": "call"}
                    )
                ).json()["items"]
                if item["lead_id"] == timed
            ]
            refused = await here.client.post(
                f"{BASE}/calls/{real['event_id']}/private",
                json={"command_id": str(uuid4()), "private": True, "reason": "not_placed"},
                headers=WRITE,
            )
            assert refused.status_code == 409, refused.text
            assert (await here.client.get(BASE)).json()["numbers"]["calls"] == 1

    run(exercise())
