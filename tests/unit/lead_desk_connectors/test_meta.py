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


def _leads_handler(pages: dict[str | None, dict]) -> tuple[list[dict], object]:
    seen: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        params = dict(request.url.params)
        seen.append(params)
        return httpx.Response(200, json=pages[params.get("after")])

    return seen, handler


PAGED = {
    None: {
        "data": [{"id": "L1"}, {"id": "L2"}],
        "paging": {"cursors": {"after": "c1"}, "next": "https://graph.facebook.com/next"},
    },
    "c1": {"data": [{"id": "L3"}], "paging": {"cursors": {"after": "c2"}}},
}


def test_recent_leads_follows_metas_pages_to_the_end() -> None:
    seen, handler = _leads_handler(PAGED)
    leads = asyncio.run(_graph(handler).recent_leads(["F1"], "t", since=100))
    assert [lead["id"] for lead in leads] == ["L1", "L2", "L3"]
    assert [params.get("after") for params in seen] == [None, "c1"]
    assert json.loads(seen[0]["filtering"]) == [
        {"field": "time_created", "operator": "GREATER_THAN", "value": 100}
    ]


def test_recent_leads_stops_at_its_limit() -> None:
    seen, handler = _leads_handler(PAGED)
    leads = asyncio.run(_graph(handler).recent_leads(["F1", "F2"], "t", since=100, limit=2))
    assert [lead["id"] for lead in leads] == ["L1", "L2"]
    assert len(seen) == 1 and seen[0]["limit"] == "2"


def test_one_page_of_leads_returns_metas_next_cursor() -> None:
    _, handler = _leads_handler(PAGED)
    graph = _graph(handler)
    rows, after = asyncio.run(graph.leads_page("F1", "t", since=100))
    assert ([row["id"] for row in rows], after) == (["L1", "L2"], "c1")
    rows, after = asyncio.run(graph.leads_page("F1", "t", since=100, after="c1"))
    assert ([row["id"] for row in rows], after) == (["L3"], None)


def test_forms_lists_every_form_archived_ones_too() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v23.0/111/leadgen_forms"
        if request.url.params.get("after") == "c1":
            return httpx.Response(200, json={"data": [{"id": "F2", "status": "ARCHIVED"}]})
        return httpx.Response(
            200,
            json={
                "data": [{"id": "F1", "name": "Enquiry", "status": "ACTIVE"}],
                "paging": {"cursors": {"after": "c1"}, "next": "https://graph.facebook.com/n"},
            },
        )

    forms = asyncio.run(_graph(handler).forms("111", "t"))
    assert forms == [
        {"id": "F1", "name": "Enquiry", "status": "ACTIVE"},
        {"id": "F2", "name": "F2", "status": "ARCHIVED"},
    ]


@pytest.mark.parametrize(
    "error, kind",
    [
        ({"code": 190}, "token"),
        (
            {"code": 200, "message": "Lead access is restricted by the Leads Access Manager"},
            "lead_access",
        ),
        ({"code": 100, "message": "This app has no leads access for the page"}, "lead_access"),
        ({"code": 10}, "permission"),
        ({"code": 1}, "other"),
    ],
)
def test_graph_errors_say_what_the_manager_can_do(error: dict, kind: str) -> None:
    assert meta.graph_error(error, 400).kind == kind


def _access(body: dict, status: int = 200):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v23.0/111"
        assert request.url.params["fields"] == "has_lead_access.app_id(1234567890)"
        return httpx.Response(status, json=body)

    return asyncio.run(_graph(handler).require_lead_access("111", "t"))


def test_a_business_using_leads_access_manager_must_allow_the_app() -> None:
    with pytest.raises(meta.MetaError) as caught:
        _access(
            {"has_lead_access": {"enabled_lead_access_manager": True, "can_access_lead": False}}
        )
    assert caught.value.kind == "lead_access" and "Leads Access Manager" in str(caught.value)


@pytest.mark.parametrize(
    "body, status",
    [
        ({"has_lead_access": {"enabled_lead_access_manager": True, "can_access_lead": True}}, 200),
        (
            {"has_lead_access": {"enabled_lead_access_manager": False, "can_access_lead": False}},
            200,
        ),
        ({"id": "111"}, 200),
        ({"error": {"code": 100, "message": "Unknown field"}}, 400),
    ],
)
def test_lead_access_that_meta_allows_or_doesnt_report_carries_on(body: dict, status: int) -> None:
    _access(body, status)


def test_a_lost_connection_is_not_hidden_by_the_lead_access_check() -> None:
    with pytest.raises(meta.MetaError) as caught:
        _access({"error": {"code": 190, "message": "expired"}}, 400)
    assert caught.value.kind == "token"


def test_meta_s_own_words_and_code_are_kept_for_managers() -> None:
    from ac_platform.lead_desk.connected_apps import meta_said

    error = meta.graph_error(
        {"code": 100, "error_subcode": 33, "message": "(#100) Unsupported post  request"}, 400
    )
    assert (error.code, error.subcode, error.detail) == (100, 33, "(#100) Unsupported post request")
    said = meta_said(error)
    assert said.startswith("Meta refused the request.")
    assert "Meta says: “(#100) Unsupported post request”" in said
    assert said.endswith("(code 100, subcode 33)")
    assert meta.graph_error({"code": 190, "message": "expired"}, 400).kind == "token"
