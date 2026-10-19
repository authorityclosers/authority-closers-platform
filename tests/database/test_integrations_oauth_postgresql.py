"""Connect (OAuth 2.0 + PKCE) on PostgreSQL, end to end with fictional rows.

An organisation admin registers an app, approves it on the consent screen, the app
swaps the one-time code (with its PKCE verifier) for tokens, reads the API with the
access token, refreshes, and a replayed refresh token ends the connection. A denied
request returns access_denied; a wrong return address never redirects; removing the
connection in Settings stops its tokens.
"""

from __future__ import annotations

import base64
import hashlib
import secrets
from pathlib import Path
from typing import Any, cast
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest

from ac_platform.http.routes import RouteContext
from ac_platform.integrations.api_http import install_integrations_api
from ac_platform.integrations.http import install_integrations_http
from ac_platform.integrations.oauth_http import install_oauth_http
from tests.database.test_conversation_postgresql import postgres_harness as _postgres_harness
from tests.database.test_conversation_postgresql import run
from tests.database.test_conversation_submission_http_postgresql import ORIGIN, _setup
from tests.database.test_lead_desk_postgresql import _organisation

WRITE = {"Origin": ORIGIN, "Content-Type": "application/json"}
RETURN = "https://partner.example.test/sales-xray/callback"


@pytest.fixture
def postgres_harness() -> Any:
    yield from cast(Any, _postgres_harness).__wrapped__()


def _pkce() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
    return verifier, challenge.decode().rstrip("=")


def test_an_app_connects_with_consent_and_pkce(postgres_harness: Any, tmp_path: Path) -> None:
    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path)
        try:
            await _organisation(setup)
            context = RouteContext(setup.settings, setup.require_actor, setup.sessions)
            install_integrations_http(setup.app, context)
            install_integrations_api(setup.app, context)
            install_oauth_http(setup.app, context)
            transport = httpx.ASGITransport(app=setup.app)
            async with (
                httpx.AsyncClient(transport=transport, base_url=ORIGIN) as admin,
                httpx.AsyncClient(transport=transport, base_url=ORIGIN) as app_server,
            ):
                admin.cookies.set(setup.settings.session_cookie_name, setup.token)
                bad = await admin.post(
                    "/v1/sales-xray/integrations/apps",
                    headers=WRITE,
                    json={"name": "x", "redirect_uris": ["http://partner.example.test/cb"]},
                )
                assert bad.status_code == 422
                made = await admin.post(
                    "/v1/sales-xray/integrations/apps",
                    headers=WRITE,
                    json={"name": "Partner CRM", "redirect_uris": [RETURN]},
                )
                assert made.status_code == 200, made.text
                client_id, client_secret = made.json()["client_id"], made.json()["client_secret"]
                assert client_id.startswith("sxc_") and client_secret.startswith("sxcs_")

                verifier, challenge = _pkce()
                ask = {
                    "client_id": client_id,
                    "redirect_uri": RETURN,
                    "scope": "leads:read calls:read",
                    "code_challenge": challenge,
                    "code_challenge_method": "S256",
                    "response_type": "code",
                    "state": "s-123",
                }
                seen = await admin.post("/v1/oauth/authorize/check", headers=WRITE, json=ask)
                assert seen.status_code == 200, seen.text
                assert seen.json()["app"]["name"] == "Partner CRM"
                assert [s["key"] for s in seen.json()["scopes"]] == ["calls:read", "leads:read"]
                assert seen.json()["returns_to"] == "partner.example.test"
                wrong = await admin.post(
                    "/v1/oauth/authorize/check",
                    headers=WRITE,
                    json={**ask, "redirect_uri": "https://evil.example/cb"},
                )
                assert wrong.status_code == 400 and "did not register" in wrong.text
                plain = await admin.post(
                    "/v1/oauth/authorize/check",
                    headers=WRITE,
                    json={**ask, "code_challenge_method": "plain"},
                )
                assert plain.status_code == 400

                denied = await admin.post(
                    "/v1/oauth/authorize/decision", headers=WRITE, json={**ask, "approve": False}
                )
                assert parse_qs(urlsplit(denied.json()["redirect"]).query) == {
                    "error": ["access_denied"],
                    "state": ["s-123"],
                }
                approved = await admin.post(
                    "/v1/oauth/authorize/decision", headers=WRITE, json={**ask, "approve": True}
                )
                assert approved.status_code == 200, approved.text
                back = urlsplit(approved.json()["redirect"])
                assert f"{back.scheme}://{back.hostname}{back.path}" == RETURN
                code = parse_qs(back.query)["code"][0]
                assert parse_qs(back.query)["state"] == ["s-123"]

                exchange = {
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": RETURN,
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "code_verifier": verifier,
                }
                wrong_verifier = await app_server.post(
                    "/v1/oauth/token", data={**exchange, "code_verifier": "x" * 50}
                )
                assert wrong_verifier.status_code == 400
                assert wrong_verifier.json()["error"] == "invalid_grant"
                no_secret = await app_server.post(
                    "/v1/oauth/token", data={**exchange, "client_secret": "sxcs_wrong"}
                )
                assert no_secret.status_code == 401
                tokens = await app_server.post("/v1/oauth/token", data=exchange)
                assert tokens.status_code == 200, tokens.text
                assert tokens.headers["cache-control"] == "no-store"
                body = tokens.json()
                assert body["token_type"] == "Bearer"  # noqa: S105 - a type name
                assert body["expires_in"] == 3600
                assert body["scope"] == "calls:read leads:read"

                bearer = {"Authorization": f"Bearer {body['access_token']}"}
                me = await app_server.get("/v1/api/me", headers=bearer)
                assert me.status_code == 200, me.text
                assert me.json()["organisation"]["id"] == str(setup.state.tenant_id)
                assert (await app_server.get("/v1/api/leads", headers=bearer)).status_code == 200
                write = await app_server.post("/v1/api/leads", headers=bearer, json={"name": "A"})
                assert write.status_code == 403  # leads:write was not approved

                again = await app_server.post("/v1/oauth/token", data=exchange)
                assert again.status_code == 400  # a code works once ...
                assert (await app_server.get("/v1/api/me", headers=bearer)).status_code == 401
                # ... and its second use ended what the first one made.

                # A fresh connection, then refresh and a replayed refresh token.
                verifier, challenge = _pkce()
                approved = await admin.post(
                    "/v1/oauth/authorize/decision",
                    headers=WRITE,
                    json={**ask, "code_challenge": challenge, "approve": True},
                )
                code = parse_qs(urlsplit(approved.json()["redirect"]).query)["code"][0]
                tokens = await app_server.post(
                    "/v1/oauth/token",
                    data={**exchange, "code": code, "code_verifier": verifier},
                )
                first_refresh = tokens.json()["refresh_token"]
                renewed = await app_server.post(
                    "/v1/oauth/token",
                    auth=(client_id, client_secret),
                    data={"grant_type": "refresh_token", "refresh_token": first_refresh},
                )
                assert renewed.status_code == 200, renewed.text
                fresh = {"Authorization": f"Bearer {renewed.json()['access_token']}"}
                assert (await app_server.get("/v1/api/me", headers=fresh)).status_code == 200
                replay = await app_server.post(
                    "/v1/oauth/token",
                    auth=(client_id, client_secret),
                    data={"grant_type": "refresh_token", "refresh_token": first_refresh},
                )
                assert replay.status_code == 400
                assert (await app_server.get("/v1/api/me", headers=fresh)).status_code == 401

                # A third connection, removed from Settings.
                verifier, challenge = _pkce()
                approved = await admin.post(
                    "/v1/oauth/authorize/decision",
                    headers=WRITE,
                    json={**ask, "code_challenge": challenge, "approve": True},
                )
                code = parse_qs(urlsplit(approved.json()["redirect"]).query)["code"][0]
                tokens = await app_server.post(
                    "/v1/oauth/token",
                    data={**exchange, "code": code, "code_verifier": verifier},
                )
                live = {"Authorization": f"Bearer {tokens.json()['access_token']}"}
                page = (await admin.get("/v1/sales-xray/integrations")).json()
                active = [c for c in page["connections"] if c["revoked_at"] is None]
                assert len(active) == 1 and active[0]["app"] == "Partner CRM"
                removed = await admin.post(
                    f"/v1/sales-xray/integrations/connections/{active[0]['id']}/revoke",
                    headers=WRITE,
                )
                assert removed.status_code == 200
                assert (await app_server.get("/v1/api/me", headers=live)).status_code == 401
                revoked_app = await admin.post(
                    f"/v1/sales-xray/integrations/apps/{made.json()['id']}/revoke", headers=WRITE
                )
                assert revoked_app.status_code == 200
                gone = await admin.post("/v1/oauth/authorize/check", headers=WRITE, json=ask)
                assert gone.status_code == 400 and "not registered" in gone.text
        finally:
            await setup.engine.dispose()

    run(exercise())
