"""The Pulse org link on PostgreSQL, against a fictional Pulse (no network).

An admin connects the organisation; Pulse's approval comes back to the callback, which
swaps the code with PKCE, seals the link's tokens, registers the webhook and reads the
directory. Members are matched by verified email (never an unverified one), the match
copies the Pulse title and team to the person's profile, the missing one is invited as
a Seller, a signed webhook makes Sales X-Ray read that member again (a bad signature
changes nothing), photos can be turned off, and unlinking ends it at Pulse too. Nobody
but an owner or admin sees any of it. Fictional people only.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from pathlib import Path
from typing import Any, cast
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from pydantic import SecretStr
from sqlalchemy import select, update

from ac_platform.http.routes import RouteContext
from ac_platform.pulse import http as pulse_http
from ac_platform.pulse.http import install_pulse_http
from ac_platform.pulse.models import PersonPulseProfile, PulseOrgLink
from ac_platform.pulse.oidc import PulseClient
from ac_platform.tenancy.models import Membership, OrganisationInvite
from tests.database.test_conversation_postgresql import postgres_harness as _postgres_harness
from tests.database.test_conversation_postgresql import run
from tests.database.test_conversation_submission_http_postgresql import ORIGIN, _setup
from tests.database.test_lead_desk_postgresql import _organisation

PULSE = "https://pulse.example.test"
WRITE = {"Origin": ORIGIN, "Content-Type": "application/json"}
SEAL = base64.urlsafe_b64encode(b"k" * 32).decode()
HOOK_SECRET = "pwhs_fictional_webhook_secret_000000"  # noqa: S105 - a test value


@pytest.fixture
def postgres_harness() -> Any:
    yield from cast(Any, _postgres_harness).__wrapped__()


class FakePulse:
    def __init__(self, owner_email: str) -> None:
        self.members: dict[str, dict[str, Any]] = {
            "p-owner": {
                "sub": "p-owner",
                "email": owner_email,
                "email_verified": True,
                "name": "Fictional Owner",
                "title": "Founder",
                "team": "Leadership",
                "picture": None,
                "role": "admin",
                "status": "active",
                "updated_at": "2026-10-25T10:00:00Z",
            },
            "p-new": {
                "sub": "p-new",
                "email": "rohan.iyer@example.test",
                "email_verified": True,
                "name": "Rohan Iyer",
                "title": "Sales executive",
                "team": "Inside sales",
                "role": "member",
                "status": "active",
                "updated_at": "2026-10-25T10:00:00Z",
            },
            "p-unchecked": {
                "sub": "p-unchecked",
                "email": "neha.k@example.test",
                "email_verified": False,
                "name": "Neha K",
                "role": "member",
                "status": "active",
                "updated_at": "2026-10-25T10:00:00Z",
            },
        }
        self.calls: list[tuple[str, str]] = []
        self.codes: list[dict[str, list[str]]] = []
        self.verifier_ok = False
        self.ended = False

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        self.calls.append((request.method, path))
        if path == "/.well-known/openid-configuration":
            return httpx.Response(
                200,
                json={
                    "issuer": PULSE,
                    "authorization_endpoint": f"{PULSE}/oauth/authorize",
                    "token_endpoint": f"{PULSE}/oauth/token",
                    "jwks_uri": f"{PULSE}/oauth/jwks",
                    "revocation_endpoint": f"{PULSE}/oauth/revoke",
                    "pulse_org_api_base": f"{PULSE}/api/v1/connect",
                    "code_challenge_methods_supported": ["S256"],
                },
            )
        if path == "/oauth/token":
            form = parse_qs(request.content.decode())
            self.codes.append(form)
            if form["grant_type"] == ["authorization_code"]:
                return httpx.Response(
                    200,
                    json={
                        "access_token": "pxa_access_1",
                        "refresh_token": "pxr_refresh_1",
                        "expires_in": 600,
                        "scope": "openid pulse.org.read pulse.org.webhooks",
                        "pulse_org_id": "org-greenleaf",
                        "pulse_org_name": "Greenleaf Realty (test)",
                    },
                )
            if self.ended:
                return httpx.Response(400, json={"error": "invalid_grant"})
            return httpx.Response(200, json={"access_token": "pxa_access_2", "expires_in": 600})
        if path == "/oauth/revoke":
            return httpx.Response(200)
        base = "/api/v1/connect/orgs/org-greenleaf"
        if request.headers.get("authorization", "").split(" ")[-1] not in {
            "pxa_access_1",
            "pxa_access_2",
        }:
            return httpx.Response(401)
        if path == f"{base}/members":
            return httpx.Response(
                200, json={"members": list(self.members.values()), "next_cursor": None}
            )
        if path.startswith(f"{base}/members/"):
            found = self.members.get(path.rsplit("/", 1)[1])
            return httpx.Response(200, json=found) if found else httpx.Response(404)
        if path == f"{base}/webhooks" and request.method == "POST":
            body = json.loads(request.content)
            assert body["url"] == f"{ORIGIN}/v1/api/pulse/webhook"
            return httpx.Response(201, json={"id": "wh-1", "secret": HOOK_SECRET})
        if path in {f"{base}/webhooks/wh-1", f"{base}/link"} and request.method == "DELETE":
            self.ended = True
            return httpx.Response(204)
        return httpx.Response(404)


def _signed(body: bytes, secret: str = HOOK_SECRET) -> dict[str, str]:
    stamp = str(int(time.time()))
    digest = hmac.new(secret.encode(), stamp.encode() + b"." + body, hashlib.sha256)
    return {
        "content-type": "application/json",
        "x-pulse-event": "person.updated",
        "x-pulse-event-id": "evt-1",
        "x-pulse-signature": f"t={stamp},v1={digest.hexdigest()}",
    }


def test_an_admin_links_the_organisation_to_its_pulse_org(
    postgres_harness: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def no_photo(*_args: Any, **_kwargs: Any) -> None:
        return None

    monkeypatch.setattr(pulse_http, "fetch_pulse_photo", no_photo)
    # Seats are the organisation service's own rule (it refuses when they are full,
    # and the page shows its words); here every invite has a seat.
    monkeypatch.setattr(pulse_http, "seat_exempt", lambda *_args, **_kwargs: True)

    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path)
        try:
            await _organisation(setup)
            async with setup.sessions() as db, db.begin():
                owner = await db.scalar(
                    select(Membership).where(Membership.person_id == setup.state.person_id)
                )
                assert owner is not None
                from ac_platform.identity.models import Person

                person = await db.get(Person, setup.state.person_id)
                assert person is not None and person.email_verified_at is not None
                owner_email = str(person.email)
            pulse = FakePulse(owner_email)
            settings = setup.settings.model_copy(
                update={
                    "public_learner_tenant_id": setup.settings.operations_tenant_id,
                    "pulse_issuer": PULSE,
                    "pulse_client_id": "sx-test",
                    "pulse_client_secret": SecretStr("fictional-secret-0000"),
                    "pulse_seal_key": SecretStr(SEAL),
                }
            )
            client = PulseClient(
                issuer=PULSE,
                client_id="sx-test",
                client_secret="fictional-secret-0000",  # noqa: S106 - a test value
                http_client=httpx.AsyncClient(transport=httpx.MockTransport(pulse.handler)),
            )
            install_pulse_http(
                setup.app,
                RouteContext(settings, setup.require_actor, setup.sessions),
                client=client,
            )
            transport = httpx.ASGITransport(app=setup.app)
            async with (
                httpx.AsyncClient(transport=transport, base_url=ORIGIN) as admin,
                httpx.AsyncClient(transport=transport, base_url=ORIGIN) as outsider,
                httpx.AsyncClient(transport=transport, base_url=ORIGIN) as pulse_server,
            ):
                admin.cookies.set(setup.settings.session_cookie_name, setup.token)
                assert (await outsider.get("/v1/sales-xray/pulse")).status_code == 401
                before = await admin.get("/v1/sales-xray/pulse")
                assert before.status_code == 200, before.text
                assert before.json()["configured"] is True
                assert before.json()["link"] is None

                started = await admin.post("/v1/sales-xray/pulse/connect", headers=WRITE)
                assert started.status_code == 200, started.text
                asked = parse_qs(urlsplit(started.json()["redirect_url"]).query)
                assert asked["scope"] == ["openid pulse.org.read pulse.org.webhooks"]
                assert asked["code_challenge_method"] == ["S256"]
                assert asked["redirect_uri"] == [f"{ORIGIN}/v1/integrations/pulse/callback"]
                state = asked["state"][0]

                # Someone else's browser can't finish it; a wrong state finds nothing.
                assert (
                    (
                        await outsider.get(
                            "/v1/integrations/pulse/callback", params={"state": state, "code": "c"}
                        )
                    )
                    .headers["location"]
                    .endswith("pulse=sign_in")
                )
                wrong = await admin.get(
                    "/v1/integrations/pulse/callback", params={"state": "x" * 43, "code": "c"}
                )
                assert wrong.headers["location"].endswith("pulse=expired")

                back = await admin.get(
                    "/v1/integrations/pulse/callback", params={"state": state, "code": "code-1"}
                )
                assert back.status_code == 303
                assert back.headers["location"] == (
                    f"{ORIGIN}/organisation?tab=connections&part=pulse&pulse=connected"
                )
                [exchange] = [
                    form for form in pulse.codes if form["grant_type"] == ["authorization_code"]
                ]
                assert exchange["code"] == ["code-1"]
                challenge = (
                    base64.urlsafe_b64encode(
                        hashlib.sha256(exchange["code_verifier"][0].encode()).digest()
                    )
                    .rstrip(b"=")
                    .decode()
                )
                assert asked["code_challenge"] == [challenge]
                # The same approval can't be replayed.
                replay = await admin.get(
                    "/v1/integrations/pulse/callback", params={"state": state, "code": "code-1"}
                )
                assert replay.headers["location"].endswith("pulse=expired")

                async with setup.sessions() as db:
                    link = await db.scalar(select(PulseOrgLink))
                    assert link is not None and link.status == "active"
                    assert link.pulse_org_id == "org-greenleaf"
                    assert link.webhook_id == "wh-1"
                    # Keys are sealed, never stored as given.
                    for value in ("pxr_refresh_1", "pxa_access_1", HOOK_SECRET):
                        assert value not in str(
                            (
                                link.sealed_refresh_token,
                                link.sealed_access_token,
                                link.sealed_webhook_secret,
                            )
                        )
                    profile = await db.scalar(
                        select(PersonPulseProfile).where(
                            PersonPulseProfile.person_id == setup.state.person_id
                        )
                    )
                    assert profile is not None
                    assert (profile.title, profile.team, profile.source) == (
                        "Founder",
                        "Leadership",
                        "org_link",
                    )

                page = (await admin.get("/v1/sales-xray/pulse")).json()
                assert page["link"]["pulse_org_name"] == "Greenleaf Realty (test)"
                by_sub = {member["name"]: member for member in page["members"]}
                assert by_sub["Fictional Owner"]["matched_by"] == "email"
                assert by_sub["Rohan Iyer"]["can_invite"] is True
                # An address Pulse never checked neither matches nor gets an invite.
                assert by_sub["Neha K"]["person_id"] is None
                assert by_sub["Neha K"]["can_invite"] is False
                people = (await admin.get("/v1/sales-xray/pulse/people")).json()["people"]
                assert people[str(setup.state.person_id)]["title"] == "Founder"

                invited = await admin.post(
                    "/v1/sales-xray/pulse/invite",
                    headers=WRITE,
                    json={"members": [by_sub["Rohan Iyer"]["id"], by_sub["Neha K"]["id"]]},
                )
                assert invited.status_code == 200, invited.text
                assert invited.json()["invited"] == [by_sub["Rohan Iyer"]["id"]], invited.json()[
                    "refused"
                ]
                async with setup.sessions() as db:
                    invite = await db.scalar(
                        select(OrganisationInvite).where(
                            OrganisationInvite.email_normalized == "rohan.iyer@example.test"
                        )
                    )
                    assert invite is not None and invite.role == "member"

                # A signed notice: Sales X-Ray reads the member again from Pulse.
                pulse.members["p-owner"] = {
                    **pulse.members["p-owner"],
                    "title": "Managing director",
                    "updated_at": "2026-10-25T11:00:00Z",
                }
                body = json.dumps(
                    {
                        "event_id": "evt-1",
                        "type": "person.updated",
                        "org_id": "org-greenleaf",
                        "sub": "p-owner",
                        "changed": ["title"],
                        # A body never writes data by itself.
                        "title": "Hacker",
                    }
                ).encode()
                forged = await pulse_server.post(
                    "/v1/api/pulse/webhook", content=body, headers=_signed(body, "whsec_wrong")
                )
                assert forged.status_code == 401
                notice = await pulse_server.post(
                    "/v1/api/pulse/webhook", content=body, headers=_signed(body)
                )
                assert notice.status_code == 202, notice.text
                async with setup.sessions() as db:
                    profile = await db.scalar(
                        select(PersonPulseProfile).where(
                            PersonPulseProfile.person_id == setup.state.person_id
                        )
                    )
                    assert profile is not None and profile.title == "Managing director"

                shared = await admin.put(
                    "/v1/sales-xray/pulse/sharing",
                    headers=WRITE,
                    json={"photos": "off", "signals": "off"},
                )
                assert shared.status_code == 200
                assert shared.json()["link"]["sharing"]["photos"] == "off"

                # A plain member sees none of it.
                async with setup.sessions() as db, db.begin():
                    await db.execute(
                        update(Membership)
                        .where(Membership.person_id == setup.state.person_id)
                        .values(role="member")
                    )
                assert (await admin.get("/v1/sales-xray/pulse")).status_code == 403
                assert (
                    await admin.post("/v1/sales-xray/pulse/disconnect", headers=WRITE)
                ).status_code == 403
                async with setup.sessions() as db, db.begin():
                    await db.execute(
                        update(Membership)
                        .where(Membership.person_id == setup.state.person_id)
                        .values(role="admin")
                    )

                ended = await admin.post("/v1/sales-xray/pulse/disconnect", headers=WRITE)
                assert ended.status_code == 200, ended.text
                assert ended.json()["told_pulse"] is True and ended.json()["link"] is None
                assert ("DELETE", "/api/v1/connect/orgs/org-greenleaf/link") in pulse.calls
                async with setup.sessions() as db:
                    link = await db.scalar(select(PulseOrgLink))
                    assert link is not None and link.status == "revoked"
                    assert link.sealed_refresh_token is None
                # After unlinking, notices are refused.
                late = await pulse_server.post(
                    "/v1/api/pulse/webhook", content=body, headers=_signed(body)
                )
                assert late.status_code == 401
        finally:
            await setup.engine.dispose()

    run(exercise())
