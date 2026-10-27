"""Strict languages through the API, on PostgreSQL (27 Oct 2026): Lead rules' switch is
saved with the team settings, and a lead nobody free speaks then waits for a manager."""

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


def test_strict_languages_hold_a_lead_nobody_speaks(postgres_harness: Any, tmp_path: Path) -> None:
    async def exercise() -> None:
        async with world(postgres_harness, tmp_path) as here:
            here.as_admin()

            async def add(name: str, phone: str) -> dict[str, Any]:
                added = await here.client.post(
                    f"{BASE}/leads",
                    json={
                        "command_id": str(uuid4()),
                        "name": name,
                        "phone": phone,
                        "language": "Marathi",
                    },
                    headers=WRITE,
                )
                assert added.status_code == 201, added.text
                body: dict[str, Any] = added.json()
                return body

            team = (await here.client.get(f"{BASE}/team")).json()
            seller = next(
                rep for rep in team["reps"] if rep["person_id"] == str(here.seller.person_id)
            )
            saved = await here.client.put(
                f"{BASE}/team/{here.seller.person_id}",
                json={
                    "expected_revision": seller["revision"],
                    "available": True,
                    "max_open": 50,
                    "languages": ["Hindi"],
                },
                headers=WRITE,
            )
            assert saved.status_code == 200, saved.text
            assert saved.json()["settings"]["strict_language"] is False
            preferred = await add("Fictional Preferred", "98760 84001")
            assert preferred["lead"]["owner_person_id"] == str(here.seller.person_id)

            switched = await here.client.put(
                f"{BASE}/settings",
                json={
                    "expected_revision": saved.json()["settings"]["revision"],
                    "auto_reassign": False,
                    "reassign_minutes": 10,
                    "strict_language": True,
                },
                headers=WRITE,
            )
            assert switched.status_code == 200, switched.text
            assert switched.json()["settings"]["strict_language"] is True
            strict = await add("Fictional Strict", "98760 84002")
            assert strict["lead"]["owner_person_id"] is None
            assert strict["owner_reason"] == "Nobody free speaks Marathi; it waits for a manager."

    run(exercise())
