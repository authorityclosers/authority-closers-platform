"""My work leaves out the moves a new stage list makes (AUT-2218, 25 Oct 2026: after the
nine-stage install, the approving admin's My work said "8 stage moves", each "You moved
them to Discussion Incomplete"). Those lines stay in the lead's history, marked as the
stage list's, and in no one's work."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import Engine

from tests.database.conversation_harness import conversation_harness
from tests.database.test_conversation_postgresql import run
from tests.database.test_lead_os_acceptance_postgresql import BASE, ROOT, WRITE, later, world


@pytest.fixture(scope="module")
def postgres_harness() -> Iterator[Engine]:
    yield from conversation_harness(ROOT)


def test_a_stage_list_install_is_nobodys_work(postgres_harness: Any, tmp_path: Path) -> None:
    async def exercise() -> None:
        async with world(postgres_harness, tmp_path) as here:
            lead_id = await here.add("Fictional Install One", "98760 66001")
            talked = await here.dispose(
                lead_id, connected=True, step="interested", follow_up_at=later(days=1)
            )
            assert talked.status_code == 200, talked.text
            here.as_admin()
            version = (await here.client.get(f"{BASE}/journey")).json()["version"]
            picked = await here.client.post(
                f"{BASE}/journey/template",
                json={
                    "expectedVersion": version,
                    "template": "education",
                    "map": {"interested": "counselled"},
                },
                headers=WRITE,
            )
            assert picked.status_code == 200, picked.text
            # The lead's history keeps the line, marked as the stage list's.
            events = [e for e in (await here.detail(lead_id))["events"] if e["kind"] == "stage"]
            assert [e["move_source"] for e in events] == ["template"]
            # The admin who installed it did no work on the lead.
            work = (await here.client.get(f"{BASE}/activity", params={"day": "today"})).json()
            assert [item["event"]["kind"] for item in work["items"]] == []
            assert "stage" not in work["counts"]
            # The seller's own call stays in their work.
            here.as_seller()
            mine = (await here.client.get(f"{BASE}/activity", params={"day": "today"})).json()
            assert [item["event"]["kind"] for item in mine["items"]] == ["result"]

    run(exercise())
