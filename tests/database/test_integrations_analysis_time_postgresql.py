"""Analysis time for apps on PostgreSQL (API gap 9, 15 Nov 2026).

An organisation's key reads the workspace's analysis time (``GET /v1/api/analysis-time``)
and each member's share (``/team``), as the app's own pages read them: the organisation's
one pool, time only, names and never emails, and nothing reserved by reading. MCP's
``analysis_time`` answers the same. A key without ``calls:read`` is refused. Fictional
rows only.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import func, select

from ac_platform.conversation_intelligence.acquisition_models import ConversationAcquisitionUsage
from tests.database.test_conversation_postgresql import postgres_harness as _postgres_harness
from tests.database.test_conversation_postgresql import run
from tests.database.test_conversation_submission_http_postgresql import ORIGIN, _setup
from tests.database.test_integrations_platform_apps_postgresql import _install
from tests.database.test_lead_desk_postgresql import _organisation

WRITE = {"Origin": ORIGIN, "Content-Type": "application/json"}
SECONDS = ("given_seconds", "used_seconds", "left_seconds", "longest_call_seconds")


@pytest.fixture
def postgres_harness() -> Any:
    yield from cast(Any, _postgres_harness).__wrapped__()


def test_an_organisations_key_reads_its_analysis_time_and_each_members_share(
    postgres_harness: Any, tmp_path: Path
) -> None:
    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path)
        try:
            await _organisation(setup)
            # The setup's tenant is an organisation here, not the Personal one, and not the
            # operations workspace.
            _install(
                setup,
                setup.settings.model_copy(
                    update={"public_learner_tenant_id": uuid4(), "operations_tenant_id": uuid4()}
                ),
            )
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
                        json={"name": "Fictional dashboard", "scopes": scopes},
                    )
                    assert made.status_code == 200, made.text
                    return {"Authorization": f"Bearer {made.json()['key']}"}

                async def uses() -> int:
                    async with setup.sessions() as db:
                        return int(
                            await db.scalar(
                                select(func.count()).select_from(ConversationAcquisitionUsage)
                            )
                            or 0
                        )

                reader = await key(["calls:read"])
                before = await uses()
                left = await app.get("/v1/api/analysis-time", headers=reader)
                assert left.status_code == 200, left.text
                body = left.json()
                assert body["pool"] == "organisation"
                assert all(isinstance(body[name], int) and body[name] >= 0 for name in SECONDS)
                assert body["left_seconds"] <= body["given_seconds"]
                # Time only: nothing that could be a price.
                assert not any("paise" in name or "price" in name for name in body)

                team = await app.get("/v1/api/analysis-time/team", headers=reader)
                assert team.status_code == 200, team.text
                people = team.json()["people"]
                assert people and {"person_id", "name", "role", "used_seconds"} == set(people[0])
                assert "@" not in json.dumps(people)  # names, never emails
                assert await uses() == before  # reading reserves nothing

                tool = await app.post(
                    "/v1/mcp",
                    headers=reader,
                    json={
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "tools/call",
                        "params": {"name": "analysis_time", "arguments": {}},
                    },
                )
                assert tool.status_code == 200, tool.text
                answer = tool.json()["result"]
                assert answer["isError"] is False
                assert answer["structuredContent"]["left_seconds"] == body["left_seconds"]

                writer = await key(["leads:read"])
                refused = await app.get("/v1/api/analysis-time", headers=writer)
                assert refused.status_code == 403
                assert refused.json()["error"]["code"] == "scope_missing"
        finally:
            await setup.engine.dispose()

    run(exercise())
