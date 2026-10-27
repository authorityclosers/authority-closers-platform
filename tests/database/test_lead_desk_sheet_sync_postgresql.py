"""Connected Google Sheets sync by themselves every 10 minutes (leads setup audit, 27 Oct
2026), on PostgreSQL with Google faked: new rows come in, rows seen before don't double, and
a sheet that can't be read says why on its card."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import Engine, select

from ac_platform.lead_desk import sheet_sync
from ac_platform.lead_desk.models import Lead
from ac_platform.lead_desk.store import DeskError
from tests.database.conversation_harness import conversation_harness
from tests.database.test_conversation_postgresql import run
from tests.database.test_lead_os_acceptance_postgresql import BASE, ROOT, WRITE, world

SHEET = "https://docs.google.com/spreadsheets/d/1FictionalSheetId0123456789abcdef/edit#gid=0"


@pytest.fixture(scope="module")
def postgres_harness() -> Iterator[Engine]:
    yield from conversation_harness(ROOT)


def test_a_connected_sheet_brings_its_new_rows_in_by_itself(
    postgres_harness: Any, tmp_path: Path
) -> None:
    async def exercise() -> None:
        async with world(postgres_harness, tmp_path) as here:
            here.as_admin()
            made = await here.client.post(
                f"{BASE}/sources",
                json={"kind": "sheet", "label": "Fictional Sheet", "sheet_url": SHEET},
                headers=WRITE,
            )
            assert made.status_code == 201, made.text
            source_id = made.json()["source_id"]
            rows = ["name,phone", "Fictional One,98760 82001", "Fictional Two,98760 82002"]
            asked: list[str] = []
            broken: list[bool] = [False]

            async def fetch(url: str) -> bytes:
                asked.append(url)
                if broken[0]:
                    raise DeskError(422, "Sales Xray can't open this sheet.")
                return "\n".join(rows).encode()

            now = datetime.now(UTC)

            async def sync(at: datetime) -> int:
                return await sheet_sync.sync_due(here.setup.sessions, at, fetch=fetch)

            async def names() -> set[str]:
                async with here.setup.sessions() as db:
                    found = await db.scalars(
                        select(Lead.name).where(
                            Lead.tenant_id == here.tenant_id, Lead.source == "sheet"
                        )
                    )
                    return set(found.all())

            async def problem() -> str | None:
                listed = await here.client.get(f"{BASE}/sources")
                assert listed.status_code == 200, listed.text
                [sheet] = [
                    item for item in listed.json()["sources"] if item["source_id"] == source_id
                ]
                value: str | None = sheet.get("problem")
                return value

            # The first pass reads it (its CSV export) and files both rows.
            assert await sync(now) == 2
            assert asked and "/export?format=csv&gid=0" in asked[0]
            assert await names() == {"Fictional One", "Fictional Two"}
            # A minute later it isn't due: Google isn't asked again.
            assert await sync(now + timedelta(minutes=1)) == 0
            assert len(asked) == 1
            # Ten minutes on, a new row comes in once; the old rows stay as they were.
            rows.append("Fictional Three,98760 82003")
            assert await sync(now + timedelta(minutes=11)) == 1
            assert await names() == {"Fictional One", "Fictional Two", "Fictional Three"}
            # A sheet that can't be read says why, and is tried again later.
            broken[0] = True
            assert await sync(now + timedelta(minutes=22)) == 0
            assert "can't open" in (await problem() or "")
            broken[0] = False
            assert await sync(now + timedelta(minutes=33)) == 0
            assert await problem() is None
            # Switched off, it isn't read at all.
            off = await here.client.post(
                f"{BASE}/sources/{source_id}/active", json={"active": False}, headers=WRITE
            )
            assert off.status_code == 200, off.text
            before = len(asked)
            assert await sync(now + timedelta(minutes=44)) == 0
            assert len(asked) == before

    run(exercise())
