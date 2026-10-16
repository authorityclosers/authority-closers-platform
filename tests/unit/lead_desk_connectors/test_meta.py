"""Meta Lead Ads: Continue with Meta, sealed Page tokens, signed webhooks, every answer kept."""

import asyncio
import base64
import hashlib
import hmac
import json
from uuid import uuid4

import httpx
import pytest

from ac_platform.lead_desk.capture import extract
from ac_platform.lead_desk.connectors import meta

KEY = base64.urlsafe_b64encode(b"k" * 32).decode()
ENV = {
    "AC_META_APP_ID": "1234567890",
    "AC_META_APP_SECRET": "app-secret",
    "AC_META_LOGIN_CONFIG_ID": "987654321",
    "AC_META_WEBHOOK_VERIFY_TOKEN": "verify-me",
    "AC_LEAD_DESK_TOKEN_KEY": KEY,
}


def cfg() -> meta.MetaConfig:
    value = meta.config(ENV)
    assert value is not None
    return value


@pytest.mark.parametrize("missing", list(ENV))
def test_the_connector_stays_off_until_every_setting_exists(missing: str) -> None:
    assert meta.config({k: v for k, v in ENV.items() if k != missing}) is None


def test_a_short_token_key_keeps_it_off() -> None:
    assert (
        meta.config({**ENV, "AC_LEAD_DESK_TOKEN_KEY": base64.urlsafe_b64encode(b"x" * 16).decode()})
        is None
    )


def test_graph_version_defaults_and_can_be_set() -> None:
    assert cfg().graph.endswith("/v23.0")
    assert meta.config({**ENV, "AC_META_GRAPH_VERSION": "v25.0"}).graph.endswith("/v25.0")


def test_page_tokens_are_sealed_and_bound_to_their_page() -> None:
    key = cfg().token_key
    box = meta.seal(key, "page-token-abc", page_id="111")
    assert "page-token-abc" not in json.dumps(box)
    assert meta.unseal(key, box, page_id="111") == "page-token-abc"
    with pytest.raises(meta.MetaError):
        meta.unseal(key, box, page_id="222")
    with pytest.raises(meta.MetaError):
        meta.unseal(b"z" * 32, box, page_id="111")


def test_state_round_trips_for_the_same_person_and_workspace() -> None:
    tenant, person = uuid4(), uuid4()
    state = meta.make_state("s", tenant_id=tenant, person_id=person, now=1000)
    meta.read_state("s", state, tenant_id=tenant, person_id=person, now=1001)


def test_state_refuses_tampering_expiry_and_other_people() -> None:
    tenant, person = uuid4(), uuid4()
    state = meta.make_state("s", tenant_id=tenant, person_id=person, now=1000)
    raw, mac = state.split(".")
    with pytest.raises(meta.MetaError):
        meta.read_state("other", state, tenant_id=tenant, person_id=person, now=1001)
    with pytest.raises(meta.MetaError):
        meta.read_state("s", raw + "x." + mac, tenant_id=tenant, person_id=person, now=1001)
    with pytest.raises(meta.MetaError):
        meta.read_state(
            "s", state, tenant_id=tenant, person_id=person, now=1000 + meta.STATE_SECONDS + 1
        )
    with pytest.raises(meta.MetaError):
        meta.read_state("s", state, tenant_id=tenant, person_id=uuid4(), now=1001)
    with pytest.raises(meta.MetaError):
        meta.read_state("s", "garbage", tenant_id=tenant, person_id=person, now=1001)


def test_dialog_asks_for_the_business_login_configuration() -> None:
    url = meta.dialog_url(
        cfg(), redirect_uri="https://app.example/v1/lead-desk/meta/callback", state="st"
    )
    assert url.startswith("https://www.facebook.com/v23.0/dialog/oauth?")
    assert "config_id=987654321" in url and "client_id=1234567890" in url and "state=st" in url


def test_webhook_signature() -> None:
    body = b'{"object":"page"}'
    good = "sha256=" + hmac.new(b"app-secret", body, hashlib.sha256).hexdigest()
    assert meta.signature_ok("app-secret", body, good)
    assert not meta.signature_ok("app-secret", body + b" ", good)
    assert not meta.signature_ok("app-secret", body, None)
    assert not meta.signature_ok("app-secret", body, "sha1=abc")


WEBHOOK = {
    "object": "page",
    "entry": [
        {
            "id": "111",
            "time": 1760000000,
            "changes": [
                {
                    "field": "leadgen",
                    "value": {"leadgen_id": "L1", "page_id": "111", "form_id": "F1", "ad_id": "A1"},
                },
                {"field": "feed", "value": {"item": "status"}},
                {"field": "leadgen", "value": {"leadgen_id": "L2", "form_id": "F2"}},
            ],
        },
        "junk",
    ],
}


def test_lead_events_reads_only_new_lead_notices() -> None:
    events = meta.lead_events(WEBHOOK)
    assert [(e.leadgen_id, e.page_id, e.form_id) for e in events] == [
        ("L1", "111", "F1"),
        ("L2", "111", "F2"),
    ]
    assert meta.lead_events({"object": "user", "entry": WEBHOOK["entry"]}) == []


@pytest.mark.parametrize(
    "forms, form_id, expected",
    [
        ("all", "F1", True),
        (None, None, True),
        (["F1"], "F1", True),
        (["F1"], "F2", False),
        (["F1"], None, False),
    ],
)
def test_wants_form(forms: object, form_id: str | None, expected: bool) -> None:
    assert meta.wants_form(forms, form_id) is expected


LEAD = {
    "id": "L1",
    "created_time": "2026-10-16T06:00:00+0000",
    "field_data": [
        {"name": "full_name", "values": ["Meera Shah"]},
        {"name": "phone_number", "values": ["+919811122233"]},
        {"name": "email", "values": ["meera@example.com"]},
        {"name": "city", "values": ["Ahmedabad"]},
        {"name": "what_is_your_budget?", "values": ["2-5 lakh"]},
    ],
    "ad_id": "A1",
    "campaign_name": "Solar Oct",
    "form_id": "F1",
    "platform": "ig",
    "is_organic": False,
}


def test_lead_record_keeps_every_answer_and_metas_ids() -> None:
    record = meta.lead_record(LEAD, page_name="Rao Solar")
    found = extract(record)
    assert (found.name, found.phone, found.email, found.city) == (
        "Meera Shah",
        "+919811122233",
        "meera@example.com",
        "Ahmedabad",
    )
    assert record["leadgen_id"] == "L1"
    assert record["meta"]["campaign_name"] == "Solar Oct"
    assert record["meta"]["is_organic"] is False
    assert any(item["name"] == "what_is_your_budget?" for item in record["field_data"])
    assert record["lead_source"] == "Meta · Rao Solar"


def _graph(handler) -> meta.Graph:
    return meta.Graph(cfg(), client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))


def test_graph_reads_pages_with_tokens() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v23.0/me/accounts"
        return httpx.Response(
            200,
            json={
                "data": [
                    {"id": "111", "name": "Rao Solar", "access_token": "t1"},
                    {"id": "222", "name": "No token"},
                ]
            },
        )

    pages = asyncio.run(_graph(handler).pages("user-token"))
    assert pages == [{"id": "111", "name": "Rao Solar", "token": "t1"}]


@pytest.mark.parametrize(
    "code, words",
    [(190, "Connect the Page again"), (200, "permission"), (1, "refused")],
)
def test_graph_errors_become_plain_messages(code: int, words: str) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": {"code": code, "message": "x"}})

    with pytest.raises(meta.MetaError, match=words):
        asyncio.run(_graph(handler).lead("L1", "t"))


def test_subscribe_needs_success() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST" and request.url.path == "/v23.0/111/subscribed_apps"
        assert b"subscribed_fields=leadgen" in request.content
        return httpx.Response(200, json={"success": True})

    asyncio.run(_graph(handler).subscribe("111", "t"))
