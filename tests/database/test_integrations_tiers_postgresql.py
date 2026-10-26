"""Plans decide what apps may do (docs/product/developer-platform-tiers.md, slice 1).

An organisation's admin made a key and connected an app while billing was off: both keep
working as before. The owner's table (economics settings) then puts the workspace on a
tier: on the trial, new keys are refused and Connect grants only reading, saying what the
Organisation plan adds, while the key made before keeps working; with writes advertised,
MCP lists a write tool with its securitySchemes and asks for its scope; a plan below what
a key holds (a downgrade) stops it; and each tier has its own rate limit. Disposable
loopback PostgreSQL, fictional rows only.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

import httpx
import pytest

from ac_platform.economics import store as economics
from ac_platform.integrations import tiers
from tests.database.test_conversation_postgresql import postgres_harness as _postgres_harness
from tests.database.test_conversation_postgresql import run
from tests.database.test_conversation_submission_http_postgresql import ORIGIN, _setup
from tests.database.test_integrations_platform_apps_postgresql import _connect, _install
from tests.database.test_lead_desk_postgresql import _organisation

WRITE = {"Origin": ORIGIN, "Content-Type": "application/json"}
APP_RETURN = "https://mcp-host.example.test/oauth/callback"


@pytest.fixture
def postgres_harness() -> Any:
    yield from cast(Any, _postgres_harness).__wrapped__()


async def _table(setup: Any, **section: Any) -> None:
    """Save the owner's table with these developer_platform fields, as Admin would."""
    async with setup.sessions() as db, db.begin():
        config, _ = await economics.read(db)
        await economics.save(
            db,
            {**config, "developer_platform": {**config["developer_platform"], **section}},
            person_id=None,
            reason="tiers test",
            now=datetime.now(UTC),
        )
    tiers.forget_platform()


def _call(name: str, arguments: dict[str, Any] | None = None, ident: int = 1) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": ident,
        "method": "tools/call",
        "params": {"name": name, "arguments": arguments or {}},
    }


LIST = {"jsonrpc": "2.0", "id": 9, "method": "tools/list"}


def test_plans_decide_what_apps_may_do(postgres_harness: Any, tmp_path: Path) -> None:
    async def exercise() -> None:
        tiers.forget_platform()
        setup = await _setup(postgres_harness, tmp_path)
        try:
            await _organisation(setup)
            # The setup's tenant is an organisation here, not the Personal one.
            _install(setup, setup.settings.model_copy(update={"public_learner_tenant_id": uuid4()}))
            tenant = str(setup.state.tenant_id)
            transport = httpx.ASGITransport(app=setup.app)
            async with (
                httpx.AsyncClient(transport=transport, base_url=ORIGIN) as person,
                httpx.AsyncClient(transport=transport, base_url=ORIGIN) as server,
            ):
                person.cookies.set(setup.settings.session_cookie_name, setup.token)
                # Billing off: today's access, a key that writes, nothing left out.
                made = await person.post(
                    "/v1/sales-xray/integrations/keys",
                    headers=WRITE,
                    json={"name": "Before", "scopes": ["leads:read", "leads:write"]},
                )
                assert made.status_code == 200, made.text
                before = {"Authorization": f"Bearer {made.json()['key']}"}
                plan = (await person.get("/v1/me/connected-apps/plan")).json()
                assert plan["tier"] == "unbilled"
                assert all(row["included"] for row in plan["includes"])
                app = (
                    await server.post(
                        "/v1/oauth/register",
                        json={"client_name": "Assistant", "redirect_uris": [APP_RETURN]},
                    )
                ).json()

                # The owner puts this workspace on the trial.
                await _table(setup, overrides={tenant: "trial"})
                plan = (await person.get("/v1/me/connected-apps/plan")).json()
                assert plan["tier"] == "trial"
                rows = {row["key"]: row for row in plan["includes"]}
                assert rows["connector_read"]["included"] is True
                assert rows["connector_writes"] == {
                    **rows["connector_writes"],
                    "included": False,
                    "comes_with": "Organisation",
                }
                assert rows["api_keys"]["included"] is False
                refused = await person.post(
                    "/v1/sales-xray/integrations/keys",
                    headers=WRITE,
                    json={"name": "After", "scopes": ["leads:read"]},
                )
                assert refused.status_code == 403
                assert refused.json()["detail"] == "API keys come with the Organisation plan."
                # The key made before keeps working.
                added = await server.post(
                    "/v1/api/leads", headers=before, json={"name": "Asha Fictional"}
                )
                assert added.status_code == 201, added.text
                # Connect grants the reading and says what the Organisation plan adds.
                seen, tokens, _ = await _connect(
                    person, server, app, APP_RETURN, "calls:read leads:read leads:notes"
                )
                assert [row["key"] for row in seen["scopes"]] == ["calls:read", "leads:read"]
                assert seen["not_included"] == [
                    {
                        "key": "leads:notes",
                        "label": "Add notes to leads",
                        "comes_with": "Organisation",
                    }
                ]
                assert tokens["scope"] == "calls:read leads:read"
                bearer = {"Authorization": f"Bearer {tokens['access_token']}"}
                # Writes not advertised (ChatGPT 1.0): the list is the scopes' own, as before.
                listed = (await server.post("/v1/mcp", headers=bearer, json=LIST)).json()
                names = {tool["name"] for tool in listed["result"]["tools"]}
                assert "add_note" not in names
                assert all("securitySchemes" not in tool for tool in listed["result"]["tools"])

                # Writes advertised on the trial: the plan doesn't include them, said plainly.
                await _table(setup, overrides={tenant: "trial"}, advertise_writes=True)
                listed = (await server.post("/v1/mcp", headers=bearer, json=LIST)).json()
                assert "add_note" not in {tool["name"] for tool in listed["result"]["tools"]}
                note = {"lead_id": added.json()["id"], "note": "Hi", "request_id": "req-tier-01"}
                past = (
                    await server.post("/v1/mcp", headers=bearer, json=_call("add_note", note))
                ).json()
                assert past["result"]["isError"] is True and "_meta" not in past["result"]
                assert past["result"]["content"][0]["text"] == (
                    "This plan doesn't include “Add notes to leads”. "
                    "It comes with the Organisation plan."
                )

                # On Organisation, MCP lists add_note with its scheme and asks for its scope.
                await _table(setup, overrides={tenant: "organisation"}, advertise_writes=True)
                tools = (await server.post("/v1/mcp", headers=bearer, json=LIST)).json()
                by_name = {tool["name"]: tool for tool in tools["result"]["tools"]}
                assert by_name["add_note"]["securitySchemes"] == [
                    {"type": "oauth2", "scopes": ["leads:notes"]}
                ]
                assert by_name["list_leads"]["securitySchemes"] == [
                    {"type": "oauth2", "scopes": ["leads:read"]}
                ]
                asked = (
                    await server.post("/v1/mcp", headers=bearer, json=_call("add_note", note))
                ).json()
                assert asked["result"]["isError"] is True
                challenge = asked["result"]["_meta"]["mcp/www_authenticate"][0]
                assert challenge.startswith(
                    'Bearer error="insufficient_scope", scope="leads:notes"'
                )
                assert "/.well-known/oauth-protected-resource/v1/mcp" in challenge
                # Reading still answers.
                read = (
                    await server.post("/v1/mcp", headers=bearer, json=_call("list_leads"))
                ).json()
                assert read["result"]["isError"] is False, read

                # A plan below what a key holds (Personal has no leads) stops it; it is kept.
                await _table(setup, overrides={tenant: "personal"}, advertise_writes=False)
                stopped = await server.get("/v1/api/leads", headers=before)
                assert stopped.status_code == 403
                assert stopped.json()["error"] == {
                    "code": "plan_scope",
                    "message": "This plan doesn't include “Read leads”. "
                    "It comes with the Organisation plan.",
                }
                await _table(setup, overrides={tenant: "organisation"})
                assert (await server.get("/v1/api/leads", headers=before)).status_code == 200

                # Each tier has its own rate limit, from the table.
                await _table(
                    setup,
                    overrides={tenant: "enterprise"},
                    tiers={"enterprise": {"per_minute": 2, "workspace_per_minute": 2}},
                )
                answers = [
                    (await server.get("/v1/api/me", headers=before)).status_code for _ in range(3)
                ]
                assert answers == [200, 200, 429]
        finally:
            tiers.forget_platform()
            await setup.engine.dispose()

    run(exercise())
