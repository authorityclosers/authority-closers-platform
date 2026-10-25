"""One-tap Email on a lead card (owner, 24 Oct 2026): a list row says whether the lead has
an email address, and never the address itself."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import Engine

from tests.database.conversation_harness import conversation_harness
from tests.database.test_conversation_postgresql import run
from tests.database.test_lead_os_acceptance_postgresql import BASE, ROOT, WRITE, world


@pytest.fixture(scope="module")
def postgres_harness() -> Iterator[Engine]:
    yield from conversation_harness(ROOT)


def test_a_row_says_whether_its_lead_has_an_email_and_never_shows_it(
    postgres_harness: Any, tmp_path: Path
) -> None:
    async def exercise() -> None:
        async with world(postgres_harness, tmp_path) as here:
            here.as_admin()
            for name, phone, email in (
                ("Fictional Mail One", "98760 62001", "one@example.test"),
                ("Fictional Mail Two", "98760 62002", None),
            ):
                body: dict[str, Any] = {"command_id": str(uuid4()), "name": name, "phone": phone}
                if email:
                    body["email"] = email
                added = await here.client.post(f"{BASE}/leads", json=body, headers=WRITE)
                assert added.status_code == 201, added.text
            page = await here.client.get(f"{BASE}/leads", params={"scope": "team"})
            assert page.status_code == 200, page.text
            rows = {row["name"]: row for row in page.json()["leads"]}
            assert rows["Fictional Mail One"]["has_email"] is True
            assert rows["Fictional Mail Two"]["has_email"] is False
            assert "one@example.test" not in page.text

    run(exercise())
