"""Messenger and Instagram in the Sales Xray CRM, on PostgreSQL with Meta faked.

An organisation connects its Page (and the Page's Instagram account); a message from
someone new becomes a lead with their name; the seller answers inside 24 hours, and
later only with the Human Agent tag when the organisation has it on (and never after
7 days); a comment with a rule's keyword gets one private reply and a public answer and
its writer becomes a lead, whose answer joins the same conversation; a first message
gets the instant first reply once; a message taken back loses its words; a lead that
leaves takes its words with it.
"""

import hashlib
import hmac
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast
from urllib.parse import parse_qs, urlparse
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import delete, func, select, update

from ac_platform.http.routes import RouteContext
from ac_platform.lead_desk.models import Lead, LeadEvent, LeadSocialAccount, LeadSocialMessage
from ac_platform.lead_desk.social import graph, inbox
from ac_platform.lead_desk.social.http import install_social_http
from tests.database.test_conversation_postgresql import postgres_harness as _postgres_harness
from tests.database.test_conversation_postgresql import run
from tests.database.test_conversation_submission_http_postgresql import ORIGIN, _setup
from tests.database.test_lead_desk_postgresql import _organisation
from tests.unit.lead_desk_social.test_social_graph import ENV, IG, IGSID, PAGE, PSID

WRITE = {"Origin": ORIGIN, "Content-Type": "application/json"}
BASE = "/v1/lead-desk"
COMMENTER = "2400000000000077"  # a fictional person's id on the Page's comment
ANSWERER = "2400000000000099"  # the same person's Messenger id after the private reply


@pytest.fixture
def postgres_harness() -> Any:
    yield from cast(Any, _postgres_harness).__wrapped__()


class FakeGraph:
    """Meta's Graph API for one fictional Page with an Instagram account."""

    sent: list[dict[str, Any]] = []
    public: list[dict[str, Any]] = []
    subscribed: list[str] = []

    def __init__(self, cfg: graph.SocialConfig, client: Any = None, *, timeout: float = 15) -> None:
        self.cfg = cfg

    async def user_token(self, *, code: str, redirect_uri: str) -> str:
        assert code == "login-code" and redirect_uri.endswith("/v1/lead-desk/messaging/callback")
        return "long-user-token"

    async def pages(self, user_token: str) -> list[graph.Page]:
        return [graph.Page(PAGE, "Fictional Homes", "page-token", IG, "fictional.homes")]

    async def subscribe(self, page_id: str, page_token: str) -> None:
        assert page_token == "page-token"  # noqa: S105 - the fake's own token
        FakeGraph.subscribed.append(page_id)

    async def profile(self, channel: str, user_id: str, page_token: str) -> str | None:
        return {PSID: "Asha Fictional", IGSID: "@fictional.buyer"}.get(user_id)

    async def send(
        self,
        page_id: str,
        page_token: str,
        *,
        user_id: str,
        text: str,
        channel: str,
        human_agent: bool = False,
    ) -> str:
        FakeGraph.sent.append(
            {"to": user_id, "text": text, "channel": channel, "human_agent": human_agent}
        )
        return f"m.out{len(FakeGraph.sent)}"

    async def private_reply(
        self, page_id: str, page_token: str, *, comment_id: str, text: str, channel: str
    ) -> tuple[str, str]:
        FakeGraph.sent.append({"comment": comment_id, "text": text, "channel": channel})
        return f"m.out{len(FakeGraph.sent)}", ANSWERER

    async def public_reply(
        self, page_token: str, *, comment_id: str, text: str, channel: str
    ) -> str:
        FakeGraph.public.append({"comment": comment_id, "text": text, "channel": channel})
        return "c.pub1"


def _signed(payload: dict[str, Any]) -> tuple[bytes, dict[str, str]]:
    body = json.dumps(payload).encode()
    signature = (
        "sha256="
        + hmac.new(ENV["AC_WHATSAPP_APP_SECRET"].encode(), body, hashlib.sha256).hexdigest()
    )
    return body, {"content-type": "application/json", "x-hub-signature-256": signature}


def _dm(obj: str, account: str, user: str, mid: str, text: str, **extra: Any) -> dict[str, Any]:
    message: dict[str, Any] = {"mid": mid, "text": text, **extra}
    return {
        "object": obj,
        "entry": [
            {
                "id": account,
                "messaging": [
                    {
                        "sender": {"id": user},
                        "recipient": {"id": account},
                        "timestamp": int(datetime.now(UTC).timestamp() * 1000),
                        "message": message,
                    }
                ],
            }
        ],
    }


def _comment(comment_id: str, text: str, user: str = COMMENTER) -> dict[str, Any]:
    return {
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
                            "comment_id": comment_id,
                            "post_id": f"{PAGE}_555",
                            "message": text,
                            "from": {"id": user, "name": "Ravi Fictional"},
                            "created_time": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S+0000"),
                        },
                    }
                ],
            }
        ],
    }


def test_messenger_and_instagram_conversations_and_comment_replies(
    postgres_harness: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for name, value in ENV.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(graph, "Graph", FakeGraph)
    FakeGraph.sent, FakeGraph.public, FakeGraph.subscribed = [], [], []
    cfg = graph.config()
    assert cfg is not None

    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path)
        try:
            await _organisation(setup)
            settings = setup.settings.model_copy(update={"public_learner_tenant_id": uuid4()})
            install_social_http(
                setup.app, RouteContext(settings, setup.require_actor, setup.sessions)
            )
            tenant = setup.state.tenant_id
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=setup.app), base_url=ORIGIN
            ) as client:
                client.cookies.set(setup.settings.session_cookie_name, setup.token)

                async def deliver(payload: dict[str, Any]) -> dict[str, int]:
                    body, headers = _signed(payload)
                    answer = await client.post(
                        f"{BASE}/messaging/webhook", content=body, headers=headers
                    )
                    assert answer.status_code == 200, answer.text
                    return cast(dict[str, int], answer.json())

                async def tick(work: Any) -> int:
                    async with setup.sessions() as db, db.begin():
                        return int(await work(db, cfg, FakeGraph(cfg), now=datetime.now(UTC)))

                # ----- connect the Page and its Instagram account -----
                before = (await client.get(f"{BASE}/messaging/status")).json()
                assert before == {"configured": True, "accounts": [], "taken": []}
                start = await client.get(f"{BASE}/messaging/connect")
                assert start.status_code == 303
                dialog = start.headers["location"]
                assert f"config_id={ENV['AC_MESSAGING_LOGIN_CONFIG_ID']}" in dialog
                state = parse_qs(urlparse(dialog).query)["state"][0]
                back = await client.get(
                    f"{BASE}/messaging/callback", params={"code": "login-code", "state": state}
                )
                assert back.status_code == 303, back.text
                assert back.headers["location"].endswith(
                    "/organisation?tab=integrations&messaging=connected"
                )
                assert FakeGraph.subscribed == [PAGE]
                status = (await client.get(f"{BASE}/messaging/status")).json()
                [page] = status["accounts"]
                assert (page["pageName"], page["igUsername"], page["hasInstagram"]) == (
                    "Fictional Homes",
                    "fictional.homes",
                    True,
                )
                async with setup.sessions() as db:
                    row = await db.scalar(select(LeadSocialAccount))
                    assert row is not None and "page-token" not in json.dumps(row.token)

                # ----- someone new writes on Messenger: a lead with their name -----
                bad = await client.post(
                    f"{BASE}/messaging/webhook",
                    content=b"{}",
                    headers={"content-type": "application/json", "x-hub-signature-256": "sha256=0"},
                )
                assert bad.status_code == 401
                first = _dm("page", PAGE, PSID, "m.in1", "Is the 3 BHK available?")
                assert await deliver(first) == {
                    "messages": 1,
                    "leads": 1,
                    "statuses": 0,
                    "comments": 0,
                    "unsent": 0,
                }
                assert (await deliver(first))["messages"] == 0  # Meta's retry is the same message
                async with setup.sessions() as db:
                    lead = await db.scalar(select(Lead).where(Lead.name == "Asha Fictional"))
                    assert lead is not None and lead.source_label == "Messenger · Fictional Homes"
                lead_id = lead.id

                chat = (await client.get(f"{BASE}/leads/{lead_id}/social")).json()
                [thread] = chat["threads"]
                assert (thread["channel"], thread["windowOpen"], thread["humanAgent"]) == (
                    "messenger",
                    True,
                    False,
                )
                assert [m["text"] for m in thread["messages"]] == ["Is the 3 BHK available?"]

                sent = await client.post(
                    f"{BASE}/leads/{lead_id}/social",
                    json={"commandId": str(uuid4()), "channel": "messenger", "text": "Yes, it is!"},
                    headers=WRITE,
                )
                assert sent.status_code == 200, sent.text
                assert sent.json()["threads"][0]["messages"][-1]["status"] == "sent"
                assert FakeGraph.sent[-1] == {
                    "to": PSID,
                    "text": "Yes, it is!",
                    "channel": "messenger",
                    "human_agent": False,
                }
                async with setup.sessions() as db:
                    event = await db.scalar(
                        select(LeadEvent).where(
                            LeadEvent.lead_id == lead_id, LeadEvent.kind == "message"
                        )
                    )
                    # A person answered: this stops the lead's first-response clock.
                    assert event is not None and event.actor_person_id == setup.state.person_id
                    assert event.data["channel"] == "messenger" and "Yes" not in json.dumps(
                        event.data
                    )
                # Delivered, then read: statuses only move forward.
                receipt = {
                    "object": "page",
                    "entry": [
                        {
                            "id": PAGE,
                            "messaging": [
                                {"sender": {"id": PSID}, "read": {"watermark": 4102444800000}},
                                {"sender": {"id": PSID}, "delivery": {"mids": ["m.out1"]}},
                            ],
                        }
                    ],
                }
                assert (await deliver(receipt))["statuses"] == 1

                # ----- after 24 hours: only a person, with the Human Agent tag -----
                async with setup.sessions() as db, db.begin():
                    await db.execute(
                        update(LeadSocialMessage)
                        .where(LeadSocialMessage.mid == "m.in1")
                        .values(meta_time=datetime.now(UTC) - timedelta(days=2))
                    )
                late = {"commandId": str(uuid4()), "channel": "messenger", "text": "Still keen?"}
                refused = await client.post(
                    f"{BASE}/leads/{lead_id}/social", json=late, headers=WRITE
                )
                assert refused.status_code == 409 and "24 hours" in refused.json()["detail"]
                page_settings = {**page["settings"], "humanAgent": True}
                saved = await client.put(
                    f"{BASE}/messaging/accounts/{page['id']}", json=page_settings, headers=WRITE
                )
                assert saved.status_code == 200, saved.text
                chat = (await client.get(f"{BASE}/leads/{lead_id}/social")).json()
                assert chat["threads"][0]["humanAgent"] is True
                tagged = await client.post(
                    f"{BASE}/leads/{lead_id}/social",
                    json={**late, "commandId": str(uuid4()), "humanAgent": True},
                    headers=WRITE,
                )
                assert tagged.status_code == 200, tagged.text
                assert FakeGraph.sent[-1]["human_agent"] is True
                async with setup.sessions() as db, db.begin():
                    await db.execute(
                        update(LeadSocialMessage)
                        .where(LeadSocialMessage.mid == "m.in1")
                        .values(meta_time=datetime.now(UTC) - timedelta(days=8))
                    )
                too_late = await client.post(
                    f"{BASE}/leads/{lead_id}/social",
                    json={**late, "commandId": str(uuid4()), "humanAgent": True},
                    headers=WRITE,
                )
                assert too_late.status_code == 409 and "7 days" in too_late.json()["detail"]

                # ----- Instagram: its own lead, under the Instagram account -----
                assert (await deliver(_dm("instagram", IG, IGSID, "ig.in1", "price?")))[
                    "leads"
                ] == 1
                async with setup.sessions() as db:
                    buyer = await db.scalar(select(Lead).where(Lead.name == "@fictional.buyer"))
                    assert buyer is not None
                    assert buyer.source_label == "Instagram · @fictional.homes"

                # ----- a comment with the rule's keyword: one private reply -----
                rules = {
                    **page_settings,
                    "comments": [
                        {
                            "keywords": ["price", "site visit"],
                            "reply": "Hi {first_name}, here are the prices.",
                            "publicReply": "We've sent you a message.",
                        }
                    ],
                    "firstReply": {
                        "on": True,
                        "text": "Thanks {first_name}, a seller will reply soon.",
                    },
                }
                saved = await client.put(
                    f"{BASE}/messaging/accounts/{page['id']}", json=rules, headers=WRITE
                )
                assert saved.status_code == 200, saved.text
                assert (await deliver(_comment("777_100", "Nice view")))["comments"] == 0
                async with setup.sessions() as db:
                    noted = await db.scalar(select(LeadSocialAccount))
                    assert noted is not None
                    # Settings → Connected apps can say why it got no reply.
                    assert noted.config[inbox.SKIP_KEY]["why"] == "no_rule"
                assert (await deliver(_comment("777_101", "PRICE please?"))) == {
                    "messages": 0,
                    "leads": 1,
                    "statuses": 0,
                    "comments": 1,
                    "unsent": 0,
                }
                assert (await deliver(_comment("777_101", "PRICE please?")))["comments"] == 0
                assert await tick(inbox.comment_replies) == 1
                assert await tick(inbox.comment_replies) == 0  # once per comment
                assert FakeGraph.sent[-1] == {
                    "comment": "777_101",
                    "text": "Hi Ravi, here are the prices.",
                    "channel": "messenger",
                }
                assert FakeGraph.public == [
                    {
                        "comment": "777_101",
                        "text": "We've sent you a message.",
                        "channel": "messenger",
                    }
                ]
                async with setup.sessions() as db:
                    commenter = await db.scalar(select(Lead).where(Lead.name == "Ravi Fictional"))
                    assert commenter is not None
                    states = (
                        await db.execute(
                            select(LeadSocialMessage.kind, LeadSocialMessage.reply_state).where(
                                LeadSocialMessage.lead_id == commenter.id
                            )
                        )
                    ).all()
                    assert sorted(states, key=str) == sorted(
                        [("comment", "replied"), ("text", None)], key=str
                    )
                # Their answer to the private reply joins the same lead, and opens the window.
                assert (await deliver(_dm("page", PAGE, ANSWERER, "m.in2", "Yes please")))[
                    "leads"
                ] == 0
                chat = (await client.get(f"{BASE}/leads/{commenter.id}/social")).json()
                assert any(t["windowOpen"] for t in chat["threads"])
                # They wrote after Sales Xray did, and Asha has an answer: of the recent
                # writers only the Instagram buyer, still unanswered, gets the first reply.
                assert await tick(inbox.first_replies) == 1
                assert FakeGraph.sent[-1] == {
                    "to": IGSID,
                    "text": "Thanks fictional.buyer, a seller will reply soon.",
                    "channel": "instagram",
                    "human_agent": False,
                }

                # ----- someone new: the instant first reply, once -----
                newcomer = "2400000000000055"
                await deliver(_dm("page", PAGE, newcomer, "m.in3", "hello"))
                await deliver(_dm("page", PAGE, newcomer, "m.in4", "anyone there?"))
                assert await tick(inbox.first_replies) == 1
                assert await tick(inbox.first_replies) == 0
                assert FakeGraph.sent[-1]["to"] == newcomer
                assert FakeGraph.sent[-1]["text"] == "Thanks there, a seller will reply soon."
                async with setup.sessions() as db:
                    auto = await db.scalar(
                        select(LeadEvent).where(
                            LeadEvent.kind == "message", LeadEvent.actor_person_id.is_(None)
                        )
                    )
                    # An automation's reply doesn't stop anyone's first-response clock.
                    assert auto is not None and auto.data["auto"] in (
                        "first_reply",
                        "comment_reply",
                    )

                # ----- taking a message back removes its words -----
                taken = _dm("page", PAGE, newcomer, "m.in4", "")
                taken["entry"][0]["messaging"][0]["message"] = {"mid": "m.in4", "is_deleted": True}
                assert (await deliver(taken))["unsent"] == 1

                inbox_view = (await client.get(f"{BASE}/social/inbox")).json()
                assert {item["channel"] for item in inbox_view} == {"messenger", "instagram"}
                assert len(inbox_view) >= 4

                # ----- a lead that leaves takes its words -----
                async with setup.sessions() as db, db.begin():
                    await db.execute(delete(LeadEvent).where(LeadEvent.lead_id == lead_id))
                    await db.execute(delete(Lead).where(Lead.id == lead_id))
                async with setup.sessions() as db, db.begin():
                    assert await inbox.erasure_sweep(db, datetime.now(UTC)) >= 3
                async with setup.sessions() as db:
                    left = await db.scalar(
                        select(func.count())
                        .select_from(LeadSocialMessage)
                        .where(
                            LeadSocialMessage.tenant_id == tenant,
                            LeadSocialMessage.lead_id == lead_id,
                            LeadSocialMessage.body.is_not(None),
                        )
                    )
                    assert left == 0

                disconnected = await client.post(
                    f"{BASE}/messaging/accounts/{page['id']}/disconnect", headers=WRITE
                )
                assert disconnected.json()["accounts"] == []
                # A disconnected Page's messages no longer come in.
                assert (await deliver(_dm("page", PAGE, PSID, "m.in9", "hello?")))["messages"] == 0
        finally:
            await setup.engine.dispose()

    run(exercise())
