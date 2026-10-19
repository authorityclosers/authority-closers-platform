"""Dev's webhook aliases: /v1/lead-desk/meta/webhook/whatsapp and …/messaging are the
same handlers as /whatsapp/webhook and /messaging/webhook, with the same checks.

Dev sits behind Cloudflare Access, and only the Leads webhook path
(/v1/lead-desk/meta/webhook and below) has the bypass Meta needs; the aliases live
under it. Staging and production use the canonical paths.
"""

import hashlib
import hmac
import json
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

import httpx
import pytest

from ac_platform.http.routes import RouteContext
from ac_platform.lead_desk.social.http import install_social_http
from ac_platform.lead_desk.whatsapp.http import install_whatsapp_http
from tests.database.test_conversation_postgresql import postgres_harness as _postgres_harness
from tests.database.test_conversation_postgresql import run
from tests.database.test_conversation_submission_http_postgresql import ORIGIN, _setup
from tests.unit.lead_desk_whatsapp.test_whatsapp_cloud import ENV as WHATSAPP_ENV

ENV = {**WHATSAPP_ENV, "AC_MESSAGING_LOGIN_CONFIG_ID": "5550001"}
BASE = "/v1/lead-desk"
PATHS = {
    "whatsapp": ("/meta/webhook/whatsapp", "/whatsapp/webhook"),
    "messaging": ("/meta/webhook/messaging", "/messaging/webhook"),
}
EMPTY = {
    "whatsapp": {"object": "whatsapp_business_account", "entry": []},
    "messaging": {"object": "page", "entry": []},
}


@pytest.fixture
def postgres_harness() -> Any:
    yield from cast(Any, _postgres_harness).__wrapped__()


def _signed(payload: dict[str, Any], secret: str) -> tuple[bytes, dict[str, str]]:
    body = json.dumps(payload).encode()
    signature = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return body, {"content-type": "application/json", "x-hub-signature-256": signature}


def test_dev_aliases_answer_like_the_canonical_webhooks(
    postgres_harness: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for name, value in ENV.items():
        monkeypatch.setenv(name, value)

    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path)
        try:
            settings = setup.settings.model_copy(update={"public_learner_tenant_id": uuid4()})
            context = RouteContext(settings, setup.require_actor, setup.sessions)
            install_whatsapp_http(setup.app, context)
            install_social_http(setup.app, context)
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=setup.app), base_url=ORIGIN
            ) as client:
                token = ENV["AC_WHATSAPP_WEBHOOK_VERIFY_TOKEN"]
                secret = ENV["AC_WHATSAPP_APP_SECRET"]
                for kind, paths in PATHS.items():
                    for path in paths:
                        url = f"{BASE}{path}"
                        right = await client.get(
                            url,
                            params={
                                "hub.mode": "subscribe",
                                "hub.verify_token": token,
                                "hub.challenge": "4242",
                            },
                        )
                        assert (right.status_code, right.text) == (200, "4242"), (kind, path)
                        wrong = await client.get(
                            url,
                            params={
                                "hub.mode": "subscribe",
                                "hub.verify_token": "not-it",
                                "hub.challenge": "4242",
                            },
                        )
                        assert wrong.status_code == 403, (kind, path)
                        bad = await client.post(
                            url,
                            content=b"{}",
                            headers={
                                "content-type": "application/json",
                                "x-hub-signature-256": "sha256=00",
                            },
                        )
                        assert bad.status_code == 401, (kind, path)
                        body, headers = _signed(EMPTY[kind], secret)
                        good = await client.post(url, content=body, headers=headers)
                        assert good.status_code == 200, (kind, path, good.text)
                # Not a catch-all: anything else under /meta/webhook stays unknown.
                other = await client.get(f"{BASE}/meta/webhook/other")
                assert other.status_code in (404, 405)
        finally:
            await setup.engine.dispose()

    run(exercise())
