"""Continue with Google: AC's Google Ads app, the accounts a person can reach, their lead forms."""

import asyncio
import base64
import json
from typing import Any
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import httpx
import pytest

from ac_platform.lead_desk.capture import extract
from ac_platform.lead_desk.connectors import google_ads
from ac_platform.lead_desk.connectors import google_ads_api as api

KEY = base64.urlsafe_b64encode(b"k" * 32).decode()
ENV = {
    "AC_GOOGLE_ADS_CLIENT_ID": "client-1.apps.googleusercontent.com",
    "AC_GOOGLE_ADS_CLIENT_SECRET": "client-secret",
    "AC_GOOGLE_ADS_DEVELOPER_TOKEN": "dev-token",
    "AC_LEAD_DESK_TOKEN_KEY": KEY,
}


def cfg() -> api.GoogleAdsConfig:
    value = api.config(ENV)
    assert value is not None
    return value


def ads(handler: Any) -> api.Ads:
    return api.Ads(cfg(), httpx.AsyncClient(transport=httpx.MockTransport(handler)))


@pytest.mark.parametrize("missing", sorted(ENV))
def test_the_connector_stays_off_until_every_setting_exists(missing: str) -> None:
    assert api.config({**ENV, missing: " "}) is None


def test_a_bad_token_key_keeps_it_off_and_the_version_can_move() -> None:
    assert api.config({**ENV, "AC_LEAD_DESK_TOKEN_KEY": "short"}) is None
    assert cfg().api == "https://googleads.googleapis.com/v25"
    moved = api.config({**ENV, "AC_GOOGLE_ADS_API_VERSION": "v26"})
    assert moved is not None and moved.api.endswith("/v26")


def test_sealed_secrets_open_only_for_their_account_and_kind() -> None:
    box = api.seal(cfg().token_key, "refresh-1", customer_id="111", what="token")
    assert "refresh-1" not in json.dumps(box)
    assert api.unseal(cfg().token_key, box, customer_id="111", what="token") == "refresh-1"
    for customer, what in (("222", "token"), ("111", "key")):
        with pytest.raises(api.GoogleAdsApiError):
            api.unseal(cfg().token_key, box, customer_id=customer, what=what)
    with pytest.raises(api.GoogleAdsApiError):
        api.unseal(cfg().token_key, None, customer_id="111", what="token")


def test_consent_asks_only_for_google_ads_with_lasting_access() -> None:
    url = api.consent_url(
        cfg(), redirect_uri="https://x.test/v1/lead-desk/google/callback", state="s"
    )
    query = parse_qs(urlsplit(url).query)
    assert url.startswith(api.AUTH)
    assert query["scope"] == [api.SCOPE]
    assert query["access_type"] == ["offline"] and query["prompt"] == ["consent"]
    assert query["client_id"] == [ENV["AC_GOOGLE_ADS_CLIENT_ID"]]


def test_the_state_must_come_back_to_the_same_person_and_workspace() -> None:
    tenant, person = uuid4(), uuid4()
    state = api.make_state(cfg(), tenant_id=tenant, person_id=person)
    api.read_state(cfg(), state, tenant_id=tenant, person_id=person)
    with pytest.raises(api.GoogleAdsApiError, match="Google"):
        api.read_state(cfg(), state, tenant_id=uuid4(), person_id=person)
    with pytest.raises(api.GoogleAdsApiError):
        api.read_state(cfg(), state + "x", tenant_id=tenant, person_id=person)


def test_the_code_becomes_a_refresh_token_and_a_lost_grant_says_connect_again() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        form = parse_qs(request.content.decode())
        if form["grant_type"] == ["authorization_code"]:
            return httpx.Response(
                200, json={"refresh_token": "r1", "access_token": "a", "scope": api.SCOPE}
            )
        return httpx.Response(400, json={"error": "invalid_grant"})

    client = ads(handler)
    assert asyncio.run(client.refresh_token(code="c", redirect_uri="https://x.test/cb")) == "r1"
    with pytest.raises(api.GoogleAdsApiError, match="Continue with Google again"):
        asyncio.run(client.access_token("r1"))


def test_without_lasting_access_the_sign_in_is_refused() -> None:
    client = ads(lambda request: httpx.Response(200, json={"access_token": "a"}))
    with pytest.raises(api.GoogleAdsApiError):
        asyncio.run(client.refresh_token(code="c", redirect_uri="https://x.test/cb"))


def test_accounts_include_those_under_a_manager_and_skip_managers() -> None:
    seen: list[tuple[str, str | None, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["developer-token"] == "dev-token"
        assert request.headers["authorization"] == "Bearer access-1"
        if request.url.path.endswith("customers:listAccessibleCustomers"):
            return httpx.Response(
                200, json={"resourceNames": ["customers/100", "customers/200", "customers/300"]}
            )
        customer = request.url.path.split("/")[3]
        seen.append(
            (
                customer,
                request.headers.get("login-customer-id"),
                json.loads(request.content)["query"],
            )
        )
        rows = {
            "100": [  # a manager with two client accounts
                {"customerClient": {"id": "100", "descriptiveName": "Agency MCC", "manager": True}},
                {"customerClient": {"id": "101", "descriptiveName": "Rao Solar", "manager": False}},
                {
                    "customerClient": {
                        "id": "200",
                        "descriptiveName": "Own (via MCC)",
                        "manager": False,
                    }
                },
            ],
            "200": [
                {"customerClient": {"id": "200", "descriptiveName": "Own", "testAccount": True}}
            ],
        }
        if customer == "300":
            return httpx.Response(403, json={"error": {"code": 403}})
        return httpx.Response(200, json={"results": rows[customer]})

    found = asyncio.run(ads(handler).accounts("access-1"))
    assert {a.customer_id: (a.name, a.login_customer_id, a.test) for a in found} == {
        "101": ("Rao Solar", "100", False),
        "200": ("Own", None, True),  # direct access wins over the manager path
    }
    assert all(login == customer for customer, login, _ in seen)
    assert "FROM customer_client" in seen[0][2]


def test_lead_forms_show_where_they_send_leads_now() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["login-customer-id"] == "100"
        assert "asset.type = 'LEAD_FORM'" in json.loads(request.content)["query"]
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "asset": {
                            "resourceName": "customers/101/assets/7",
                            "id": "7",
                            "name": "Solar quote",
                            "leadFormAsset": {
                                "deliveryMethods": [
                                    {
                                        "webhook": {
                                            "advertiserWebhookUrl": "https://hooks.zapier.com/x",
                                            "googleSecret": "z",
                                        }
                                    }
                                ]
                            },
                        }
                    },
                    {
                        "asset": {
                            "resourceName": "customers/101/assets/8",
                            "leadFormAsset": {"headline": "Book a visit"},
                        }
                    },
                ]
            },
        )

    account = api.Account("101", "Rao Solar", "100", False)
    forms = asyncio.run(ads(handler).lead_forms(account, "a"))
    assert [(f.form_id, f.name, f.webhook_url) for f in forms] == [
        ("7", "Solar quote", "https://hooks.zapier.com/x"),
        ("8", "Book a visit", None),
    ]


def test_someone_elses_webhook_is_kept_and_ours_is_set_or_left() -> None:
    url, key = "https://sx.test/v1/lead-desk/capture/s/google-ads", "k1"
    form = api.LeadForm("customers/1/assets/7", "7", "F", None, None)
    assert api.webhook_plan(form, url=url, key=key) == "set"
    assert api.webhook_plan(api.LeadForm("r", "7", "F", url, key), url=url, key=key) == "ok"
    assert api.webhook_plan(api.LeadForm("r", "7", "F", url, "old"), url=url, key=key) == "set"
    assert (
        api.webhook_plan(
            api.LeadForm("r", "7", "F", "https://hooks.zapier.com/x", "z"), url=url, key=key
        )
        == "other"
    )


def test_setting_the_webhook_changes_only_the_forms_delivery() -> None:
    sent: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v25/customers/101/assets:mutate"
        sent.append(json.loads(request.content))
        return httpx.Response(200, json={"results": [{"resourceName": "customers/101/assets/7"}]})

    account = api.Account("101", "Rao Solar", "100", False)
    form = api.LeadForm("customers/101/assets/7", "7", "F", None, None)
    asyncio.run(ads(handler).set_webhook(account, form, "a", url="https://sx.test/hook", key="k1"))
    (operation,) = sent[0]["operations"]
    assert operation["updateMask"] == "lead_form_asset.delivery_methods"
    hook = operation["update"]["leadFormAsset"]["deliveryMethods"][0]["webhook"]
    assert hook == {
        "advertiserWebhookUrl": "https://sx.test/hook",
        "googleSecret": "k1",
        "payloadSchemaVersion": "3",
    }
    assert set(operation["update"]) == {"resourceName", "leadFormAsset"}


@pytest.mark.parametrize(
    ("status", "body", "words"),
    [
        (
            403,
            {
                "error": {
                    "details": [
                        {
                            "errors": [
                                {
                                    "errorCode": {
                                        "authorizationError": "DEVELOPER_TOKEN_NOT_APPROVED"
                                    }
                                }
                            ]
                        }
                    ]
                }
            },
            "approved",
        ),
        (401, {"error": {"code": 401}}, "Continue with Google again"),
        (403, {"error": {"code": 403}}, "Ask its owner"),
        (429, {"error": {"code": 429}}, "slow down"),
        (500, {}, "Try again"),
    ],
)
def test_google_errors_become_plain_words(status: int, body: dict[str, Any], words: str) -> None:
    client = ads(lambda request: httpx.Response(status, json=body))
    with pytest.raises(api.GoogleAdsApiError, match=words):
        asyncio.run(client.search("101", "SELECT asset.id FROM asset", "a", login=None))


def test_no_answer_from_google_is_a_plain_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down")

    with pytest.raises(api.GoogleAdsApiError, match="didn't answer"):
        asyncio.run(ads(handler).search("101", "q", "a", login=None))


def test_search_follows_pages() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        token = json.loads(request.content).get("pageToken")
        if token is None:
            return httpx.Response(200, json={"results": [{"n": 1}], "nextPageToken": "p2"})
        return httpx.Response(200, json={"results": [{"n": 2}]})

    assert asyncio.run(ads(handler).search("101", "q", "a", login=None)) == [{"n": 1}, {"n": 2}]


SUBMISSION = {
    "leadFormSubmissionData": {
        "resourceName": "customers/101/leadFormSubmissionData/abc",
        "id": "abc",
        "asset": "customers/101/assets/7",
        "campaign": "customers/101/campaigns/22",
        "adGroup": "customers/101/adGroups/33",
        "gclid": "Cj0KCQ-click",
        "submissionDateTime": "2026-10-18 15:10:00+05:30",
        "leadFormSubmissionFields": [
            {"fieldType": "FULL_NAME", "fieldValue": "Asha Rao"},
            {"fieldType": "PHONE_NUMBER", "fieldValue": "+91 98765 43210"},
            {"fieldType": "CITY", "fieldValue": "Pune"},
        ],
        "customLeadFormSubmissionFields": [
            {"questionText": "What is your monthly bill?", "fieldValue": "4000"}
        ],
    }
}


def test_a_pulled_submission_reads_exactly_like_a_webhook_lead() -> None:
    record = google_ads.to_record(api.webhook_payload(SUBMISSION))
    found = extract(record)
    assert (found.name, found.phone, found.city) == ("Asha Rao", "+919876543210", "Pune")
    assert record["What is your monthly bill?"] == "4000"
    assert record["lead_id"] == "gclid:Cj0KCQ-click"
    assert record["google_ads"]["form_id"] == "7"
    assert record["google_ads"]["campaign_id"] == "22"
    assert record["google_ads"]["adgroup_id"] == "33"
    # The same lead by webhook carries the same click id, so it is filed once.
    webhook = {
        "lead_id": "other-id",
        "gcl_id": "Cj0KCQ-click",
        "user_column_data": [{"column_id": "FULL_NAME", "string_value": "Asha Rao"}],
    }
    assert google_ads.to_record(webhook)["lead_id"] == record["lead_id"]


def test_the_pull_reads_a_day_early_for_the_accounts_time_zone() -> None:
    since = 1_792_300_000  # 2026-10-18 05:06 UTC
    assert api.since_text(since) == "2026-10-17 00:00:00"
    queries: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        queries.append(json.loads(request.content)["query"])
        return httpx.Response(200, json={"results": [SUBMISSION]})

    account = api.Account("101", "Rao Solar", None, False)
    rows = asyncio.run(ads(handler).submissions(account, "a", since=since))
    assert rows[0]["gcl_id"] == "Cj0KCQ-click"
    assert "FROM lead_form_submission_data" in queries[0]
    assert ">= '2026-10-17 00:00:00'" in queries[0] and f"LIMIT {api.PULL_MAX}" in queries[0]


def test_only_continue_with_google_sources_count_as_the_connector() -> None:
    class Source:
        def __init__(self, kind: str, config: dict[str, Any]) -> None:
            self.kind, self.config = kind, config

    assert api.is_connector(Source("webhook", {"connector": "google_ads"}))
    assert not api.is_connector(Source("webhook", {}))
    assert not api.is_connector(Source("meta", {"connector": "google_ads"}))
