"""WhatsApp in the Sales Xray CRM and the first-response SLA, on PostgreSQL with Meta faked.

An organisation connects its own number; a message from someone new becomes a lead for
the seller the rules pick; the seller replies inside the 24-hour window and only with
a template after it, and only to someone who agreed; statuses move forward only; an
ad lead who said yes on the form gets an instant first reply; a message after hours
gets the after-hours reply once; a lead nobody answers in time alerts the seller and
shows in the SLA report; a lead that leaves takes its words with it.
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
from ac_platform.lead_desk import sla
from ac_platform.lead_desk.models import (
    Lead,
    LeadDeskSettings,
    LeadDevice,
    LeadEvent,
    LeadSlaBreach,
    LeadWhatsAppMessage,
    LeadWhatsAppNumber,
)
from ac_platform.lead_desk.store import LeadDesk, Viewer
from ac_platform.lead_desk.whatsapp import cloud, inbox
from ac_platform.lead_desk.whatsapp.http import install_whatsapp_http
from tests.database.test_conversation_postgresql import postgres_harness as _postgres_harness
from tests.database.test_conversation_postgresql import run
from tests.database.test_conversation_submission_http_postgresql import ORIGIN, _setup
from tests.database.test_lead_desk_postgresql import _organisation
from tests.unit.lead_desk_whatsapp.test_whatsapp_cloud import ENV

WRITE = {"Origin": ORIGIN, "Content-Type": "application/json"}
BASE = "/v1/lead-desk"
NUMBER_ID = "10001"
WABA_ID = "55500001"
CALLER = "919876543210"  # a fictional person who writes in


@pytest.fixture
def postgres_harness() -> Any:
    yield from cast(Any, _postgres_harness).__wrapped__()


class FakeCloud:
    """Meta's Cloud API for one fictional business account."""

    sent: list[dict[str, Any]] = []
    templates_at_meta: list[dict[str, Any]] = []

    def __init__(
        self, cfg: cloud.WhatsAppConfig, client: Any = None, *, timeout: float = 15
    ) -> None:
        self.cfg = cfg

    async def exchange(self, code: str, *, redirect_uri: str | None = None) -> str:
        assert code == "signup-code"
        assert redirect_uri is None or redirect_uri.endswith("/v1/lead-desk/whatsapp/callback")
        return "fake-business-token"

    async def shared_accounts(self, token: str) -> list[str]:
        return [WABA_ID]

    async def phone_numbers(self, waba_id: str, token: str) -> list[str]:
        assert waba_id == WABA_ID
        return [NUMBER_ID]

    async def number(self, phone_number_id: str, token: str) -> dict[str, str]:
        return {
            "display_number": "+91 80000 00000",
            "verified_name": "Fictional Homes",
            "quality": "GREEN",
        }

    async def subscribe(self, waba_id: str, token: str) -> None:
        assert waba_id == WABA_ID

    async def register(self, phone_number_id: str, token: str, pin: str) -> None:
        assert len(pin) == 6

    async def send_text(self, phone_number_id: str, token: str, *, to: str, body: str) -> str:
        assert token == "fake-business-token"  # noqa: S105 - the fake's own token
        FakeCloud.sent.append({"to": to, "text": body})
        return f"wamid.OUT{len(FakeCloud.sent)}"

    async def send_template(
        self,
        phone_number_id: str,
        token: str,
        *,
        to: str,
        name: str,
        language: str,
        values: list[str],
    ) -> str:
        FakeCloud.sent.append({"to": to, "template": name, "language": language, "values": values})
        return f"wamid.OUT{len(FakeCloud.sent)}"

    async def templates(self, waba_id: str, token: str) -> list[dict[str, Any]]:
        return FakeCloud.templates_at_meta

    async def create_template(self, waba_id: str, token: str, **kwargs: Any) -> dict[str, Any]:
        FakeCloud.templates_at_meta.append(
            {
                "id": "77700009",
                "name": kwargs["name"],
                "language": kwargs["language"],
                "category": kwargs["category"],
                "status": "PENDING",
                "components": [{"type": "BODY", "text": kwargs["body"]}],
            }
        )
        return {"id": "77700009", "status": "PENDING", "category": kwargs["category"]}

    async def delete_template(self, waba_id: str, token: str, *, name: str) -> None:
        FakeCloud.templates_at_meta = [t for t in FakeCloud.templates_at_meta if t["name"] != name]


WELCOME = {
    "id": "77700001",
    "name": "welcome_lead",
    "language": "en",
    "category": "UTILITY",
    "status": "APPROVED",
    "components": [
        {"type": "BODY", "text": "Hi {{1}}, thanks for your enquiry. When can we call?"}
    ],
}
PENDING = {**WELCOME, "id": "77700002", "name": "site_visit", "status": "PENDING"}


def _signed(payload: dict[str, Any]) -> tuple[bytes, dict[str, str]]:
    body = json.dumps(payload).encode()
    signature = (
        "sha256="
        + hmac.new(ENV["AC_WHATSAPP_APP_SECRET"].encode(), body, hashlib.sha256).hexdigest()
    )
    return body, {"content-type": "application/json", "x-hub-signature-256": signature}


def _inbound(wamid: str, text: str, at: datetime, sender: str = CALLER) -> dict[str, Any]:
    return {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": WABA_ID,
                "changes": [
                    {
                        "field": "messages",
                        "value": {
                            "metadata": {"phone_number_id": NUMBER_ID},
                            "contacts": [{"profile": {"name": "Asha Patil"}, "wa_id": sender}],
                            "messages": [
                                {
                                    "from": sender,
                                    "id": wamid,
                                    "timestamp": str(int(at.timestamp())),
                                    "type": "text",
                                    "text": {"body": text},
                                }
                            ],
                        },
                    }
                ],
            }
        ],
    }


def _status(wamid: str, status: str, at: datetime) -> dict[str, Any]:
    payload = _inbound("unused", "", at)
    value = payload["entry"][0]["changes"][0]["value"]
    value["messages"] = []
    value["statuses"] = [{"id": wamid, "status": status, "timestamp": str(int(at.timestamp()))}]
    return payload


def test_whatsapp_conversations_from_connect_to_sla(
    postgres_harness: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for name, value in ENV.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(cloud, "Cloud", FakeCloud)
    FakeCloud.sent = []
    FakeCloud.templates_at_meta = [WELCOME, PENDING]
    cfg = cloud.config()
    assert cfg is not None

    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path)
        try:
            await _organisation(setup)
            settings = setup.settings.model_copy(update={"public_learner_tenant_id": uuid4()})
            install_whatsapp_http(
                setup.app, RouteContext(settings, setup.require_actor, setup.sessions)
            )
            tenant = setup.state.tenant_id
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=setup.app), base_url=ORIGIN
            ) as client:
                client.cookies.set(setup.settings.session_cookie_name, setup.token)

                # ----- connect the organisation's own number -----
                before = (await client.get(f"{BASE}/whatsapp/status")).json()
                assert before["configured"] is True and before["numbers"] == []
                assert before["configId"] == ENV["AC_WHATSAPP_CONFIG_ID"]
                # Connect WhatsApp: off to Meta's Embedded Signup and back.
                start = await client.get(f"{BASE}/whatsapp/start")
                assert start.status_code == 303
                dialog = start.headers["location"]
                assert dialog.startswith("https://www.facebook.com/v23.0/dialog/oauth?")
                assert f"config_id={ENV['AC_WHATSAPP_CONFIG_ID']}" in dialog
                state = parse_qs(urlparse(dialog).query)["state"][0]
                forged = await client.get(
                    f"{BASE}/whatsapp/callback", params={"code": "signup-code", "state": "x.y"}
                )
                assert forged.headers["location"].endswith("whatsapp=failed")
                back = await client.get(
                    f"{BASE}/whatsapp/callback", params={"code": "signup-code", "state": state}
                )
                assert back.status_code == 303, back.text
                assert back.headers["location"].endswith(
                    "/organisation?tab=integrations&whatsapp=connected"
                )
                # The page-side path (Embedded Signup's own code) lands on the same number.
                connected = await client.post(
                    f"{BASE}/whatsapp/connect",
                    json={"code": "signup-code", "wabaId": WABA_ID, "phoneNumberId": NUMBER_ID},
                    headers=WRITE,
                )
                assert connected.status_code == 200, connected.text
                status = connected.json()
                assert len(status["numbers"]) == 1
                assert status["numbers"][0]["displayNumber"] == "+91 80000 00000"
                assert {(t["name"], t["status"]) for t in status["templates"]} == {
                    ("welcome_lead", "APPROVED"),
                    ("site_visit", "PENDING"),
                }
                number_id = status["numbers"][0]["id"]
                async with setup.sessions() as db:
                    row = await db.scalar(select(LeadWhatsAppNumber))
                    assert row is not None and "fake-business-token" not in json.dumps(row.token)

                # ----- someone new writes in: a lead, shared out by the rules -----
                now = datetime.now(UTC)
                body, headers = _signed(_inbound("wamid.IN1", "Is the 3 BHK available?", now))
                bad = await client.post(
                    f"{BASE}/whatsapp/webhook",
                    content=body,
                    headers={**headers, "x-hub-signature-256": "sha256=00"},
                )
                assert bad.status_code == 401
                got = await client.post(f"{BASE}/whatsapp/webhook", content=body, headers=headers)
                assert got.status_code == 200 and got.json()["leads"] == 1, got.text
                again = await client.post(f"{BASE}/whatsapp/webhook", content=body, headers=headers)
                assert again.json()["messages"] == 0  # Meta's retry is the same message
                async with setup.sessions() as db:
                    lead = await db.scalar(select(Lead).where(Lead.phone == f"+{CALLER}"))
                    assert lead is not None and lead.name == "Asha Patil"
                    assert lead.owner_person_id == setup.state.person_id
                    assert lead.source_label == "WhatsApp · +91 80000 00000"
                lead_id = str(lead.id)

                chat = (await client.get(f"{BASE}/leads/{lead_id}/whatsapp")).json()
                assert [m["text"] for m in chat["messages"]] == ["Is the 3 BHK available?"]
                assert chat["windowOpen"] is True and chat["optedIn"] is True
                assert chat["optInHow"] == "They messaged you on WhatsApp"
                assert [t["name"] for t in chat["templates"]] == ["welcome_lead"]

                # ----- a reply inside the window, then statuses that only move on -----
                reply = await client.post(
                    f"{BASE}/leads/{lead_id}/whatsapp",
                    json={"commandId": str(uuid4()), "text": "Yes! When can I call you?"},
                    headers=WRITE,
                )
                assert reply.status_code == 200, reply.text
                assert FakeCloud.sent[-1] == {"to": CALLER, "text": "Yes! When can I call you?"}
                for state in ("read", "delivered"):
                    body, headers = _signed(_status("wamid.OUT1", state, now))
                    await client.post(f"{BASE}/whatsapp/webhook", content=body, headers=headers)
                chat = (await client.get(f"{BASE}/leads/{lead_id}/whatsapp")).json()
                out = [m for m in chat["messages"] if m["direction"] == "out"]
                assert out[0]["status"] == "read" and out[0]["by"]

                # ----- after 24 hours: a template only -----
                async with setup.sessions() as db, db.begin():
                    await db.execute(
                        update(LeadWhatsAppMessage)
                        .where(LeadWhatsAppMessage.direction == "in")
                        .values(meta_time=now - timedelta(hours=25))
                    )
                late = await client.post(
                    f"{BASE}/leads/{lead_id}/whatsapp",
                    json={"commandId": str(uuid4()), "text": "Hello again"},
                    headers=WRITE,
                )
                assert late.status_code == 409 and "template" in late.json()["detail"]
                short = await client.post(
                    f"{BASE}/leads/{lead_id}/whatsapp",
                    json={"commandId": str(uuid4()), "template": "welcome_lead", "language": "en"},
                    headers=WRITE,
                )
                assert short.status_code == 422  # its {{1}} is missing
                templated = await client.post(
                    f"{BASE}/leads/{lead_id}/whatsapp",
                    json={
                        "commandId": str(uuid4()),
                        "template": "welcome_lead",
                        "language": "en",
                        "values": ["Asha"],
                    },
                    headers=WRITE,
                )
                assert templated.status_code == 200, templated.text
                assert FakeCloud.sent[-1]["values"] == ["Asha"]
                shown = templated.json()["messages"][-1]
                assert shown["text"] == "Hi Asha, thanks for your enquiry. When can we call?"

                # ----- someone who never agreed gets nothing until the seller records a yes -----
                async with setup.sessions() as db, db.begin():
                    desk = LeadDesk(
                        db,
                        Viewer(
                            person_id=setup.state.person_id,
                            tenant_id=tenant,
                            role="admin",
                            name="A",
                        ),
                    )
                    quiet, _ = await desk.ingest(
                        {"name": "Ravi Kumar", "phone": "+919811100011"},
                        source="manual",
                        actor=setup.state.person_id,
                    )
                    assert quiet is not None
                    quiet_id = str(quiet.id)
                refused = await client.post(
                    f"{BASE}/leads/{quiet_id}/whatsapp",
                    json={
                        "commandId": str(uuid4()),
                        "template": "welcome_lead",
                        "language": "en",
                        "values": ["Ravi"],
                    },
                    headers=WRITE,
                )
                assert refused.status_code == 409 and "agreed" in refused.json()["detail"]
                agreed = await client.post(
                    f"{BASE}/leads/{quiet_id}/whatsapp/opt-in",
                    json={"commandId": str(uuid4()), "agreed": True, "how": "Said yes on the call"},
                    headers=WRITE,
                )
                assert agreed.json()["optedIn"] is True
                assert agreed.json()["optInHow"] == "Said yes on the call"
                allowed = await client.post(
                    f"{BASE}/leads/{quiet_id}/whatsapp",
                    json={
                        "commandId": str(uuid4()),
                        "template": "welcome_lead",
                        "language": "en",
                        "values": ["Ravi"],
                    },
                    headers=WRITE,
                )
                assert allowed.status_code == 200, allowed.text

                inbox_rows = (await client.get(f"{BASE}/whatsapp/inbox")).json()
                assert {row["leadName"] for row in inbox_rows} == {"Asha Patil", "Ravi Kumar"}
                # The Chats screen's fields: number, kind, direction, status, clock, owner.
                ravi = next(row for row in inbox_rows if row["leadName"] == "Ravi Kumar")
                assert (ravi["lastDirection"], ravi["lastKind"], ravi["lastStatus"]) == (
                    "out",
                    "template",
                    "sent",
                )
                assert ravi["waitingSince"] is None and ravi["accountId"] == number_id
                assert ravi["place"].startswith("WhatsApp · +")
                assert ravi["ownerId"] is None or ravi["ownerName"]
                chats = (await client.get(f"{BASE}/chats")).json()
                assert set(chats["sla"]) == {"on", "minutes"} and chats["generatedAt"]
                assert {t["leadName"] for t in chats["threads"]} == {"Asha Patil", "Ravi Kumar"}
                assert {t["channel"] for t in chats["threads"]} == {"whatsapp"}
                assert all(t["key"].startswith(f"whatsapp:{number_id}:") for t in chats["threads"])
                assert "919811100011" not in str([t["key"] for t in chats["threads"]])

                # ----- templates: create one for review, delete it -----
                made = await client.post(
                    f"{BASE}/whatsapp/numbers/{number_id}/templates",
                    json={
                        "name": "visit_reminder",
                        "language": "en",
                        "category": "UTILITY",
                        "body": "Hi {{1}}, see you at {{2}}.",
                        "example": ["Asha", "11 am"],
                    },
                    headers=WRITE,
                )
                assert made.status_code == 201, made.text
                assert ("visit_reminder", "PENDING") in {
                    (t["name"], t["status"]) for t in made.json()["templates"]
                }
                gone = await client.delete(
                    f"{BASE}/whatsapp/numbers/{number_id}/templates/visit_reminder",
                    headers=WRITE,
                )
                assert "visit_reminder" not in {t["name"] for t in gone.json()["templates"]}

                # ----- auto replies: first reply needs a consent question -----
                no_question = await client.put(
                    f"{BASE}/whatsapp/numbers/{number_id}/auto-replies",
                    json={"firstReply": {"on": True, "template": "welcome_lead", "language": "en"}},
                    headers=WRITE,
                )
                assert no_question.status_code == 422
                rules = await client.put(
                    f"{BASE}/whatsapp/numbers/{number_id}/auto-replies",
                    json={
                        "firstReply": {
                            "on": True,
                            "template": "welcome_lead",
                            "language": "en",
                            "consentQuestion": "ok_to_whatsapp?",
                        },
                        "outOfHours": {"on": True, "text": "Thanks! We'll reply when we open."},
                    },
                    headers=WRITE,
                )
                assert rules.status_code == 200, rules.text

            # A new ad lead who said yes, and one who didn't: only the first is greeted.
            async with setup.sessions() as db, db.begin():
                desk = LeadDesk(
                    db,
                    Viewer(
                        person_id=setup.state.person_id, tenant_id=tenant, role="system", name="S"
                    ),
                )
                for name, phone, answer in (
                    ("Meera Shah", "+919811100022", "Yes"),
                    ("Kiran Rao", "+919811100033", "No"),
                ):
                    await desk.ingest(
                        {
                            "field_data": [
                                {"name": "full_name", "values": [name]},
                                {"name": "phone_number", "values": [phone]},
                                {"name": "ok_to_whatsapp?", "values": [answer]},
                            ]
                        },
                        source="meta",
                        source_ref=f"{100000000000100 + len(phone)}{answer}",
                        actor=None,
                    )
            sent_before = len(FakeCloud.sent)
            async with setup.sessions() as db, db.begin():
                assert (
                    await inbox.first_replies(db, cfg, FakeCloud(cfg), now=datetime.now(UTC)) == 1
                )
            assert FakeCloud.sent[sent_before:] == [
                {
                    "to": "919811100022",
                    "template": "welcome_lead",
                    "language": "en",
                    "values": ["Meera"],
                }
            ]
            async with setup.sessions() as db, db.begin():
                assert (
                    await inbox.first_replies(db, cfg, FakeCloud(cfg), now=datetime.now(UTC)) == 0
                )

            # A message at night gets the after-hours reply, once.
            night = datetime(2027, 1, 18, 17, 0, tzinfo=UTC)  # 22:30 in India, a Monday
            async with setup.sessions() as db, db.begin():
                row = await db.get(LeadDeskSettings, tenant, with_for_update=True)
                if row is None:
                    row = LeadDeskSettings(
                        tenant_id=tenant, revision=1, config={}, updated_at=night
                    )
                    db.add(row)
                row.config = {
                    **(row.config or {}),
                    "work_hours": {
                        "days": [0, 1, 2, 3, 4],
                        "start": "09:00",
                        "end": "18:00",
                        "pause_leads": False,
                    },
                }
                number = await db.scalar(select(LeadWhatsAppNumber))
                assert number is not None
                db.add(
                    LeadWhatsAppMessage(
                        id=uuid4(),
                        tenant_id=tenant,
                        number_id=number.id,
                        lead_id=lead.id,
                        wa_id=CALLER,
                        direction="in",
                        wamid="wamid.NIGHT",
                        kind="text",
                        body="Are you open now?",
                        status="received",
                        meta_time=night - timedelta(minutes=2),
                        created_at=night - timedelta(minutes=2),
                    )
                )
            for expected in (1, 0):
                async with setup.sessions() as db, db.begin():
                    assert (
                        await inbox.out_of_hours_replies(db, cfg, FakeCloud(cfg), now=night)
                        == expected
                    )
            assert FakeCloud.sent[-1] == {"to": CALLER, "text": "Thanks! We'll reply when we open."}

            # ----- first-response SLA -----
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=setup.app), base_url=ORIGIN
            ) as client:
                client.cookies.set(setup.settings.session_cookie_name, setup.token)
                odd = await client.put(
                    f"{BASE}/sla", json={"on": True, "minutes": 7}, headers=WRITE
                )
                assert odd.status_code == 422
                saved = await client.put(
                    f"{BASE}/sla",
                    json={"on": True, "minutes": 5, "alertManagers": True},
                    headers=WRITE,
                )
                assert saved.status_code == 200 and saved.json()["minutes"] == 5
            async with setup.sessions() as db, db.begin():
                # Hours off for this part: the clock starts at arrival.
                row = await db.get(LeadDeskSettings, tenant, with_for_update=True)
                assert row is not None
                row.config = {k: v for k, v in (row.config or {}).items() if k != "work_hours"}
                db.add(
                    LeadDevice(
                        id=uuid4(),
                        tenant_id=tenant,
                        person_id=setup.state.person_id,
                        platform="android",
                        token="fcm-token-1",  # noqa: S106 - a fake phone address
                        token_sha256=hashlib.sha256(b"fcm-token-1").hexdigest(),
                        created_at=datetime.now(UTC),
                        last_seen_at=datetime.now(UTC),
                    )
                )
            later = datetime.now(UTC) + timedelta(minutes=6)
            async with setup.sessions() as db, db.begin():
                breaches = await sla.find_breaches(db, now=later)
            # Asha and Ravi heard from a person; Meera's only reply was automatic and
            # Kiran heard nothing: those two went past 5 minutes.
            async with setup.sessions() as db:
                waiting = {
                    lead.name
                    for lead in (
                        await db.scalars(
                            select(Lead).where(Lead.id.in_([b.lead_id for b in breaches]))
                        )
                    ).all()
                }
            assert waiting == {"Kiran Rao", "Meera Shah"}
            assert all(b.tokens == ["fcm-token-1"] for b in breaches)
            # Managers on a screen see the same two, the longest late first.
            async with setup.sessions() as db:
                late = await sla.late_now(db, tenant, now=later)
            assert {item.lead_name for item in late} == {"Kiran Rao", "Meera Shah"}
            assert all(item.minutes_late >= 1 for item in late)
            assert all(item.owner_person_id == setup.state.person_id for item in late)
            async with setup.sessions() as db, db.begin():
                assert await sla.find_breaches(db, now=later + timedelta(minutes=1)) == []
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=setup.app), base_url=ORIGIN
            ) as client:
                client.cookies.set(setup.settings.session_cookie_name, setup.token)
                report = (await client.get(f"{BASE}/reports/sla")).json()
                assert report["settings"]["minutes"] == 5
                assert report["late"] == []  # seen right now, nobody is past 5 minutes yet
                (seller,) = report["sellers"]
                # Seen right now, Meera and Kiran are still inside their 5 minutes.
                assert (
                    seller["leads"],
                    seller["inTime"],
                    seller["breached"],
                    seller["waiting"],
                ) == (4, 2, 0, 2)
                assert seller["medianMinutes"] == 0

            # ----- a lead that leaves takes its WhatsApp words with it -----
            async with setup.sessions() as db, db.begin():
                await db.execute(delete(LeadSlaBreach).where(LeadSlaBreach.lead_id == lead.id))
                await db.execute(delete(LeadEvent).where(LeadEvent.lead_id == lead.id))
                await db.execute(delete(Lead).where(Lead.id == lead.id))
            async with setup.sessions() as db, db.begin():
                assert await inbox.erasure_sweep(db, datetime.now(UTC)) >= 3
            async with setup.sessions() as db:
                left = await db.scalar(
                    select(func.count())
                    .select_from(LeadWhatsAppMessage)
                    .where(
                        LeadWhatsAppMessage.lead_id == lead.id,
                        LeadWhatsAppMessage.body.is_not(None),
                    )
                )
                assert left == 0
        finally:
            await setup.engine.dispose()

    run(exercise())
