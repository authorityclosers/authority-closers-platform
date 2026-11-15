"""The team for apps on PostgreSQL (API gap 7, 15 Nov 2026).

An organisation's key with ``team:read`` reads the team as Lead Desk's Team page shows it
(``GET /v1/api/team``, MCP ``list_team``): each person's name and role, whether they take new
leads, their lead limit and open leads, and the leads waiting for an owner; never an email or
a phone. A key without ``team:read`` is refused. Fictional rows only.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

import httpx
import pytest

from tests.database.test_conversation_postgresql import postgres_harness as _postgres_harness
from tests.database.test_conversation_postgresql import run, seed
from tests.database.test_conversation_submission_http_postgresql import ORIGIN, _setup
from tests.database.test_integrations_platform_apps_postgresql import _install
from tests.database.test_lead_desk_postgresql import _admin_sells, _organisation

WRITE = {"Origin": ORIGIN, "Content-Type": "application/json"}


@pytest.fixture
def postgres_harness() -> Any:
    yield from cast(Any, _postgres_harness).__wrapped__()


def test_an_organisations_key_reads_the_team_without_emails(
    postgres_harness: Any, tmp_path: Path
) -> None:
    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path)
        try:
            await _organisation(setup)
            await _admin_sells(setup)
            mate = await seed(setup.engine, tenant_id=setup.state.tenant_id, role="member")
            _install(setup, setup.settings)
            transport = httpx.ASGITransport(app=setup.app)
            async with (
                httpx.AsyncClient(transport=transport, base_url=ORIGIN) as person,
                httpx.AsyncClient(transport=transport, base_url=ORIGIN) as app,
            ):
                person.cookies.set(setup.settings.session_cookie_name, setup.token)

                async def key(scopes: list[str]) -> dict[str, str]:
                    made = await person.post(
                        "/v1/sales-xray/integrations/keys",
                        headers=WRITE,
                        json={"name": "Fictional roster", "scopes": scopes},
                    )
                    assert made.status_code == 200, made.text
                    return {"Authorization": f"Bearer {made.json()['key']}"}

                reader = await key(["team:read"])
                team = await app.get("/v1/api/team", headers=reader)
                assert team.status_code == 200, team.text
                body = team.json()
                people = {row["person_id"]: row for row in body["people"]}
                admin = people[str(setup.state.person_id)]
                assert admin["role"] == "admin" and admin["takes_new_leads"] is True
                assert admin["name"]
                assert str(mate.person_id) in people
                assert isinstance(body["unassigned_leads"], int)
                assert "@" not in json.dumps(body)  # names, never emails
                assert not any("phone" in field for row in body["people"] for field in row)

                tool = await app.post(
                    "/v1/mcp",
                    headers=reader,
                    json={
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "tools/call",
                        "params": {"name": "list_team", "arguments": {}},
                    },
                )
                answer = tool.json()["result"]
                assert answer["isError"] is False
                assert len(answer["structuredContent"]["people"]) == len(body["people"])

                refused = await app.get("/v1/api/team", headers=await key(["leads:read"]))
                assert refused.status_code == 403
                assert refused.json()["error"]["code"] == "scope_missing"
        finally:
            await setup.engine.dispose()

    run(exercise())
