"""Owners and admins act on many leads at once (PostgreSQL, 22 Oct 2026).

Give leads to a seller, move them to a stage, move them to another pipeline; a lead that
is already there, or isn't on the desk, is skipped and counted; a retry changes nothing;
a seller can't.
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


def test_many_leads_at_once(postgres_harness: Any, tmp_path: Path) -> None:
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
                await client.put(
                    f"{BASE}/team/{seller.person_id}",
                    json={"expected_revision": 0, "available": True, "max_open": 50},
                    headers=WRITE,
                )
                ids = []
                for index in range(3):
                    added = await client.post(
                        f"{BASE}/leads",
                        json={
                            "command_id": str(uuid4()),
                            "name": f"Fictional Lead {index}",
                            "phone": f"98765 4321{index}",
                            "assign": "me",
                        },
                        headers=WRITE,
                    )
                    assert added.status_code == 201, added.text
                    ids.append(added.json()["lead"]["lead_id"])

                async def bulk(**body: Any) -> httpx.Response:
                    return await client.post(
                        f"{BASE}/leads/bulk",
                        json={"command_id": str(uuid4()), "lead_ids": ids, **body},
                        headers=WRITE,
                    )

                given = await bulk(action="assign", person_id=str(seller.person_id))
                assert given.status_code == 200, given.text
                assert given.json()["done"] == 3 and given.json()["skipped"] == 0

                command = str(uuid4())
                moved = await client.post(
                    f"{BASE}/leads/bulk",
                    json={
                        "command_id": command,
                        "lead_ids": [*ids, str(uuid4())],
                        "action": "stage",
                        "step": "follow_up",
                    },
                    headers=WRITE,
                )
                assert moved.status_code == 200, moved.text
                assert (moved.json()["done"], moved.json()["skipped"]) == (3, 1)
                assert moved.json()["words"].startswith("3 leads moved to")
                # The same request again: already done, nothing changes twice.
                again = await client.post(
                    f"{BASE}/leads/bulk",
                    json={
                        "command_id": command,
                        "lead_ids": ids,
                        "action": "stage",
                        "step": "follow_up",
                    },
                    headers=WRITE,
                )
                assert (again.json()["done"], again.json()["skipped"]) == (3, 0)
                there = await bulk(action="stage", step="follow_up")
                assert (there.json()["done"], there.json()["skipped"]) == (0, 3)
                detail = (await client.get(f"{BASE}/leads/{ids[0]}")).json()
                assert detail["lead"]["stage"] == "follow_up"
                assert detail["lead"]["owner_person_id"] == str(seller.person_id)

                made = await client.post(
                    f"{BASE}/pipelines",
                    json={"name": "Partners", "template": "simple", "sources": []},
                    headers=WRITE,
                )
                assert made.status_code == 200, made.text
                to_pipeline = await bulk(action="pipeline", pipeline="partners")
                assert to_pipeline.json()["done"] == 3
                page = (await client.get(f"{BASE}/leads?scope=team&pipeline=partners")).json()
                assert page["total"] == 3
                assert (await bulk(action="pipeline", pipeline="nope")).status_code == 422
                assert (await bulk(action="stage")).status_code == 422

                as_(seller_token)
                assert (await bulk(action="stage", step="won")).status_code == 403
        finally:
            await setup.engine.dispose()

    run(exercise())
