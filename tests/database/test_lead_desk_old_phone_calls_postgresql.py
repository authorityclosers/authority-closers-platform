"""Every call the phone keeps reaches its lead (owner, 20 Nov 2026: "No data should be deleted.
Not the call logs ... every call, everything needs to be there ... not just seven days"). A row
weeks or months old is logged as a call of its own, first read or not; sent again it is known;
only a row from a broken clock (over PHONE_LOG_MAX_DAYS) or from before its lead existed stays
off. Made-up people only."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Engine, update

from ac_platform.lead_desk.models import Lead
from ac_platform.lead_desk.store import PHONE_LOG_MAX_DAYS
from tests.database.conversation_harness import conversation_harness
from tests.database.test_conversation_postgresql import run
from tests.database.test_lead_desk_honest_connected_postgresql import all_day
from tests.database.test_lead_os_acceptance_postgresql import BASE, ROOT, WRITE, world


@pytest.fixture(scope="module")
def postgres_harness() -> Iterator[Engine]:
    yield from conversation_harness(ROOT)


def _row(log_id: str, number: str, at: datetime, seconds: int = 95) -> dict[str, Any]:
    return {
        "log_id": log_id,
        "number": number,
        "started_at": at.isoformat(),
        "duration_seconds": seconds,
        "direction": "outgoing",
    }


def test_old_calls_from_the_phone_are_kept_as_calls(postgres_harness: Any, tmp_path: Path) -> None:
    async def exercise() -> None:
        async with world(postgres_harness, tmp_path) as here:
            await all_day(here)
            regular = await here.add("Fictional Old Caller", "98760 71001")
            first_read = await here.add("Fictional First Read", "98760 71002")
            now = datetime.now(UTC)
            # Both were leads long before these calls (an import keeps the lead's own date).
            async with here.setup.sessions() as db, db.begin():
                await db.execute(
                    update(Lead)
                    .where(Lead.id.in_([UUID(regular), UUID(first_read)]))
                    .values(created_at=now - timedelta(days=400))
                )
            device = str(uuid4())
            sent = await here.client.post(
                f"{BASE}/phone-log",
                json={
                    "device_id": device,
                    "calls": [
                        _row("201", "9876071001", now - timedelta(days=3)),
                        _row("202", "9876071001", now - timedelta(days=30)),
                        _row("203", "9876071001", now - timedelta(days=200)),
                        # A broken clock: years before any phone kept it.
                        _row("204", "9876071001", now - timedelta(days=PHONE_LOG_MAX_DAYS + 5)),
                    ],
                },
                headers=WRITE,
            )
            assert sent.status_code == 200, sent.text
            assert (sent.json()["logged"], sent.json()["already"], sent.json()["skipped"]) == (
                3,
                0,
                1,
            )
            # Sent again (a dropped answer, or Find my old calls reading everything again).
            again = await here.client.post(
                f"{BASE}/phone-log",
                json={
                    "device_id": device,
                    "calls": [
                        _row("201", "9876071001", now - timedelta(days=3)),
                        _row("202", "9876071001", now - timedelta(days=30)),
                        _row("203", "9876071001", now - timedelta(days=200)),
                    ],
                },
                headers=WRITE,
            )
            assert (again.json()["logged"], again.json()["already"]) == (0, 3)

            # The phone's first read once only timed dials beyond 7 days: now it logs them too.
            first = await here.client.post(
                f"{BASE}/phone-log",
                json={
                    "device_id": str(uuid4()),
                    "backfill": True,
                    "calls": [
                        _row("301", "9876071002", now - timedelta(days=40)),
                        _row("302", "9876071002", now - timedelta(days=90), seconds=0),
                    ],
                },
                headers=WRITE,
            )
            assert first.status_code == 200, first.text
            assert first.json()["logged"] == 2

            old = await here.detail(regular)
            phone_calls = [e for e in old["events"] if e.get("via") == "phone"]
            assert len(phone_calls) == 3
            # Each sits at the time of its call, months back included.
            oldest = min(datetime.fromisoformat(e["at"]) for e in phone_calls)
            assert oldest < now - timedelta(days=199)
            assert old["lead"]["calls"] == 3
            read = await here.detail(first_read)
            assert [e.get("connected") for e in read["events"] if e.get("via") == "phone"] in (
                [True, False],
                [False, True],
            )

    run(exercise())
