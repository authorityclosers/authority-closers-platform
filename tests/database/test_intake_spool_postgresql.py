"""The release spool's replay on PostgreSQL (lead_desk/spool.py): every lead a hold kept
is filed once, through the same key check, with the time it reached the spool."""

from __future__ import annotations

import fcntl
import json
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, TextIO

import pytest
from sqlalchemy import Engine, select

from ac_platform.lead_desk import spool
from ac_platform.lead_desk.models import Lead
from tests.database.conversation_harness import conversation_harness
from tests.database.test_conversation_postgresql import run
from tests.database.test_lead_os_acceptance_postgresql import BASE, ROOT, WRITE, world


@pytest.fixture(scope="module")
def postgres_harness() -> Iterator[Engine]:
    yield from conversation_harness(ROOT)


def test_a_held_lead_is_filed_once_with_the_time_it_arrived(
    postgres_harness: Any, tmp_path: Path
) -> None:
    async def exercise() -> None:
        async with world(postgres_harness, tmp_path) as here:
            here.as_admin()
            made = await here.client.post(
                f"{BASE}/sources",
                json={"kind": "webhook", "label": "Fictional website form"},
                headers=WRITE,
            )
            assert made.status_code == 201, made.text
            source_id, key = made.json()["source_id"], made.json()["token"]
            root = tmp_path / "spool"
            spool.prepare(root)
            arrived = datetime.now(UTC).replace(microsecond=0) - timedelta(minutes=3)
            path = f"/v1/lead-desk/capture/{source_id}"

            def keep(body: dict[str, Any], *, key: str = key, google: bool = False) -> None:
                if google:
                    body = {**body, "google_key": key}
                    entry = spool.entry_for(
                        f"{path}/google-ads", "", {}, json.dumps(body).encode(), arrived
                    )
                else:
                    entry = spool.entry_for(
                        path, "", {"X-Lead-Desk-Key": key}, json.dumps(body).encode(), arrived
                    )
                spool.write(root, entry)

            async def replay() -> dict[str, int]:
                return await spool.replay(here.setup.sessions, root, app_url="https://x.test")

            lead = {"name": "Fictional Held Lead", "phone": "98765 00021"}
            keep(lead)
            assert await replay() == {"filed": 1, "known": 0, "rejected": 0, "kept": 0}
            [held] = [row for row in await _leads(here) if row.name == "Fictional Held Lead"]
            assert held.source == "webhook"
            assert held.received_at == arrived
            assert list((root / "new").iterdir()) == []
            # Filed: the lead is in the database, so no copy stays on disk.
            assert list(root.rglob("*.json")) == []

            # The same post kept twice (a sender's own retry) is filed once.
            keep(lead)
            assert await replay() == {"filed": 0, "known": 1, "rejected": 0, "kept": 0}

            # A wrong key is never filed; the file waits in rejected/ for a week.
            keep({"name": "Fictional Wrong Key", "phone": "98765 00022"}, key="wrong-key")
            assert await replay() == {"filed": 0, "known": 0, "rejected": 1, "kept": 0}
            assert len(list((root / "rejected").iterdir())) == 1

            # Google Ads, held the same way, is filed as its webhook would be.
            keep(
                {
                    "lead_id": "fictional-google-1",
                    "user_column_data": [
                        {"column_id": "FULL_NAME", "string_value": "Fictional Google Lead"},
                        {"column_id": "PHONE_NUMBER", "string_value": "+919876500023"},
                    ],
                },
                google=True,
            )
            assert (await replay())["filed"] == 1

            # Another process replaying holds the lock: this one waits for the next minute.
            keep({"name": "Fictional Later Lead", "phone": "98765 00024"})
            lock = _held(root)
            try:
                assert await replay() == {"filed": 0, "known": 0, "rejected": 0, "kept": 0}
            finally:
                lock.close()
            assert (await replay())["filed"] == 1

            names = {row.name for row in await _leads(here)}
            assert {"Fictional Google Lead", "Fictional Later Lead"} <= names
            assert "Fictional Wrong Key" not in names

    run(exercise())


def _held(root: Path) -> TextIO:
    lock = open(root / ".replay.lock", "a")  # noqa: SIM115 - closed by the caller
    fcntl.flock(lock, fcntl.LOCK_EX)
    return lock


async def _leads(here: Any) -> list[Lead]:
    async with here.setup.sessions() as db:
        return list((await db.scalars(select(Lead).where(Lead.tenant_id == here.tenant_id))).all())
