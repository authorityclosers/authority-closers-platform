"""One seller's leads for their profile (owner, 21 Oct 2026), through the HTTP API on PostgreSQL.

`/v1/lead-desk/leads?scope=team&owner=<person>` lists only that seller's leads, for owners
and admins; a seller can't read a teammate's, and an owner filter needs the team scope.
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
from tests.database.test_lead_desk_postgresql import _organisation

WRITE = {"Origin": ORIGIN, "Content-Type": "application/json"}
BASE = "/v1/lead-desk"


@pytest.fixture
def postgres_harness() -> Any:
    yield from cast(Any, _postgres_harness).__wrapped__()


def test_a_sellers_profile_lists_only_their_leads(postgres_harness: Any, tmp_path: Path) -> None:
    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path)
        try:
            await _organisation(setup)  # the signed-in person is an admin
            seller = await seed(setup.engine, tenant_id=setup.state.tenant_id, role="member")
            seller_token = await _session(setup, seller)
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=setup.app), base_url=ORIGIN
            ) as client:

                def as_(token: str) -> None:
                    client.cookies.clear()
                    client.cookies.set(setup.settings.session_cookie_name, token)

                async def add(name: str) -> None:
                    added = await client.post(
                        f"{BASE}/leads",
                        json={"command_id": str(uuid4()), "name": name, "assign": "me"},
                        headers=WRITE,
                    )
                    assert added.status_code == 201, added.text

                as_(setup.token)
                await add("Admin Fictional Lead")
                as_(seller_token)
                await add("Seller Fictional Lead One")
                await add("Seller Fictional Lead Two")

                as_(setup.token)
                page = await client.get(
                    f"{BASE}/leads", params={"scope": "team", "owner": str(seller.person_id)}
                )
                assert page.status_code == 200, page.text
                names = sorted(row["name"] for row in page.json()["leads"])
                assert names == ["Seller Fictional Lead One", "Seller Fictional Lead Two"]
                assert page.json()["total"] == 2
                everyone = await client.get(f"{BASE}/leads", params={"scope": "team"})
                assert everyone.json()["total"] == 3
                mine_with_owner = await client.get(
                    f"{BASE}/leads", params={"scope": "mine", "owner": str(seller.person_id)}
                )
                assert mine_with_owner.status_code == 422

                as_(seller_token)
                refused = await client.get(
                    f"{BASE}/leads", params={"scope": "team", "owner": str(setup.state.person_id)}
                )
                assert refused.status_code == 403
        finally:
            await setup.engine.dispose()

    run(exercise())
