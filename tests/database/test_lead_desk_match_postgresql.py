"""Add lead says while typing that a number is already a lead (PostgreSQL, 22 Oct 2026).

A manager sees the lead; its owner sees it as theirs; another seller learns only that a
teammate has the number; a new or unreadable number is not found.
"""

from pathlib import Path
from typing import Any, cast
from uuid import uuid4

import httpx
import pytest

from tests.database.test_conversation_account_library_postgresql import _session
from tests.database.test_conversation_postgresql import postgres_harness as _postgres_harness
from tests.database.test_conversation_postgresql import run, seed
from tests.database.test_conversation_submission_http_postgresql import ORIGIN, _setup
from tests.database.test_lead_desk_journey_postgresql import _organisation

WRITE = {"Origin": ORIGIN, "Content-Type": "application/json"}
BASE = "/v1/lead-desk"


@pytest.fixture
def postgres_harness() -> Any:
    yield from cast(Any, _postgres_harness).__wrapped__()


def test_a_number_already_a_lead_is_said_before_add(postgres_harness: Any, tmp_path: Path) -> None:
    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path)
        try:
            await _organisation(setup)
            seller = await seed(setup.engine, tenant_id=setup.state.tenant_id, role="member")
            seller_token = await _session(setup, seller)
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=setup.app), base_url=ORIGIN
            ) as client:

                def as_(token: str) -> None:
                    client.cookies.set(setup.settings.session_cookie_name, token)

                as_(setup.token)
                added = await client.post(
                    f"{BASE}/leads",
                    json={
                        "command_id": str(uuid4()),
                        "name": "Fictional Buyer",
                        "phone": "98765 43210",
                        "assign": "me",
                    },
                    headers=WRITE,
                )
                assert added.status_code == 201, added.text
                lead_id = added.json()["lead"]["lead_id"]

                seen = (await client.get(f"{BASE}/leads/match?phone=%2B91 98765-43210")).json()
                assert seen["found"] is True and seen["lead_id"] == lead_id
                assert seen["name"] == "Fictional Buyer" and seen["yours"] is True
                assert seen["stage_label"]

                assert (await client.get(f"{BASE}/leads/match?phone=98765 00000")).json()[
                    "found"
                ] is False
                assert (await client.get(f"{BASE}/leads/match?phone=12")).json()["found"] is False
                assert (await client.get(f"{BASE}/leads/match")).status_code == 422

                # Another seller learns only that a teammate has the number.
                as_(seller_token)
                hidden = (await client.get(f"{BASE}/leads/match?phone=9876543210")).json()
                assert hidden["found"] is True and hidden["yours"] is False
                assert hidden["lead_id"] is None and hidden["name"] is None
        finally:
            await setup.engine.dispose()

    run(exercise())
