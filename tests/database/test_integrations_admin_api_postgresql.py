"""The admin primitives for an organisation's key on PostgreSQL (owner, 17 Nov 2026: "every
base-level primitive in CLI, MCP and API"; integrations/admin_api.py).

An owner's or admin's organisation key reads the workspace and its invites (team:read),
invites, sends again, cancels, changes roles and removes people (team:manage), archives, bins
and restores leads (leads:archive) and gives one person's leads to another (leads:assign),
each through the app's own service; the same request_id again changes nothing; over 5 leads
it previews first; MCP has the same tools; a key without the scope is refused. Fictional
rows only."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import select, update

from ac_platform.lead_desk.models import Lead
from ac_platform.tenancy.models import Membership, OrganisationInvite
from ac_platform.tenancy.seat_grant_models import OrganisationSeatGrant
from tests.database.test_conversation_postgresql import postgres_harness as _postgres_harness
from tests.database.test_conversation_postgresql import run, seed
from tests.database.test_conversation_submission_http_postgresql import ORIGIN, _setup
from tests.database.test_integrations_platform_apps_postgresql import _install
from tests.database.test_lead_desk_postgresql import _admin_sells, _organisation

WRITE = {"Origin": ORIGIN, "Content-Type": "application/json"}
SCOPES = ["team:read", "team:manage", "leads:read", "leads:write", "leads:archive", "leads:assign"]


@pytest.fixture
def postgres_harness() -> Any:
    yield from cast(Any, _postgres_harness).__wrapped__()


def test_an_admins_key_runs_the_admin_primitives(postgres_harness: Any, tmp_path: Path) -> None:
    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path)
        try:
            await _organisation(setup)
            await _admin_sells(setup)
            mate = await seed(setup.engine, tenant_id=setup.state.tenant_id, role="member")
            # The key's person is the owner: roles change only by the owner (the app's rule).
            async with setup.sessions() as db, db.begin():
                await db.execute(
                    update(Membership)
                    .where(
                        Membership.tenant_id == setup.state.tenant_id,
                        Membership.person_id == setup.state.person_id,
                    )
                    .values(role="owner")
                )
            # The harness's tenant doubles as the public learner tenant, which no organisation
            # service manages; this workspace is an organisation here (as in the Lead OS world).
            settings = setup.settings.model_copy(update={"public_learner_tenant_id": uuid4()})
            _install(setup, settings)
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
                        json={"name": "Fictional admin", "scopes": scopes},
                    )
                    assert made.status_code == 200, made.text
                    return {"Authorization": f"Bearer {made.json()['key']}"}

                admin = await key(SCOPES)

                async def post(path: str, body: dict[str, Any], status: int = 200) -> Any:
                    answer = await app.post(f"/v1/api{path}", headers=admin, json=body)
                    assert answer.status_code == status, answer.text
                    return answer.json()

                # The workspace.
                seen = await app.get("/v1/api/workspace", headers=admin)
                assert seen.status_code == 200, seen.text
                body = seen.json()
                assert body["members_by_role"]["owner"] == 1
                assert body["ai_apps_switch"]["paused"] is False
                assert "@" not in json.dumps(body)

                # Leads: seven, all the admin's (the admin takes new leads).
                for number in range(7):
                    await post(
                        "/leads",
                        {"name": f"Fictional Shelf {number}", "phone": f"98760 5510{number}"},
                        status=201,
                    )
                async with setup.sessions() as db:
                    leads = list(
                        await db.scalars(
                            select(Lead.id).where(Lead.tenant_id == setup.state.tenant_id)
                        )
                    )
                assert len(leads) == 7
                two = [str(lead) for lead in leads[:2]]
                archived = await post(
                    "/leads/shelf",
                    {"action": "archive", "lead_ids": two, "request_id": "arch-0001"},
                )
                assert archived["changed"] == 2
                again = await post(
                    "/leads/shelf",
                    {"action": "archive", "lead_ids": two, "request_id": "arch-0001"},
                )
                assert again["job_id"] == archived["job_id"]
                async with setup.sessions() as db:
                    gone = await db.scalars(select(Lead.archived_at).where(Lead.id.in_(leads[:2])))
                    assert all(at is not None for at in gone)
                restored = await post(
                    "/leads/shelf",
                    {"action": "restore_archive", "lead_ids": two, "request_id": "arch-0002"},
                )
                assert restored["changed"] == 2

                # Over 5 leads: preview first, then apply with its sha.
                everyone = {"action": "bin", "filter": {"scope": "team"}, "request_id": "bin-00001"}
                refused = await post("/leads/shelf", everyone, status=409)
                assert refused["error"]["code"] == "preview_first"
                preview = await post("/leads/shelf", {**everyone, "preview": True})
                assert preview["changed"] == 7 and preview["preview"] is True
                async with setup.sessions() as db:
                    assert all(
                        at is None
                        for at in await db.scalars(select(Lead.binned_at).where(Lead.id.in_(leads)))
                    )
                binned = await post(
                    "/leads/shelf", {**everyone, "preview_sha": preview["preview_sha"]}
                )
                assert binned["changed"] == 7
                back = {
                    "action": "restore_bin",
                    "filter": {"scope": "team", "shelf": "bin"},
                    "request_id": "bin-00002",
                }
                sha = (await post("/leads/shelf", {**back, "preview": True}))["preview_sha"]
                assert (await post("/leads/shelf", {**back, "preview_sha": sha}))["changed"] == 7

                # One person's leads to another (the lead rules shared the seven out).
                async with setup.sessions() as db:
                    held = len(
                        list(
                            await db.scalars(
                                select(Lead.id).where(
                                    Lead.id.in_(leads),
                                    Lead.owner_person_id == setup.state.person_id,
                                )
                            )
                        )
                    )
                assert held >= 1
                move = {
                    "from_person_id": str(setup.state.person_id),
                    "to_person_id": str(mate.person_id),
                    "request_id": "move-0001",
                }
                sha = (await post("/leads/reassign", {**move, "preview": True}))["preview_sha"]
                moved = await post("/leads/reassign", {**move, "preview_sha": sha})
                assert moved["changed"] == held
                async with setup.sessions() as db:
                    owners = set(
                        await db.scalars(select(Lead.owner_person_id).where(Lead.id.in_(leads)))
                    )
                assert owners == {mate.person_id}

                # People.
                role = await post(
                    f"/team/{mate.person_id}/role", {"role": "manager", "request_id": "role-0001"}
                )
                assert role["role"] == "manager"
                await post(
                    f"/team/{mate.person_id}/role", {"role": "manager", "request_id": "role-0001"}
                )
                await post(f"/team/{mate.person_id}/remove", {"request_id": "remove-0001"})
                async with setup.sessions() as db:
                    member = await db.get(Membership, (setup.state.tenant_id, mate.person_id))
                    assert member is not None and member.status != "active"

                # Invites: a full workspace refuses (the app's seats), then it has seats.
                full = await post(
                    "/team/invites",
                    {"email": "fictional.full@example.com", "request_id": "inv-full-01"},
                    status=409,
                )
                assert full["error"]["code"] == "seats_full"
                async with setup.sessions() as db, db.begin():
                    now = datetime.now(UTC)
                    db.add(
                        OrganisationSeatGrant(
                            tenant_id=setup.state.tenant_id,
                            seats=5,
                            valid_from=now - timedelta(minutes=1),
                            valid_until=now + timedelta(days=1),
                            reason="Fictional seats for the admin API test",
                            granted_by_person_id=setup.state.person_id,
                            created_at=now,
                        )
                    )
                invited = await post(
                    "/team/invites",
                    {
                        "email": "Fictional.New@example.com",
                        "role": "member",
                        "request_id": "inv-0001",
                    },
                )
                assert invited["email"] == "f***@example.com" and invited["invite_id"]
                assert (
                    await post(
                        "/team/invites",
                        {
                            "email": "Fictional.New@example.com",
                            "role": "member",
                            "request_id": "inv-0001",
                        },
                    )
                )["invite_id"] == invited["invite_id"]
                listed = await app.get("/v1/api/team/invites", headers=admin)
                assert [row["invite_id"] for row in listed.json()["invites"]] == [
                    invited["invite_id"]
                ]
                resent = await post(
                    f"/team/invites/{invited['invite_id']}/resend", {"request_id": "inv-0002"}
                )
                assert resent["revoked"] == invited["invite_id"]
                assert resent["invite_id"] != invited["invite_id"]
                again_resent = await post(
                    f"/team/invites/{invited['invite_id']}/resend", {"request_id": "inv-0002"}
                )
                assert again_resent["invite_id"] == resent["invite_id"]
                await post(
                    f"/team/invites/{resent['invite_id']}/revoke", {"request_id": "inv-0003"}
                )
                async with setup.sessions() as db:
                    states = set(
                        await db.scalars(
                            select(OrganisationInvite.status).where(
                                OrganisationInvite.tenant_id == setup.state.tenant_id
                            )
                        )
                    )
                assert "pending" not in states

                # MCP: the same tools.
                tool = await app.post(
                    "/v1/mcp",
                    headers=admin,
                    json={
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "tools/call",
                        "params": {"name": "get_workspace", "arguments": {}},
                    },
                )
                answer = tool.json()["result"]
                assert answer["isError"] is False, answer
                assert answer["structuredContent"]["workspace"]["id"] == str(setup.state.tenant_id)
                listing = await app.post(
                    "/v1/mcp",
                    headers=admin,
                    json={"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
                )
                names = {row["name"] for row in listing.json()["result"]["tools"]}
                assert {"shelve_leads", "reassign_leads", "invite_member"} <= names

                # A key without the scope is refused.
                reader = await key(["team:read"])
                blocked = await app.post(
                    "/v1/api/team/invites",
                    headers=reader,
                    json={"email": "x@example.com", "request_id": "inv-0009"},
                )
                assert blocked.status_code == 403
                assert blocked.json()["error"]["code"] == "scope_missing"
                shelf = await app.post(
                    "/v1/api/leads/shelf",
                    headers=reader,
                    json={"action": "archive", "lead_ids": two, "request_id": str(uuid4())},
                )
                assert shelf.status_code == 403
        finally:
            await setup.engine.dispose()

    run(exercise())
