"""Phone alerts: FCM settings, what a message carries, and how FCM's answers are read."""

import base64
import json
from typing import Any
from uuid import uuid4

import httpx
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from ac_platform.lead_desk import push
from ac_platform.lead_desk.vocabulary import (
    MESSAGE_TEMPLATES,
    TEMPLATE_KEYS,
)


def _account() -> dict[str, Any]:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    return {
        "type": "service_account",
        "project_id": "sales-xray-test",
        "private_key_id": "test",
        "private_key": pem,
        "client_email": "push@sales-xray-test.iam.gserviceaccount.com",
        "client_id": "1",
        "token_uri": "https://oauth2.googleapis.com/token",
    }


DEVICE = "fcm-device-address"
CLIENT = {
    "AC_FCM_APP_ID": "1:123:android:abc",
    "AC_FCM_API_KEY": "test-api-key",
    "AC_FCM_SENDER_ID": "123",
}


def test_alerts_stay_off_until_every_setting_is_there() -> None:
    account = json.dumps(_account())
    assert push.config({}) is None
    assert push.config({"AC_FCM_SERVICE_ACCOUNT": account}) is None
    assert push.config({**CLIENT, "AC_FCM_SERVICE_ACCOUNT": "not json"}) is None
    assert push.config({**CLIENT, "AC_FCM_SERVICE_ACCOUNT": json.dumps({"type": "user"})}) is None
    raw = push.config({**CLIENT, "AC_FCM_SERVICE_ACCOUNT": account})
    encoded = push.config(
        {**CLIENT, "AC_FCM_SERVICE_ACCOUNT": base64.b64encode(account.encode()).decode()}
    )
    assert raw is not None and encoded is not None
    assert raw.project_id == encoded.project_id == "sales-xray-test"
    assert push.client_config(None).enabled is False
    client = push.client_config(raw)
    assert client.enabled and client.app_id == "1:123:android:abc"
    # The app gets public client settings only, never the service account.
    assert "private" not in client.model_dump_json()


def test_a_message_carries_ids_and_counts_never_names() -> None:
    tenant, person, lead = uuid4(), uuid4(), uuid4()
    alert = push.Alert(tenant_id=tenant, person_id=person, leads=[("new", lead)], to_call=3)
    assert alert.data() == {
        "type": "lead_desk",
        "kind": "new",
        "lead": str(lead),
        "tenant": str(tenant),
        "alerts": "1",
        "count": "3",
    }
    alert.leads.append(("due", uuid4()))
    assert alert.data()["kind"] == "many" and alert.data()["alerts"] == "2"
    assert all(isinstance(value, str) for value in alert.data().values())


@pytest.mark.parametrize(
    "status, body, outcome",
    [
        (200, {"name": "projects/x/messages/1"}, "sent"),
        (404, {"error": {"status": "NOT_FOUND"}}, "gone"),
        (400, {"error": {"message": "The registration token is not a valid FCM token"}}, "gone"),
        (500, {"error": {"status": "INTERNAL"}}, "failed"),
    ],
)
def test_fcm_answers(status: int, body: dict[str, Any], outcome: str) -> None:
    import asyncio

    cfg = push.config({**CLIENT, "AC_FCM_SERVICE_ACCOUNT": json.dumps(_account())})
    assert cfg is not None
    fcm = push.Fcm(cfg)
    seen: list[dict[str, Any]] = []

    async def token() -> str:
        return "access-token"

    fcm._token = token  # type: ignore[method-assign]

    def answer(request: httpx.Request) -> httpx.Response:
        seen.append({"url": str(request.url), "body": json.loads(request.content)})
        assert request.headers["authorization"] == "Bearer access-token"
        return httpx.Response(status, json=body)

    async def go() -> str:
        async with httpx.AsyncClient(transport=httpx.MockTransport(answer)) as client:
            return await fcm.send(client, DEVICE, {"type": "lead_desk"})

    assert asyncio.run(go()) == outcome
    assert seen[0]["url"].endswith("/v1/projects/sales-xray-test/messages:send")
    message = seen[0]["body"]["message"]
    assert message["token"] == DEVICE and message["android"]["priority"] == "HIGH"


def test_ready_messages_name_only_known_placeholders() -> None:
    allowed = {"{first_name}", "{my_name}", "{org}", "{about_interest}"}
    assert len(MESSAGE_TEMPLATES) == len(TEMPLATE_KEYS) >= 4
    for _, label, text in MESSAGE_TEMPLATES:
        assert label and text.startswith("Hi {first_name}")
        found = {part[: part.index("}") + 1] for part in ("{" + p for p in text.split("{")[1:])}
        assert found <= allowed, found
