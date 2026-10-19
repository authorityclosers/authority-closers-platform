"""WhatsApp Cloud API: settings, sealed tokens, Meta's webhook and the 24-hour window."""

import asyncio
import base64
import hashlib
import hmac
import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from ac_platform.lead_desk.whatsapp import cloud

KEY = base64.urlsafe_b64encode(b"k" * 32).decode()
ENV = {
    "AC_WHATSAPP_APP_ID": "2222222222",
    "AC_WHATSAPP_APP_SECRET": "wa-secret",
    "AC_WHATSAPP_CONFIG_ID": "3333333333",
    "AC_WHATSAPP_WEBHOOK_VERIFY_TOKEN": "verify-wa",
    "AC_LEAD_DESK_TOKEN_KEY": KEY,
}
TOKEN = "fake-business-token"  # noqa: S105 - a stand-in, never a real token


def cfg() -> cloud.WhatsAppConfig:
    value = cloud.config(ENV)
    assert value is not None
    return value


@pytest.mark.parametrize("missing", list(ENV))
def test_whatsapp_stays_off_until_every_setting_exists(missing: str) -> None:
    assert cloud.config({k: v for k, v in ENV.items() if k != missing}) is None


def test_the_graph_version_follows_the_meta_setting_unless_its_own_is_set() -> None:
    assert cfg().graph.endswith("/v23.0")
    assert cloud.config({**ENV, "AC_META_GRAPH_VERSION": "v24.0"}).graph.endswith("/v24.0")
    both = {**ENV, "AC_META_GRAPH_VERSION": "v24.0", "AC_WHATSAPP_GRAPH_VERSION": "v25.0"}
    assert cloud.config(both).graph.endswith("/v25.0")


def test_tokens_are_sealed_to_one_number_and_one_use() -> None:
    box = cloud.seal(cfg(), TOKEN, phone_number_id="10001", what="token")
    assert TOKEN not in json.dumps(box)
    assert cloud.unseal(cfg(), box, phone_number_id="10001", what="token") == TOKEN
    with pytest.raises(cloud.WhatsAppError):
        cloud.unseal(cfg(), box, phone_number_id="10002", what="token")
    with pytest.raises(cloud.WhatsAppError):
        cloud.unseal(cfg(), box, phone_number_id="10001", what="pin")


def test_a_pin_is_six_digits() -> None:
    pins = {cloud.new_pin() for _ in range(20)}
    assert all(len(pin) == 6 and pin.isdigit() for pin in pins) and len(pins) > 1


def test_numbers_and_the_24_hour_window() -> None:
    assert cloud.wa_id("+91 98765 43210") == "919876543210"
    assert cloud.wa_id("12") is None and cloud.wa_id(None) is None
    now = datetime(2027, 1, 15, 10, 0, tzinfo=UTC)
    assert cloud.window_open(now - timedelta(hours=23, minutes=59), now)
    assert not cloud.window_open(now - timedelta(hours=24), now)
    assert not cloud.window_open(None, now)
    assert cloud.window_closes(now) == now + timedelta(hours=24)


def test_template_parts_are_counted_and_filled() -> None:
    components = [
        {"type": "HEADER", "text": "Hello"},
        {"type": "BODY", "text": "Hi {{1}}, your visit is on {{2}}."},
    ]
    body = cloud.template_text(components)
    assert cloud.placeholders(body) == 2
    assert cloud.fill(body, ["Asha", "Monday"]) == "Hi Asha, your visit is on Monday."
    assert cloud.fill(body, ["Asha"]) == "Hi Asha, your visit is on {{2}}."
    assert cloud.placeholders("No parts") == 0


def _signed(body: bytes) -> str:
    return "sha256=" + hmac.new(b"wa-secret", body, hashlib.sha256).hexdigest()


def test_webhook_signature() -> None:
    body = b'{"object":"whatsapp_business_account"}'
    assert cloud.signature_ok("wa-secret", body, _signed(body))
    assert not cloud.signature_ok("wa-secret", body + b" ", _signed(body))
    assert not cloud.signature_ok("wa-secret", body, None)


WEBHOOK = {
    "object": "whatsapp_business_account",
    "entry": [
        {
            "id": "55500001",
            "changes": [
                {
                    "field": "messages",
                    "value": {
                        "messaging_product": "whatsapp",
                        "metadata": {
                            "display_phone_number": "+91 80000 00000",
                            "phone_number_id": "10001",
                        },
                        "contacts": [{"profile": {"name": "Asha Patil"}, "wa_id": "919876543210"}],
                        "messages": [
                            {
                                "from": "919876543210",
                                "id": "wamid.IN1",
                                "timestamp": "1800000000",
                                "type": "text",
                                "text": {"body": "Is the 3 BHK still available?"},
                            },
                            {
                                "from": "919876543210",
                                "id": "wamid.IN2",
                                "timestamp": "1800000060",
                                "type": "image",
                                "image": {
                                    "id": "MEDIA1",
                                    "mime_type": "image/jpeg",
                                    "caption": "Plot",
                                },
                            },
                            {
                                "from": "919876543210",
                                "id": "wamid.IN3",
                                "timestamp": "1800000120",
                                "type": "order",
                            },
                            {"from": "not-a-number", "id": "wamid.BAD", "type": "text"},
                        ],
                        "statuses": [
                            {"id": "wamid.OUT1", "status": "delivered", "timestamp": "1800000200"},
                            {
                                "id": "wamid.OUT2",
                                "status": "failed",
                                "timestamp": "1800000300",
                                "errors": [{"code": 131047, "title": "Re-engagement message"}],
                            },
                            {"id": "wamid.OUT3", "status": "deleted"},
                        ],
                    },
                },
                {
                    "field": "message_template_status_update",
                    "value": {
                        "event": "APPROVED",
                        "message_template_id": "77700001",
                        "message_template_name": "welcome_lead",
                        "message_template_language": "en",
                    },
                },
                {
                    "field": "phone_number_quality_update",
                    "value": {"display_phone_number": "+91 80000 00000", "event": "YELLOW"},
                },
            ],
        }
    ],
}


def test_a_delivery_says_what_arrived_what_was_delivered_and_template_reviews() -> None:
    delivery = cloud.parse(WEBHOOK)
    assert [(m.wamid, m.kind, m.body) for m in delivery.inbound] == [
        ("wamid.IN1", "text", "Is the 3 BHK still available?"),
        ("wamid.IN2", "image", "Plot"),
        ("wamid.IN3", "unsupported", None),
    ]
    first = delivery.inbound[0]
    assert (first.phone_number_id, first.wa_id, first.profile_name) == (
        "10001",
        "919876543210",
        "Asha Patil",
    )
    assert first.at == datetime.fromtimestamp(1800000000, UTC)
    assert delivery.inbound[1].media == {"id": "MEDIA1", "mime_type": "image/jpeg"}
    assert [(s.wamid, s.status, s.error_code) for s in delivery.statuses] == [
        ("wamid.OUT1", "delivered", None),
        ("wamid.OUT2", "failed", "131047"),
    ]
    assert [(t.meta_id, t.status) for t in delivery.templates] == [("77700001", "APPROVED")]
    assert delivery.quality == [("+91 80000 00000", "YELLOW")]
    assert cloud.parse({"object": "page", "entry": WEBHOOK["entry"]}).inbound == []


@pytest.mark.parametrize(
    "code, words",
    [
        (131047, "24 hours"),
        (190, "Connect the number again"),
        (132001, "isn't approved"),
        (130429, "limiting"),
        (1, "refused"),
    ],
)
def test_refusals_are_plain_words(code: int, words: str) -> None:
    error = cloud.refusal({"code": code})
    assert words in str(error) and error.code == code


def _api(handler) -> cloud.Cloud:
    return cloud.Cloud(cfg(), httpx.AsyncClient(transport=httpx.MockTransport(handler)))


def test_a_text_goes_to_the_numbers_messages_edge_with_the_token() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"messages": [{"id": "wamid.OUT9"}]})

    wamid = asyncio.run(_api(handler).send_text("10001", TOKEN, to="919876543210", body="Hello"))
    assert wamid == "wamid.OUT9"
    request = seen[0]
    assert request.url.path == "/v23.0/10001/messages"
    assert request.headers["authorization"] == f"Bearer {TOKEN}"
    assert json.loads(request.content) == {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": "919876543210",
        "type": "text",
        "text": {"preview_url": False, "body": "Hello"},
    }


def test_a_template_carries_its_language_and_body_values() -> None:
    seen: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        return httpx.Response(200, json={"messages": [{"id": "wamid.T1"}]})

    asyncio.run(
        _api(handler).send_template(
            "10001", TOKEN, to="919876543210", name="welcome_lead", language="en", values=["Asha"]
        )
    )
    assert seen[0]["template"] == {
        "name": "welcome_lead",
        "language": {"code": "en"},
        "components": [{"type": "body", "parameters": [{"type": "text", "text": "Asha"}]}],
    }


def test_a_number_already_registered_is_fine_but_other_refusals_are_not() -> None:
    def already(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": {"code": 133005}})

    asyncio.run(_api(already).register("10001", TOKEN, "123456"))

    def refused(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": {"code": 100}})

    with pytest.raises(cloud.WhatsAppError):
        asyncio.run(_api(refused).register("10001", TOKEN, "123456"))


def test_embedded_signup_code_is_swapped_for_the_business_token() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v23.0/oauth/access_token"
        assert request.url.params["code"] == "one-time"
        assert request.url.params["client_secret"] == ENV["AC_WHATSAPP_APP_SECRET"]
        assert "authorization" not in request.headers
        return httpx.Response(200, json={"access_token": TOKEN})

    assert asyncio.run(_api(handler).exchange("one-time")) == TOKEN


def test_embedded_signup_by_redirect_names_the_configuration() -> None:
    url = cloud.dialog_url(
        cfg(), redirect_uri="https://app.example/v1/lead-desk/whatsapp/callback", state="st"
    )
    assert url.startswith("https://www.facebook.com/v23.0/dialog/oauth?")
    assert "config_id=3333333333" in url and "client_id=2222222222" in url
    assert "response_type=code" in url and "state=st" in url


def test_the_shared_accounts_come_from_the_tokens_granted_scopes() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v23.0/debug_token"
        assert request.url.params["input_token"] == TOKEN
        return httpx.Response(
            200,
            json={
                "data": {
                    "granular_scopes": [
                        {"scope": "whatsapp_business_messaging", "target_ids": ["999999"]},
                        {
                            "scope": "whatsapp_business_management",
                            "target_ids": ["55500001", "bad"],
                        },
                    ]
                }
            },
        )

    assert asyncio.run(_api(handler).shared_accounts(TOKEN)) == ["55500001"]
