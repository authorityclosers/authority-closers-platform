"""The organisation's webhook managed with an API key, on PostgreSQL (API gap 6, 15 Nov 2026).

An organisation's key held by an admin, with ``webhooks:manage``, does by API what Settings ->
Integrations does: reads the webhook and its menu, saves it (the secret shows once), sends a
signed test, rotates the secret, reads the deliveries and turns it off, each audited as from
the key. A seller's key is refused. A fictional partner address only.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
from pathlib import Path
from typing import Any, cast

import httpx
import pytest
from sqlalchemy import select, update

from ac_platform.audit.models import AuditEvent
from ac_platform.http.routes import RouteContext
from ac_platform.integrations.api_http import install_integrations_api
from ac_platform.integrations.http import install_integrations_http
from ac_platform.tenancy.models import Membership
from tests.database.test_conversation_postgresql import postgres_harness as _postgres_harness
from tests.database.test_conversation_postgresql import run
from tests.database.test_conversation_submission_http_postgresql import ORIGIN, _setup
from tests.database.test_lead_desk_postgresql import _organisation

WRITE = {"Origin": ORIGIN, "Content-Type": "application/json"}
HOOK = "https://partner.example.test/hooks/sales-xray"


@pytest.fixture
def postgres_harness() -> Any:
    yield from cast(Any, _postgres_harness).__wrapped__()


def _signed_by(request: httpx.Request, secret: str) -> bool:
    header = request.headers["X-SX-Signature"]
    stamp = dict(item.split("=", 1) for item in header.split(",")[:1])["t"]
    values = [item.split("=", 1)[1] for item in header.split(",") if item.startswith("v1=")]
    expected = hmac.new(
        secret.encode(), f"{stamp}.".encode() + request.content, hashlib.sha256
    ).hexdigest()
    return expected in values


def test_an_admins_key_manages_the_webhook_and_a_sellers_cannot(
    postgres_harness: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AC_INTEGRATIONS_SEAL_KEY", base64.urlsafe_b64encode(b"w" * 32).decode())
    received: list[httpx.Request] = []

    def partner(request: httpx.Request) -> httpx.Response:
        received.append(request)
        return httpx.Response(204)

    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path)
        try:
            await _organisation(setup)  # the signed-in person is an admin
            context = RouteContext(setup.settings, setup.require_actor, setup.sessions)
            install_integrations_http(setup.app, context)
            install_integrations_api(setup.app, context)
            setup.app.state.integrations_http_client = httpx.AsyncClient(
                transport=httpx.MockTransport(partner)
            )
            transport = httpx.ASGITransport(app=setup.app)
            async with (
                httpx.AsyncClient(transport=transport, base_url=ORIGIN) as page,
                httpx.AsyncClient(transport=transport, base_url=ORIGIN) as app,
            ):
                page.cookies.set(setup.settings.session_cookie_name, setup.token)
                made = await page.post(
                    "/v1/sales-xray/integrations/keys",
                    headers=WRITE,
                    json={"name": "Fictional ops", "scopes": ["webhooks:manage"]},
                )
                assert made.status_code == 200, made.text
                bearer = {"Authorization": f"Bearer {made.json()['key']}"}

                shown = await app.get("/v1/api/webhook", headers=bearer)
                assert shown.status_code == 200, shown.text
                assert shown.json()["webhook"] is None
                assert "analysis.completed" in {
                    item["key"] for item in shown.json()["menu"]["events"]
                }
                early = await app.post("/v1/api/webhook/test", headers=bearer)
                assert early.status_code == 409

                saved = await app.put(
                    "/v1/api/webhook",
                    headers=bearer,
                    json={"url": HOOK, "events": ["analysis.completed", "lead.created"]},
                )
                assert saved.status_code == 200, saved.text
                secret = saved.json()["secret"]
                assert secret.startswith("whsec_")
                assert saved.json()["webhook"]["secret_hint"] == secret[-4:]
                refused = await app.put(
                    "/v1/api/webhook",
                    headers=bearer,
                    json={"url": "http://partner.example.test/x", "events": ["lead.created"]},
                )
                assert refused.status_code == 422
                assert refused.json()["error"]["code"] == "url"

                tested = await app.post("/v1/api/webhook/test", headers=bearer)
                assert tested.status_code == 200, tested.text
                assert tested.json()["delivered"] and tested.json()["http_status"] == 204
                assert _signed_by(received[-1], secret)

                rotated = await app.post("/v1/api/webhook/rotate", headers=bearer)
                assert rotated.status_code == 200, rotated.text
                second = rotated.json()["secret"]
                assert second != secret
                finished = await app.post("/v1/api/webhook/rotate/finish", headers=bearer)
                assert finished.status_code == 200, finished.text
                await app.post("/v1/api/webhook/test", headers=bearer)
                assert _signed_by(received[-1], second)
                assert not _signed_by(received[-1], secret)

                log = await app.get("/v1/api/webhook/deliveries", headers=bearer)
                assert log.status_code == 200 and log.json()["deliveries"] == []

                # A seller's key can't manage it.
                async with setup.sessions() as db, db.begin():
                    await db.execute(
                        update(Membership)
                        .where(
                            Membership.tenant_id == setup.state.tenant_id,
                            Membership.person_id == setup.state.person_id,
                        )
                        .values(role="member")
                    )
                seller = await app.get("/v1/api/webhook", headers=bearer)
                assert seller.status_code == 403
                assert seller.json()["error"]["code"] == "managers_only"
                async with setup.sessions() as db, db.begin():
                    await db.execute(
                        update(Membership)
                        .where(
                            Membership.tenant_id == setup.state.tenant_id,
                            Membership.person_id == setup.state.person_id,
                        )
                        .values(role="admin")
                    )

                off = await app.post("/v1/api/webhook/disable", headers=bearer)
                assert off.status_code == 200 and off.json()["webhook"] is None
                async with setup.sessions() as db:
                    actions = (
                        await db.scalars(
                            select(AuditEvent.action).where(
                                AuditEvent.actor_type == "api_key",
                                AuditEvent.action.like("integration.webhook%"),
                            )
                        )
                    ).all()
                assert set(actions) == {
                    "integration.webhook_saved",
                    "integration.webhook_secret_rotation_started",
                    "integration.webhook_secret_rotation_finished",
                    "integration.webhook_disabled",
                }
            await setup.app.state.integrations_http_client.aclose()
        finally:
            await setup.engine.dispose()

    run(exercise())
