"""Platform apps on PostgreSQL: self-registration (RFC 7591), a person's own
connection, the remote MCP server, and a Personal workspace. Fictional rows only.

A first-party app (Pulse on its own test host) registers itself, a plain member
approves it for their own account, and its token then reads as that member: their
own calls and leads, never the team's. The MCP server answers the same reads and
sends hosts to Connect when no token is given. A code used twice ends only that
person's connection. The person can list and remove their own connections. A token
from a Personal workspace reads calls but has no leads.
"""

from __future__ import annotations

import base64
import hashlib
import secrets
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import update

from ac_platform.http.routes import RouteContext
from ac_platform.integrations.api_http import install_integrations_api
from ac_platform.integrations.http import install_integrations_http
from ac_platform.integrations.mcp_http import install_mcp_http
from ac_platform.integrations.oauth_http import install_oauth_http
from ac_platform.tenancy.models import Membership
from tests.database.test_conversation_postgresql import postgres_harness as _postgres_harness
from tests.database.test_conversation_postgresql import run
from tests.database.test_conversation_submission_http_postgresql import ORIGIN, _setup
from tests.database.test_lead_desk_postgresql import _organisation

WRITE = {"Origin": ORIGIN, "Content-Type": "application/json"}
PULSE_RETURN = "https://pulse.example.test/api/v0/sales-xray/callback"
HOST_RETURN = "https://mcp-host.example.test/oauth/callback"


@pytest.fixture
def postgres_harness() -> Any:
    yield from cast(Any, _postgres_harness).__wrapped__()


def _pkce() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
    return verifier, challenge.decode().rstrip("=")


def _install(setup: Any, settings: Any) -> None:
    context = RouteContext(settings, setup.require_actor, setup.sessions)
    install_integrations_http(setup.app, context)
    install_integrations_api(setup.app, context)
    install_oauth_http(setup.app, context)
    install_mcp_http(setup.app, context)


async def _connect(
    person: httpx.AsyncClient,
    server: httpx.AsyncClient,
    client: dict[str, Any],
    redirect: str,
    scope: str | None,
) -> tuple[dict[str, Any], dict[str, Any], str]:
    verifier, challenge = _pkce()
    ask = {
        "client_id": client["client_id"],
        "redirect_uri": redirect,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "response_type": "code",
        "state": "st",
    }
    if scope is not None:
        ask["scope"] = scope
    seen = await person.post("/v1/oauth/authorize/check", headers=WRITE, json=ask)
    assert seen.status_code == 200, seen.text
    approved = await person.post(
        "/v1/oauth/authorize/decision", headers=WRITE, json={**ask, "approve": True}
    )
    assert approved.status_code == 200, approved.text
    code = parse_qs(urlsplit(approved.json()["redirect"]).query)["code"][0]
    exchange = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect,
        "client_id": client["client_id"],
        "code_verifier": verifier,
    }
    if client.get("client_secret"):
        exchange["client_secret"] = client["client_secret"]
    tokens = await server.post("/v1/oauth/token", data=exchange)
    assert tokens.status_code == 200, tokens.text
    return seen.json(), tokens.json(), code


def test_a_member_connects_a_platform_app_for_their_own_account(
    postgres_harness: Any, tmp_path: Path
) -> None:
    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path)
        try:
            await _organisation(setup)
            async with setup.sessions() as db, db.begin():
                await db.execute(
                    update(Membership)
                    .where(Membership.person_id == setup.state.person_id)
                    .values(role="member")
                )
            # The setup's tenant is an organisation here, not the Personal one.
            _install(setup, setup.settings.model_copy(update={"public_learner_tenant_id": uuid4()}))
            transport = httpx.ASGITransport(app=setup.app)
            async with (
                httpx.AsyncClient(transport=transport, base_url=ORIGIN) as person,
                httpx.AsyncClient(transport=transport, base_url=ORIGIN) as server,
            ):
                person.cookies.set(setup.settings.session_cookie_name, setup.token)

                # Discovery and self-registration.
                meta = await server.get("/v1/oauth/metadata")
                assert meta.status_code == 200
                assert meta.json()["registration_endpoint"].endswith("/v1/oauth/register")
                assert meta.json()["code_challenge_methods_supported"] == ["S256"]
                # The same discovery documents, served by the API (the dev edge sends them here).
                for path in (
                    "/.well-known/oauth-authorization-server",
                    "/.well-known/openid-configuration",
                ):
                    found = await server.get(path)
                    assert found.status_code == 200 and found.json() == meta.json(), path
                prm = await server.get("/.well-known/oauth-protected-resource/v1/mcp")
                assert prm.json()["resource"].endswith("/v1/mcp")
                assert "webhooks:manage" not in prm.json()["scopes_supported"]
                assert (
                    await server.get("/.well-known/oauth-protected-resource")
                ).status_code == 200
                assert (
                    await server.get("/.well-known/oauth-protected-resource/v1/admin")
                ).status_code == 404
                for wrong in (
                    {"client_name": "Sales X-Ray Official", "redirect_uris": [HOST_RETURN]},
                    {"client_name": "Host", "redirect_uris": ["http://mcp-host.example.test/cb"]},
                    {
                        "client_name": "Host",
                        "redirect_uris": [HOST_RETURN],
                        "response_types": ["token"],
                    },
                    {"redirect_uris": [HOST_RETURN]},
                ):
                    refused = await server.post("/v1/oauth/register", json=wrong)
                    assert refused.status_code == 400, wrong
                    assert refused.json()["error"] in {
                        "invalid_client_metadata",
                        "invalid_redirect_uri",
                    }
                made = await server.post(
                    "/v1/oauth/register",
                    json={
                        "client_name": "Pulse",
                        "redirect_uris": [PULSE_RETURN],
                        "grant_types": ["authorization_code", "refresh_token"],
                        "token_endpoint_auth_method": "client_secret_basic",
                        "client_uri": "https://pulse.example.test",
                    },
                )
                assert made.status_code == 201, made.text
                pulse = made.json()
                assert pulse["client_id"].startswith("sxc_")
                assert pulse["client_secret"].startswith("sxcs_")
                host = (
                    await server.post(
                        "/v1/oauth/register",
                        json={
                            "client_name": "Fictional MCP Host",
                            "redirect_uris": [HOST_RETURN],
                            "token_endpoint_auth_method": "none",
                        },
                    )
                ).json()
                assert "client_secret" not in host

                # A member approves Pulse for their own account.
                seen, tokens, code = await _connect(
                    person, server, pulse, PULSE_RETURN, "calls:read reports:read leads:read"
                )
                assert seen["reach"] == "person"
                assert seen["app"] == {
                    "name": "Pulse",
                    "client_id": pulse["client_id"],
                    "verified": True,
                    "maker": "Estate Autopilots",
                    "self_registered": False,
                }
                assert seen["workspace"]["kind"] == "organisation"
                assert seen["workspace"]["role"] == "member"
                bearer = {"Authorization": f"Bearer {tokens['access_token']}"}
                me = (await server.get("/v1/api/me", headers=bearer)).json()
                assert me["reach"] == "person"
                assert me["person"]["id"] == str(setup.state.person_id)
                assert me["workspace"]["role"] == "member"
                calls = await server.get("/v1/api/calls", headers=bearer)
                assert calls.status_code == 200 and calls.json()["next_before"] is None
                leads = await server.get("/v1/api/leads", headers=bearer)
                assert leads.status_code == 200, leads.text  # their own desk, not the team's
                missing = await server.get(
                    "/v1/api/calls/00000000-0000-0000-0000-000000000001/facts", headers=bearer
                )
                assert missing.status_code == 404  # never another person's call
                write = await server.post("/v1/api/leads", headers=bearer, json={"name": "A"})
                assert write.status_code == 403

                # The remote MCP server.
                bare = await server.post(
                    "/v1/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "ping"}
                )
                assert bare.status_code == 401
                challenge = bare.headers["www-authenticate"]
                assert 'resource_metadata="' in challenge
                assert "/.well-known/oauth-protected-resource/v1/mcp" in challenge
                assert 'scope="calls:read reports:read leads:read"' in challenge
                assert (await server.get("/v1/mcp", headers=bearer)).status_code == 405
                # AI hosts call from their own web origin; the bearer token is what counts.
                elsewhere = await server.post(
                    "/v1/mcp",
                    headers={**bearer, "Origin": "https://chatgpt.com"},
                    json={"jsonrpc": "2.0", "id": 1, "method": "ping"},
                )
                assert elsewhere.status_code == 200, elsewhere.text
                hello = await server.post(
                    "/v1/mcp",
                    headers=bearer,
                    json={
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "initialize",
                        "params": {"protocolVersion": "2025-06-18", "capabilities": {}},
                    },
                )
                assert hello.status_code == 200, hello.text
                assert hello.json()["result"]["protocolVersion"] == "2025-06-18"
                assert hello.json()["result"]["serverInfo"]["name"] == "sales-xray"
                note = await server.post(
                    "/v1/mcp",
                    headers=bearer,
                    json={"jsonrpc": "2.0", "method": "notifications/initialized"},
                )
                assert note.status_code == 202
                tools = await server.post(
                    "/v1/mcp",
                    headers=bearer,
                    json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
                )
                names = [tool["name"] for tool in tools.json()["result"]["tools"]]
                assert "list_calls" in names and "list_leads" in names
                assert "add_lead" not in names  # leads:write was not approved
                assert "search" in names and "fetch" in names  # what ChatGPT asks for
                who = await server.post(
                    "/v1/mcp",
                    headers=bearer,
                    json={
                        "jsonrpc": "2.0",
                        "id": 3,
                        "method": "tools/call",
                        "params": {"name": "whoami", "arguments": {}},
                    },
                )
                result = who.json()["result"]
                assert result["isError"] is False
                assert result["structuredContent"]["person"]["id"] == str(setup.state.person_id)
                listed = await server.post(
                    "/v1/mcp",
                    headers=bearer,
                    json={
                        "jsonrpc": "2.0",
                        "id": 4,
                        "method": "tools/call",
                        "params": {"name": "list_calls", "arguments": {}},
                    },
                )
                assert listed.json()["result"]["structuredContent"]["calls"] == []
                found = await server.post(
                    "/v1/mcp",
                    headers=bearer,
                    json={
                        "jsonrpc": "2.0",
                        "id": 7,
                        "method": "tools/call",
                        "params": {"name": "search", "arguments": {"query": "Fictional"}},
                    },
                )
                assert found.json()["result"]["isError"] is False, found.text
                assert found.json()["result"]["structuredContent"] == {"results": []}
                bad = await server.post(
                    "/v1/mcp",
                    headers=bearer,
                    json={
                        "jsonrpc": "2.0",
                        "id": 5,
                        "method": "tools/call",
                        "params": {"name": "get_call", "arguments": {"call_id": "nope"}},
                    },
                )
                assert bad.json()["result"]["isError"] is True
                unknown = await server.post(
                    "/v1/mcp",
                    headers=bearer,
                    json={
                        "jsonrpc": "2.0",
                        "id": 6,
                        "method": "tools/call",
                        "params": {"name": "drop_tables", "arguments": {}},
                    },
                )
                assert unknown.json()["error"]["code"] == -32602

                # An unchecked app shows as such; a host that asks for no scope reads only.
                seen_host, host_tokens, _ = await _connect(person, server, host, HOST_RETURN, None)
                assert seen_host["app"]["verified"] is False
                assert seen_host["app"]["self_registered"] is True
                assert host_tokens["scope"] == "calls:read leads:read reports:read"

                # The same code again ends only this person's Pulse connection.
                again = await server.post(
                    "/v1/oauth/token",
                    data={
                        "grant_type": "authorization_code",
                        "code": code,
                        "redirect_uri": PULSE_RETURN,
                        "client_id": pulse["client_id"],
                        "client_secret": pulse["client_secret"],
                        "code_verifier": "x" * 50,
                    },
                )
                assert again.status_code == 400
                assert (await server.get("/v1/api/me", headers=bearer)).status_code == 401
                host_bearer = {"Authorization": f"Bearer {host_tokens['access_token']}"}
                assert (await server.get("/v1/api/me", headers=host_bearer)).status_code == 200

                # The person sees and removes their own connections.
                mine = (await person.get("/v1/me/connected-apps")).json()["apps"]
                live = [app for app in mine if app["revoked_at"] is None]
                assert [app["app"] for app in live] == ["Fictional MCP Host"]
                # Settings → AI apps shows the consent screen's checked mark, or its absence.
                assert live[0]["verified"] is False and live[0]["maker"] is None
                removed = await person.post(
                    f"/v1/me/connected-apps/{live[0]['id']}/revoke", headers=WRITE
                )
                assert removed.status_code == 200, removed.text
                assert (await server.get("/v1/api/me", headers=host_bearer)).status_code == 401
                stranger = await person.post(
                    "/v1/me/connected-apps/00000000-0000-0000-0000-000000000002/revoke",
                    headers=WRITE,
                )
                assert stranger.status_code == 404

                # Leaving the organisation stops a live connection at once.
                _, fresh, _ = await _connect(person, server, pulse, PULSE_RETURN, "calls:read")
                fresh_bearer = {"Authorization": f"Bearer {fresh['access_token']}"}
                pulse_now = [
                    app
                    for app in (await person.get("/v1/me/connected-apps")).json()["apps"]
                    if app["revoked_at"] is None and app["app"] == "Pulse"
                ]
                assert [(app["verified"], app["maker"]) for app in pulse_now] == [
                    (True, "Estate Autopilots")
                ]
                assert (await server.get("/v1/api/me", headers=fresh_bearer)).status_code == 200
                async with setup.sessions() as db, db.begin():
                    await db.execute(
                        update(Membership)
                        .where(Membership.person_id == setup.state.person_id)
                        .values(status="inactive", ended_at=datetime.now(UTC))
                    )
                ended = await server.get("/v1/api/calls", headers=fresh_bearer)
                assert ended.status_code == 403 and ended.json()["error"]["code"] == "access_ended"
        finally:
            await setup.engine.dispose()

    run(exercise())


def test_a_personal_workspace_connection_reads_calls_but_has_no_leads(
    postgres_harness: Any, tmp_path: Path
) -> None:
    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path)
        try:
            # The setup's own tenant is the Personal workspace.
            _install(setup, setup.settings)
            transport = httpx.ASGITransport(app=setup.app)
            async with (
                httpx.AsyncClient(transport=transport, base_url=ORIGIN) as person,
                httpx.AsyncClient(transport=transport, base_url=ORIGIN) as server,
            ):
                person.cookies.set(setup.settings.session_cookie_name, setup.token)
                pulse = (
                    await server.post(
                        "/v1/oauth/register",
                        json={"client_name": "Pulse", "redirect_uris": [PULSE_RETURN]},
                    )
                ).json()
                seen, tokens, _ = await _connect(
                    person, server, pulse, PULSE_RETURN, "calls:read leads:read"
                )
                assert seen["workspace"] == {
                    "id": str(setup.state.tenant_id),
                    "kind": "personal",
                    "name": "Personal",
                    "role": None,
                }
                bearer = {"Authorization": f"Bearer {tokens['access_token']}"}
                me = (await server.get("/v1/api/me", headers=bearer)).json()
                assert me["workspace"]["kind"] == "personal" and me["organisation"] is None
                assert (await server.get("/v1/api/calls", headers=bearer)).status_code == 200
                leads = await server.get("/v1/api/leads", headers=bearer)
                assert leads.status_code == 403
                assert leads.json()["error"]["code"] == "organisation_only"
                # ChatGPT's search still answers: calls only, no leads and no refusal.
                found = await server.post(
                    "/v1/mcp",
                    headers=bearer,
                    json={
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "tools/call",
                        "params": {"name": "search", "arguments": {"query": "Fictional"}},
                    },
                )
                assert found.json()["result"]["isError"] is False, found.text
                assert found.json()["result"]["structuredContent"] == {"results": []}
        finally:
            await setup.engine.dispose()

    run(exercise())
