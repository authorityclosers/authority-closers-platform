"""Messenger and Instagram for the CRM: AC's Messaging app, Meta's webhook, the Graph calls."""

import asyncio
import base64
import json
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest

from ac_platform.lead_desk.social import graph

KEY = base64.urlsafe_b64encode(b"k" * 32).decode()
ENV = {
    "AC_WHATSAPP_APP_ID": "1234500001",
    "AC_WHATSAPP_APP_SECRET": "messaging-secret",
    "AC_WHATSAPP_WEBHOOK_VERIFY_TOKEN": "verify-me",
    "AC_MESSAGING_LOGIN_CONFIG_ID": "5550001",
    "AC_LEAD_DESK_TOKEN_KEY": KEY,
}
PAGE = "100200300"
IG = "17841400000001"
PSID = "2400000000000001"
IGSID = "3400000000000001"


def cfg() -> graph.SocialConfig:
    value = graph.config(ENV)
    assert value is not None
    return value


@pytest.mark.parametrize("missing", sorted(ENV))
def test_the_channel_stays_off_until_every_setting_exists(missing: str) -> None:
    assert graph.config({**ENV, missing: " "}) is None


def test_it_needs_no_whatsapp_signup_configuration_and_follows_its_graph_version() -> None:
    assert "AC_WHATSAPP_CONFIG_ID" not in ENV
    assert cfg().graph == "https://graph.facebook.com/v23.0"
    moved = graph.config({**ENV, "AC_WHATSAPP_GRAPH_VERSION": "v24.0"})
    assert moved is not None and moved.graph.endswith("/v24.0")


def test_a_page_token_opens_only_for_its_page() -> None:
    box = graph.seal(cfg(), "page-token", page_id=PAGE)
    assert "page-token" not in json.dumps(box)
    assert graph.unseal(cfg(), box, page_id=PAGE) == "page-token"
    with pytest.raises(graph.SocialError, match="Connect this Page again"):
        graph.unseal(cfg(), box, page_id="100200399")


def test_login_asks_for_the_messaging_configuration() -> None:
    url = graph.dialog_url(cfg(), redirect_uri="https://x.test/cb", state="s")
    query = parse_qs(urlsplit(url).query)
    assert url.startswith("https://www.facebook.com/v23.0/dialog/oauth?")
    assert query["config_id"] == ["5550001"] and query["client_id"] == ["1234500001"]
    assert query["response_type"] == ["code"] and query["redirect_uri"] == ["https://x.test/cb"]


def test_the_windows() -> None:
    now = datetime(2026, 10, 19, 12, tzinfo=UTC)
    assert graph.window_open(now - timedelta(hours=23), now)
    assert not graph.window_open(now - timedelta(hours=25), now)
    assert not graph.window_open(None, now)
    assert graph.human_agent_open(now - timedelta(days=6), now)
    assert not graph.human_agent_open(now - timedelta(days=8), now)


def _messaging(obj: str, account: str, events: list[dict[str, Any]]) -> dict[str, Any]:
    return {"object": obj, "entry": [{"id": account, "time": 1, "messaging": events}]}


def test_messenger_messages_echoes_receipts_and_take_backs() -> None:
    at = 1792440000000
    delivery = graph.parse(
        _messaging(
            "page",
            PAGE,
            [
                {
                    "sender": {"id": PSID},
                    "recipient": {"id": PAGE},
                    "timestamp": at,
                    "message": {"mid": "m.1", "text": "Is the 3 BHK still available?"},
                },
                {
                    "sender": {"id": PSID},
                    "recipient": {"id": PAGE},
                    "timestamp": at,
                    "message": {"mid": "m.2", "attachments": [{"type": "image", "payload": {}}]},
                },
                {
                    "sender": {"id": PAGE},
                    "recipient": {"id": PSID},
                    "timestamp": at,
                    "message": {"mid": "m.3", "text": "Yes!", "is_echo": True, "app_id": 99},
                },
                {
                    "sender": {"id": PSID},
                    "recipient": {"id": PAGE},
                    "delivery": {"mids": ["m.3"], "watermark": at},
                },
                {"sender": {"id": PSID}, "recipient": {"id": PAGE}, "read": {"watermark": at}},
                {
                    "sender": {"id": PSID},
                    "recipient": {"id": PAGE},
                    "timestamp": at,
                    "postback": {"title": "Book a visit", "payload": "VISIT", "mid": "m.4"},
                },
                {
                    "sender": {"id": PSID},
                    "recipient": {"id": PAGE},
                    "timestamp": at,
                    "message": {"mid": "m.1", "is_deleted": True},
                },
                {"sender": {"id": "not-an-id"}, "message": {"mid": "m.9", "text": "x"}},
            ],
        )
    )
    assert [(m.channel, m.user_id, m.mid, m.kind, m.body) for m in delivery.inbound] == [
        ("messenger", PSID, "m.1", "text", "Is the 3 BHK still available?"),
        ("messenger", PSID, "m.2", "image", None),
        ("messenger", PSID, "m.4", "postback", "Book a visit"),
    ]
    assert delivery.inbound[0].at == datetime.fromtimestamp(at / 1000, UTC)
    assert [(e.user_id, e.mid, e.body, e.app_id) for e in delivery.echoes] == [
        (PSID, "m.3", "Yes!", "99")
    ]
    assert [(s.status, s.mids) for s in delivery.seen] == [
        ("delivered", ("m.3",)),
        ("read", ()),
    ]
    assert delivery.unsent == ["m.1"]


def test_instagram_messages_come_under_the_instagram_account() -> None:
    delivery = graph.parse(
        _messaging(
            "instagram",
            IG,
            [
                {
                    "sender": {"id": IGSID},
                    "recipient": {"id": IG},
                    "timestamp": 1792440000000,
                    "message": {"mid": "ig.1", "text": "price?"},
                },
                {
                    "sender": {"id": IGSID},
                    "recipient": {"id": IG},
                    "timestamp": 1792440000000,
                    "message": {"mid": "ig.2", "reply_to": {"story": {"id": "1"}}},
                },
            ],
        )
    )
    assert [(m.channel, m.account_id, m.user_id, m.kind) for m in delivery.inbound] == [
        ("instagram", IG, IGSID, "text"),
        ("instagram", IG, IGSID, "story_reply"),
    ]
    assert graph.parse({"object": "whatsapp_business_account", "entry": []}).inbound == []


def test_comments_on_the_page_and_on_instagram_media() -> None:
    page = graph.parse(
        {
            "object": "page",
            "entry": [
                {
                    "id": PAGE,
                    "changes": [
                        {
                            "field": "feed",
                            "value": {
                                "item": "comment",
                                "verb": "add",
                                "comment_id": "777_888",
                                "post_id": f"{PAGE}_555",
                                "message": "PRICE please",
                                "from": {"id": PSID, "name": "Asha Fictional"},
                                "created_time": "2026-10-19T10:00:00+0000",
                            },
                        },
                        {
                            "field": "feed",
                            "value": {
                                "item": "comment",
                                "verb": "add",
                                "comment_id": "777_889",
                                "from": {"id": PAGE, "name": "The Page itself"},
                            },
                        },
                        {"field": "feed", "value": {"item": "reaction", "verb": "add"}},
                    ],
                }
            ],
        }
    )
    assert [(c.channel, c.comment_id, c.user_id, c.user_name, c.text) for c in page.comments] == [
        ("messenger", "777_888", PSID, "Asha Fictional", "PRICE please")
    ]
    assert page.comments[0].at == datetime(2026, 10, 19, 10, tzinfo=UTC)
    insta = graph.parse(
        {
            "object": "instagram",
            "entry": [
                {
                    "id": IG,
                    "changes": [
                        {
                            "field": "comments",
                            "value": {
                                "id": "18000000000000001",
                                "text": "details",
                                "from": {"id": IGSID, "username": "fictional.buyer"},
                                "media": {"id": "18000000000000009", "media_product_type": "FEED"},
                            },
                        }
                    ],
                }
            ],
        }
    )
    assert [(c.channel, c.user_name, c.post_id) for c in insta.comments] == [
        ("instagram", "@fictional.buyer", "18000000000000009")
    ]


def test_a_rule_matches_its_keywords_as_words() -> None:
    assert graph.matches(["price"], "What's the PRICE?")
    assert graph.matches(["site visit"], "Can I book a site visit tomorrow")
    assert not graph.matches(["price"], "priceless view")
    assert not graph.matches(["", " "], "anything")
    assert not graph.matches(["price"], None)
    assert graph.fill("Hi {first_name}, sent!", "@fictional.buyer") == "Hi fictional.buyer, sent!"
    assert graph.fill("Hi {first_name}", None) == "Hi there"


def test_refusals_in_plain_words() -> None:
    assert "24 hours" in str(graph.refusal({"code": 10, "error_subcode": 2018278}))
    assert "24 hours" in str(graph.refusal({"code": 100, "error_subcode": 2018278}))
    assert "Connect the Page again" in str(graph.refusal({"code": 190}))
    assert "limiting" in str(graph.refusal({"code": 613}))
    assert "can't get messages" in str(graph.refusal({"code": 551}))
    assert "permission" in str(graph.refusal({"code": 200}))
    assert str(graph.refusal({})) == "Meta refused the message. Try again."


def _graph(handler: Any) -> graph.Graph:
    return graph.Graph(cfg(), httpx.AsyncClient(transport=httpx.MockTransport(handler)))


def test_sending_answers_or_uses_the_human_agent_tag() -> None:
    seen: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == f"/v23.0/{PAGE}/messages"
        assert request.headers["authorization"] == "Bearer page-token"
        seen.append(json.loads(request.content))
        return httpx.Response(200, json={"recipient_id": PSID, "message_id": "m.out"})

    api = _graph(handler)
    assert (
        asyncio.run(api.send(PAGE, "page-token", user_id=PSID, text="Hello", channel="messenger"))
        == "m.out"
    )
    asyncio.run(
        api.send(
            PAGE,
            "page-token",
            user_id=IGSID,
            text="x" * 1500,
            channel="instagram",
            human_agent=True,
        )
    )
    assert seen[0] == {
        "recipient": {"id": PSID},
        "message": {"text": "Hello"},
        "messaging_type": "RESPONSE",
    }
    assert seen[1]["messaging_type"] == "MESSAGE_TAG" and seen[1]["tag"] == "HUMAN_AGENT"
    assert len(seen[1]["message"]["text"]) == 1000  # Instagram's limit


def test_a_comment_gets_a_private_and_a_public_reply() -> None:
    paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        body = json.loads(request.content)
        if request.url.path.endswith("/messages"):
            assert body["recipient"] == {"comment_id": "777_888"}
            return httpx.Response(200, json={"recipient_id": PSID, "message_id": "m.priv"})
        assert body == {"message": "Sent you a message"}
        return httpx.Response(200, json={"id": "c.pub"})

    api = _graph(handler)
    assert asyncio.run(
        api.private_reply(PAGE, "t", comment_id="777_888", text="Hi", channel="messenger")
    ) == ("m.priv", PSID)
    asyncio.run(
        api.public_reply("t", comment_id="777_888", text="Sent you a message", channel="messenger")
    )
    asyncio.run(
        api.public_reply("t", comment_id="18000001", text="Sent you a message", channel="instagram")
    )
    assert paths == [
        f"/v23.0/{PAGE}/messages",
        "/v23.0/777_888/comments",
        "/v23.0/18000001/replies",
    ]


def test_connecting_reads_pages_with_instagram_and_subscribes_them() -> None:
    calls: list[tuple[str, dict[str, str]]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        query = {key: values[0] for key, values in parse_qs(request.url.query.decode()).items()}
        calls.append((request.url.path, query))
        if request.url.path.endswith("oauth/access_token"):
            token = "long" if query.get("grant_type") == "fb_exchange_token" else "short"
            return httpx.Response(200, json={"access_token": token})
        if request.url.path.endswith("me/accounts"):
            assert request.headers["authorization"] == "Bearer long"
            if "after" not in query:
                return httpx.Response(
                    200,
                    json={
                        "data": [
                            {
                                "id": PAGE,
                                "name": "Fictional Homes",
                                "access_token": "pt1",
                                "instagram_business_account": {"id": IG, "username": "fictional"},
                            }
                        ],
                        "paging": {"next": "x", "cursors": {"after": "A"}},
                    },
                )
            return httpx.Response(
                200, json={"data": [{"id": "100200301", "name": "Second", "access_token": "pt2"}]}
            )
        assert request.url.path == f"/v23.0/{PAGE}/subscribed_apps"
        return httpx.Response(200, json={"success": True})

    api = _graph(handler)
    assert asyncio.run(api.user_token(code="c", redirect_uri="https://x.test/cb")) == "long"
    pages = asyncio.run(api.pages("long"))
    assert [(p.page_id, p.name, p.ig_user_id, p.ig_username) for p in pages] == [
        (PAGE, "Fictional Homes", IG, "fictional"),
        ("100200301", "Second", None, None),
    ]
    asyncio.run(api.subscribe(PAGE, "pt1"))
    subscribed = calls[-1][1]["subscribed_fields"].split(",")
    assert {"messages", "message_echoes", "message_reads", "feed"} <= set(subscribed)


def test_a_refused_call_raises_plain_words() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": {"code": 10, "error_subcode": 2018278}})

    with pytest.raises(graph.SocialError, match="24 hours"):
        asyncio.run(_graph(handler).send(PAGE, "t", user_id=PSID, text="late", channel="messenger"))
