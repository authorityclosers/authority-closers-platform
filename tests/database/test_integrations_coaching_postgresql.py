"""Coaching by API key and connected app (API, MCP and CLI gaps, 15 Nov 2026, gap 11): a person
reads their own Coaching and their own calls' coaching, never a teammate's; the team's Coaching
is for owners, admins and organisation keys; an organisation key has no Coaching of its own."""

import json
from pathlib import Path
from typing import Any, Literal, cast
from uuid import uuid4

import httpx
import pytest

from ac_platform.http.routes import RouteContext
from ac_platform.integrations import coaching_api, keys
from ac_platform.integrations.api_http import ApiError, Caller, Reader, install_integrations_api
from ac_platform.integrations.coaching_api import install_coaching_api
from ac_platform.integrations.http import install_integrations_http
from tests.database.test_coaching_access_postgresql import team
from tests.database.test_coaching_postgresql import postgres_harness as _postgres_harness
from tests.database.test_conversation_postgresql import run
from tests.database.test_conversation_submission_http_postgresql import ORIGIN

WRITE = {"Origin": ORIGIN, "Content-Type": "application/json"}


@pytest.fixture
def postgres_harness() -> Any:
    yield from cast(Any, _postgres_harness).__wrapped__()


def test_coaching_follows_the_app_s_rules_for_people_and_keys(
    postgres_harness: Any, tmp_path: Path
) -> None:
    async def exercise() -> None:
        setup, seller, owners, sellers, _ = await team(postgres_harness, tmp_path)
        tenant = setup.state.tenant_id

        def caller(
            person_id: Any, role: str, reach: Literal["organisation", "person"] = "person"
        ) -> Caller:
            key = keys.KeyContext(
                key_id=uuid4(),
                tenant_id=tenant,
                scopes=frozenset({"reports:read"}),
                prefix="app test",
                acting_person_id=person_id,
            )
            return Caller(key=key, reach=reach, role=role)

        async def read(who: Caller, action: Any, *args: Any) -> Any:
            async with setup.sessions() as db, db.begin():
                return await action(Reader(db, who, None, "test"), *args)

        async def refused(who: Caller, action: Any, *args: Any) -> str:
            with pytest.raises(ApiError) as caught:
                await read(who, action, *args)
            return caught.value.code

        try:
            rep = caller(seller.actor.person_id, "member")
            owner = caller(setup.state.actor.person_id, "owner")
            organisation = caller(setup.state.actor.person_id, "owner", reach="organisation")

            # A person's own Coaching: their calls only, whatever their role.
            mine = json.dumps(await read(rep, coaching_api.my_coaching))
            assert str(sellers) in mine and str(owners) not in mine
            owners_own = json.dumps(await read(owner, coaching_api.my_coaching))
            assert str(owners) in owners_own and str(sellers) not in owners_own

            # One call's coaching: your own call, never a teammate's (no owner bypass).
            assert await read(rep, coaching_api.call_coaching, sellers)
            assert await refused(rep, coaching_api.call_coaching, owners) == "call_missing"
            assert await refused(owner, coaching_api.call_coaching, sellers) == "call_missing"

            # The team's Coaching: owners, admins and organisation keys.
            assert await read(owner, coaching_api.team_coaching)
            assert await read(organisation, coaching_api.team_coaching)
            for role in ("member", "manager", "viewer"):
                who = caller(seller.actor.person_id, role)
                assert await refused(who, coaching_api.team_coaching) == "team_only", role
            # An organisation key is no person: no Coaching of its own.
            assert await refused(organisation, coaching_api.my_coaching) == "person_only"
            assert await refused(organisation, coaching_api.call_coaching, owners) == (
                "person_only"
            )

            # The same through the API with an organisation key.
            context = RouteContext(setup.settings, setup.require_actor, setup.sessions)
            install_integrations_http(setup.app, context)
            install_integrations_api(setup.app, context)
            install_coaching_api(setup.app, context)
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=setup.app), base_url=ORIGIN
            ) as client:
                client.cookies.set(setup.settings.session_cookie_name, setup.token)
                made = await client.post(
                    "/v1/sales-xray/integrations/keys",
                    headers=WRITE,
                    json={"name": "Coaching", "scopes": ["reports:read"]},
                )
                assert made.status_code == 200, made.text
                narrow = await client.post(
                    "/v1/sales-xray/integrations/keys",
                    headers=WRITE,
                    json={"name": "Calls", "scopes": ["calls:read"]},
                )
            bearer = {"Authorization": f"Bearer {made.json()['key']}"}
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=setup.app), base_url=ORIGIN
            ) as app:
                team_view = await app.get("/v1/api/coaching/team", headers=bearer)
                assert team_view.status_code == 200, team_view.text
                assert "session_id" not in team_view.json()
                assert team_view.headers["cache-control"] == "no-store"
                own = await app.get("/v1/api/coaching", headers=bearer)
                assert own.status_code == 403 and own.json()["error"]["code"] == "person_only"
                missing = await app.get(
                    "/v1/api/coaching/team",
                    headers={"Authorization": f"Bearer {narrow.json()['key']}"},
                )
                assert missing.json()["error"]["code"] == "scope_missing"
        finally:
            await setup.engine.dispose()

    run(exercise())
