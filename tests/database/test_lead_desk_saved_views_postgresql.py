"""Saved views on Leads, on the server (owner, 16 Nov 2026, M4-B), through the HTTP API on
PostgreSQL: my own views and the team's, who may make and change which, counts as the list
counts for the person asking, revisions, names and the limits."""

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


def test_saved_views_mine_and_the_teams(postgres_harness: Any, tmp_path: Path) -> None:
    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path)
        try:
            await _organisation(setup)
            tenant = setup.state.tenant_id
            seller = await seed(setup.engine, tenant_id=tenant, role="member")
            seller_token = await _session(setup, seller)
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=setup.app), base_url=ORIGIN
            ) as client:

                def as_(token: str) -> None:
                    client.cookies.set(setup.settings.session_cookie_name, token)

                async def post(path: str, body: dict[str, Any]) -> httpx.Response:
                    return await client.post(f"{BASE}{path}", json=body, headers=WRITE)

                as_(setup.token)
                for index in range(3):
                    added = await post(
                        "/leads",
                        {"command_id": str(uuid4()), "name": f"View Fictional {index}"},
                    )
                    assert added.status_code == 201, added.text

                # The team's view, made by the owner; saving twice makes one.
                command = str(uuid4())
                team_body = {
                    "command_id": command,
                    "name": "Everyone inbound",
                    "visibility": "team",
                    "filter": {"scope": "team", "side": "inbound"},
                    "display": {"columns": ["name", "stage", "owner"], "density": 52},
                }
                made = await post("/views", team_body)
                assert made.status_code == 201, made.text
                team_view = made.json()
                assert team_view["visibility"] == "team" and team_view["revision"] == 1
                assert (await post("/views", team_body)).json()["view_id"] == team_view["view_id"]
                taken = await post("/views", {**team_body, "command_id": str(uuid4())})
                assert taken.status_code == 409
                mine = await post(
                    "/views",
                    {
                        "command_id": str(uuid4()),
                        "name": "My new ones",
                        "filter": {"scope": "mine", "side": "inbound", "stage": "new"},
                    },
                )
                assert mine.status_code == 201, mine.text
                listed = (await client.get(f"{BASE}/views?counts=true")).json()["views"]
                assert [view["name"] for view in listed] == ["Everyone inbound", "My new ones"]
                assert listed[0]["count"] == 3
                assert all(view["can_change"] for view in listed)

                # A seller sees the team's view, not the owner's own; can't make or change a
                # team view, and the team list counts nothing their role can't open.
                as_(seller_token)
                seen = (await client.get(f"{BASE}/views?counts=true")).json()["views"]
                assert [view["name"] for view in seen] == ["Everyone inbound"]
                assert seen[0]["count"] is None and seen[0]["can_change"] is False
                refused = await post("/views", {**team_body, "command_id": str(uuid4())})
                assert refused.status_code == 403
                edit = await client.put(
                    f"{BASE}/views/{team_view['view_id']}",
                    json={"expected_revision": 1, "name": "Mine now"},
                    headers=WRITE,
                )
                assert edit.status_code == 403
                hidden = await client.put(
                    f"{BASE}/views/{mine.json()['view_id']}",
                    json={"expected_revision": 1, "name": "Mine now"},
                    headers=WRITE,
                )
                assert hidden.status_code == 404
                own = await post(
                    "/views",
                    {
                        "command_id": str(uuid4()),
                        "name": "Everyone inbound",
                        "filter": {"scope": "mine"},
                    },
                )
                assert own.status_code == 201, own.text
                assert own.json()["mine"] is True

                # Changes go by revision.
                as_(setup.token)
                renamed = await client.put(
                    f"{BASE}/views/{team_view['view_id']}",
                    json={"expected_revision": 1, "name": "All inbound", "position": 5},
                    headers=WRITE,
                )
                assert renamed.status_code == 200, renamed.text
                assert renamed.json()["revision"] == 2 and renamed.json()["name"] == "All inbound"
                stale = await client.put(
                    f"{BASE}/views/{team_view['view_id']}",
                    json={"expected_revision": 1, "name": "Again"},
                    headers=WRITE,
                )
                assert stale.status_code == 409
                big = await client.put(
                    f"{BASE}/views/{team_view['view_id']}",
                    json={"expected_revision": 2, "display": {"x": "y" * 5000}},
                    headers=WRITE,
                )
                assert big.status_code == 422
                gone = await post(
                    f"/views/{mine.json()['view_id']}/delete", {"expected_revision": 1}
                )
                assert gone.status_code == 200, gone.text
                assert [view["name"] for view in gone.json()["views"]] == ["All inbound"]
                assert (await client.get(f"{BASE}/views?x=1")).status_code == 422
        finally:
            await setup.engine.dispose()

    run(exercise())
