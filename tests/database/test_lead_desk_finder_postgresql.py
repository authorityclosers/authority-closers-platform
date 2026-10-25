"""Notes and search on PostgreSQL (v0.89; owner, 24 Oct 2026): what people wrote on a
seller's leads, newest first, with the remark saved with a call's outcome; and a few words
found in leads, notes and open tasks."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import Engine

from tests.database.conversation_harness import conversation_harness
from tests.database.test_conversation_postgresql import run
from tests.database.test_lead_desk_tasks_postgresql import task
from tests.database.test_lead_os_acceptance_postgresql import (
    BASE,
    ROOT,
    WRITE,
    later,
    world,
)


@pytest.fixture(scope="module")
def postgres_harness() -> Iterator[Engine]:
    yield from conversation_harness(ROOT)


def test_notes_newest_first_with_outcome_remarks_and_search_everywhere(
    postgres_harness: Any, tmp_path: Path
) -> None:
    async def exercise() -> None:
        async with world(postgres_harness, tmp_path) as here:
            one = await here.add("Fictional Find One", "98760 63001")
            two = await here.add("Fictional Find Two", "98760 63002")
            noted = await here.client.post(
                f"{BASE}/leads/{one}/notes",
                json={"command_id": str(uuid4()), "note": "Wants the brochure on WhatsApp"},
                headers=WRITE,
            )
            assert noted.status_code == 200, noted.text
            missed = await here.dispose(
                two,
                connected=False,
                reason="did_not_pick",
                follow_up_at=later(hours=3),
                remark="Try after 6 pm, 100% sure",
            )
            assert missed.status_code == 200, missed.text
            await task(here, one, kind="send_file", starts_at=later(days=1), note="Floor plan PDF")

            # Notes: both, newest first, the outcome's remark as a note.
            page = (await here.client.get(f"{BASE}/notes")).json()
            assert [item["event"]["note"] for item in page["items"]] == [
                "Try after 6 pm, 100% sure",
                "Wants the brochure on WhatsApp",
            ]
            assert [item["lead_name"] for item in page["items"]] == [
                "Fictional Find Two",
                "Fictional Find One",
            ]
            found = (await here.client.get(f"{BASE}/notes", params={"q": "brochure"})).json()
            assert [item["lead_id"] for item in found["items"]] == [one]
            # ILIKE's own characters are only letters to look for.
            percent = (await here.client.get(f"{BASE}/notes", params={"q": "100%"})).json()
            assert [item["lead_id"] for item in percent["items"]] == [two]
            nothing = (await here.client.get(f"{BASE}/notes", params={"q": "zzzz"})).json()
            assert nothing["items"] == []

            # Search: a lead by name, a note, a task.
            by_name = (await here.client.get(f"{BASE}/search", params={"q": "Find Two"})).json()
            assert [row["lead_id"] for row in by_name["leads"]] == [two]
            by_note = (await here.client.get(f"{BASE}/search", params={"q": "whatsapp"})).json()
            assert [item["lead_id"] for item in by_note["notes"]] == [one]
            assert by_note["leads"] == [] and by_note["tasks"] == []
            by_task = (await here.client.get(f"{BASE}/search", params={"q": "floor plan"})).json()
            assert [item["lead_id"] for item in by_task["tasks"]] == [one]
            assert by_task["tasks"][0]["note"] == "Floor plan PDF"
            empty = (await here.client.get(f"{BASE}/search")).json()
            assert empty == {"schema": "lead-desk/1", "leads": [], "notes": [], "tasks": []}
            short = await here.client.get(f"{BASE}/search", params={"q": "a"})
            assert short.status_code == 422

    run(exercise())
