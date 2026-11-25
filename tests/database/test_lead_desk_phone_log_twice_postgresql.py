"""A call is counted once, whichever phone sends it (WL-SX-ACTIVITY, 23 Nov 2026: one seller's
call log was stored twice, eight calls each in the same second on the same lead, so their
work read double). A reinstall or a second registered phone sends the same call history
under a new device id; a phone can also keep two rows for one call. Same lead, same start
second, direction and length: the one call it already is, and the phone learns its event.
A call one second apart, or of another length, is a call of its own. Made-up people only."""

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
from tests.database.test_lead_desk_honest_connected_postgresql import all_day
from tests.database.test_lead_os_acceptance_postgresql import BASE, ROOT, WRITE, world


@pytest.fixture(scope="module")
def postgres_harness() -> Iterator[Engine]:
    yield from conversation_harness(ROOT)


def _row(
    log_id: str, at: datetime, seconds: int = 95, direction: str = "outgoing"
) -> dict[str, Any]:
    return {
        "log_id": log_id,
        "number": "9876072001",
        "started_at": at.isoformat(),
        "duration_seconds": seconds,
        "direction": direction,
    }


def test_the_same_call_from_two_phones_is_one_call(postgres_harness: Any, tmp_path: Path) -> None:
    async def exercise() -> None:
        async with world(postgres_harness, tmp_path) as here:
            await all_day(here)
            lead = await here.add("Fictional Twice Logged", "98760 72001")
            now = datetime.now(UTC).replace(microsecond=0)
            async with here.setup.sessions() as db, db.begin():
                await db.execute(
                    update(Lead)
                    .where(Lead.id == UUID(lead))
                    .values(created_at=now - timedelta(days=30))
                )
            first, second = now - timedelta(days=2), now - timedelta(days=1)
            sent = await here.client.post(
                f"{BASE}/phone-log",
                json={
                    "device_id": str(uuid4()),
                    "calls": [
                        _row("11", first),
                        _row("12", second, seconds=40),
                        # The same call twice in one history (another row id, same call).
                        _row("13", second, seconds=40),
                    ],
                },
                headers=WRITE,
            )
            assert sent.status_code == 200, sent.text
            assert (sent.json()["logged"], sent.json()["already"]) == (2, 1)
            events = {c["log_id"]: c["event_id"] for c in sent.json()["calls"]}
            assert events["12"] == events["13"]

            # The phone reinstalled: a new device id sends the same history again.
            again = await here.client.post(
                f"{BASE}/phone-log",
                json={
                    "device_id": str(uuid4()),
                    "calls": [
                        _row("901", first),
                        _row("902", second, seconds=40),
                        # Not the same call: one second later, or another length.
                        _row("903", second + timedelta(seconds=1), seconds=40),
                        _row("904", first, seconds=96),
                    ],
                },
                headers=WRITE,
            )
            assert again.status_code == 200, again.text
            assert (again.json()["logged"], again.json()["already"]) == (2, 2)
            known = {c["log_id"]: c["event_id"] for c in again.json()["calls"]}
            assert known["901"] == events["11"] and known["902"] == events["12"]

            detail = await here.detail(lead)
            assert len([e for e in detail["events"] if e.get("via") == "phone"]) == 4
            assert detail["lead"]["calls"] == 4

    run(exercise())
