"""AI replies on PostgreSQL, with Meta and the model faked.

In auto mode a lead's WhatsApp or Messenger question about the business is answered
once, through the channel's own send, marked as an AI reply (which doesn't stop the
first-response clock), with the model, tokens and cost kept; a request for a person
is handed to the seller and the hand-off clears when the seller answers; STOP is the
person's recorded no and nothing automatic goes to them after; in suggest mode the
seller gets a draft and nothing is sent; a lead that leaves takes the drafts with it.
"""

from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import delete, func, select, update

from ac_platform.http.routes import RouteContext
from ac_platform.lead_desk.ai_replies import registry, rules, runner
from ac_platform.lead_desk.ai_replies.http import install_ai_replies_http
from ac_platform.lead_desk.models import (
    Lead,
    LeadAiReply,
    LeadDeskSettings,
    LeadEvent,
    LeadSocialAccount,
    LeadSocialMessage,
    LeadWhatsAppMessage,
    LeadWhatsAppNumber,
)
from ac_platform.lead_desk.social import graph
from ac_platform.lead_desk.store import LeadDesk, Viewer
from ac_platform.lead_desk.whatsapp import cloud
from ac_platform.lead_desk.whatsapp import inbox as wa_inbox
from ac_platform.lead_desk.whatsapp.http import install_whatsapp_http
from ac_platform.tenancy.models import Membership
from tests.database.test_conversation_postgresql import postgres_harness as _postgres_harness
from tests.database.test_conversation_postgresql import run
from tests.database.test_conversation_submission_http_postgresql import ORIGIN, _setup
from tests.database.test_lead_desk_postgresql import _organisation
from tests.database.test_lead_desk_social_postgresql import FakeGraph
from tests.database.test_lead_desk_whatsapp_postgresql import FakeCloud
from tests.unit.lead_desk_ai_replies.businesses import HOMES
from tests.unit.lead_desk_ai_replies.test_ai_reply_think import ScriptedModel
from tests.unit.lead_desk_whatsapp.test_whatsapp_cloud import ENV as WHATSAPP_ENV

WRITE = {"Origin": ORIGIN, "Content-Type": "application/json"}
BASE = "/v1/lead-desk"
ENV = {**WHATSAPP_ENV, "AC_MESSAGING_LOGIN_CONFIG_ID": "5550001"}
CALLER = "919876543210"
PSID = "2400000000000001"
PAGE = "100200300"


@pytest.fixture
def postgres_harness() -> Any:
    yield from cast(Any, _postgres_harness).__wrapped__()


def test_ai_replies_answer_hand_off_and_stop(
    postgres_harness: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for name, value in ENV.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(cloud, "Cloud", FakeCloud)
    monkeypatch.setattr(graph, "Graph", FakeGraph)
    FakeCloud.sent, FakeGraph.sent = [], []
    model = ScriptedModel()
    monkeypatch.setattr(registry, "model_for", lambda sessions: model)
    # The provider gate and key are Root's; here they are taken as cleared.
    monkeypatch.setattr(registry, "available", lambda **kwargs: (True, None))
    wa_cfg, social_cfg = cloud.config(), graph.config()
    assert wa_cfg is not None and social_cfg is not None

    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path)
        try:
            await _organisation(setup)
            settings = setup.settings.model_copy(update={"public_learner_tenant_id": uuid4()})
            context = RouteContext(settings, setup.require_actor, setup.sessions)
            install_ai_replies_http(setup.app, context)
            install_whatsapp_http(setup.app, context)
            tenant, me = setup.state.tenant_id, setup.state.person_id
            now = datetime.now(UTC)

            async with setup.sessions() as db, db.begin():
                db.add(
                    LeadDeskSettings(
                        tenant_id=tenant,
                        revision=1,
                        config={rules.KEY: rules.as_config(HOMES)},  # auto, Fictional Homes
                        updated_by_person_id=None,
                        updated_at=now,
                    )
                )
                number = LeadWhatsAppNumber(
                    id=uuid4(),
                    tenant_id=tenant,
                    waba_id="55500001",
                    phone_number_id="10001",
                    display_number="+91 80000 00000",
                    token=cloud.seal(
                        wa_cfg, "fake-business-token", phone_number_id="10001", what="token"
                    ),
                    status="active",
                    config={},
                    connected_by_person_id=me,
                    created_at=now,
                    updated_at=now,
                )
                page = LeadSocialAccount(
                    id=uuid4(),
                    tenant_id=tenant,
                    page_id=PAGE,
                    page_name="Fictional Homes",
                    token=graph.seal(social_cfg, "page-token", page_id=PAGE),
                    status="active",
                    config={},
                    connected_by_person_id=me,
                    created_at=now,
                    updated_at=now,
                )
                db.add_all([number, page])
                desk = LeadDesk(
                    db, Viewer(person_id=me, tenant_id=tenant, role="admin", name="Admin")
                )
                asha, _ = await desk.ingest(
                    {"name": "Asha Fictional", "phone": f"+{CALLER}"}, source="manual", actor=me
                )
                ravi, _ = await desk.ingest(
                    {"name": "Ravi Fictional", "messenger": PSID},
                    source="webhook",
                    source_ref=f"fb:{PAGE}:{PSID}",
                    actor=None,
                )
                assert asha is not None and ravi is not None
                await db.execute(
                    update(Lead).where(Lead.id.in_([asha.id, ravi.id])).values(owner_person_id=me)
                )
            ids = {"asha": asha.id, "ravi": ravi.id, "number": number.id, "page": page.id}

            async def whatsapp_in(text: str) -> UUID:
                async with setup.sessions() as db, db.begin():
                    row = LeadWhatsAppMessage(
                        id=uuid4(),
                        tenant_id=tenant,
                        number_id=ids["number"],
                        lead_id=ids["asha"],
                        wa_id=CALLER,
                        direction="in",
                        wamid=f"wamid.{uuid4().hex}",
                        kind="text",
                        body=text,
                        status="received",
                        meta_time=datetime.now(UTC),
                        created_at=datetime.now(UTC),
                    )
                    db.add(row)
                return row.id

            async def messenger_in(text: str) -> None:
                async with setup.sessions() as db, db.begin():
                    db.add(
                        LeadSocialMessage(
                            id=uuid4(),
                            tenant_id=tenant,
                            account_id=ids["page"],
                            lead_id=ids["ravi"],
                            channel="messenger",
                            user_id=PSID,
                            direction="in",
                            mid=f"m.{uuid4().hex}",
                            kind="text",
                            body=text,
                            status="received",
                            meta_time=datetime.now(UTC),
                            created_at=datetime.now(UTC),
                        )
                    )

            async def tick() -> dict[str, int]:
                async with httpx.AsyncClient() as client:
                    return await runner.auto_pass(
                        setup.sessions, model, client, None, now=datetime.now(UTC)
                    )

            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=setup.app), base_url=ORIGIN
            ) as http:
                http.cookies.set(setup.settings.session_cookie_name, setup.token)

                # ----- auto: a question about the business is answered once -----
                first = await whatsapp_in("Can I come for a site visit on Sunday?")
                done = await tick()
                assert (done["claimed"], done["sent"]) == (1, 1)
                assert (await tick())["claimed"] == 0  # one try per message
                assert FakeCloud.sent[-1] == {"to": CALLER, "text": "Yes, every day 10am to 7pm."}
                system, user = model.asked[-1]
                assert "Fictional Homes" in system and "site visit on Sunday" in user
                async with setup.sessions() as db:
                    reply = await db.scalar(
                        select(LeadAiReply).where(LeadAiReply.message_id == first)
                    )
                    assert reply is not None
                    assert (reply.mode, reply.outcome, reply.model, reply.input_tokens) == (
                        "auto",
                        "sent",
                        "fake-small",
                        420,
                    )
                    out = await db.scalar(
                        select(LeadWhatsAppMessage).where(
                            LeadWhatsAppMessage.id == reply.sent_message_id
                        )
                    )
                    assert (
                        out is not None and out.auto == "ai_reply" and out.sent_by_person_id is None
                    )
                    event = await db.scalar(
                        select(LeadEvent)
                        .where(LeadEvent.lead_id == ids["asha"], LeadEvent.kind == "message")
                        .order_by(LeadEvent.created_at.desc())
                    )
                    # Automatic: it doesn't stop the first-response clock.
                    assert event is not None and event.actor_person_id is None
                    assert event.data["auto"] == "ai_reply"

                # ----- they ask for a person: handed to the seller, no reply -----
                asked = len(model.asked)
                await whatsapp_in("Please call me, I want to talk to someone")
                assert (await tick())["handoff"] == 1
                assert len(model.asked) == asked and len(FakeCloud.sent) == 1
                state = (await http.get(f"{BASE}/leads/{ids['asha']}/ai")).json()
                assert state["mode"] == "auto" and state["ready"] is True
                assert [(h["channel"], h["reason"]) for h in state["handoffs"]] == [
                    ("whatsapp", "human")
                ]
                answered = await http.post(
                    f"{BASE}/leads/{ids['asha']}/whatsapp",
                    json={"commandId": str(uuid4()), "text": "Calling you now."},
                    headers=WRITE,
                )
                assert answered.status_code == 200, answered.text
                state = (await http.get(f"{BASE}/leads/{ids['asha']}/ai")).json()
                assert state["handoffs"] == []  # the seller answered

                # ----- STOP: their no, and nothing automatic after -----
                await whatsapp_in("STOP")
                assert (await tick())["stopped"] == 1
                async with setup.sessions() as db:
                    agreed, how = await wa_inbox.opt_in_state(
                        db, cast(Lead, await db.get(Lead, ids["asha"]))
                    )
                    assert agreed is False and how and "stop" in how
                await whatsapp_in("Is parking covered?")
                assert (await tick())["handoff"] == 1
                assert len(FakeCloud.sent) == 2  # only the seller's own reply went after

                # ----- Messenger, the same way -----
                await messenger_in("Parking milegi kya?")
                assert (await tick())["sent"] == 1
                assert (
                    FakeGraph.sent[-1]["to"] == PSID
                    and FakeGraph.sent[-1]["channel"] == "messenger"
                )

                # ----- suggest: a draft for the seller, nothing sent -----
                saved = await http.put(
                    f"{BASE}/ai-replies/settings",
                    json={**_view(HOMES), "mode": "suggest"},
                    headers=WRITE,
                )
                assert saved.status_code == 200, saved.text
                assert saved.json()["mode"] == "suggest" and saved.json()["ready"] is True
                await messenger_in("Is there a loan facility?")
                assert (await tick())["claimed"] == 0
                sent_before = len(FakeGraph.sent)
                draft = await http.post(
                    f"{BASE}/leads/{ids['ravi']}/ai-draft",
                    json={"channel": "messenger"},
                    headers=WRITE,
                )
                assert draft.status_code == 200, draft.text
                assert draft.json()["handoff"] is False and draft.json()["draft"]
                assert len(FakeGraph.sent) == sent_before
                await messenger_in("What is the price of a 3 BHK?")
                priced = (
                    await http.post(
                        f"{BASE}/leads/{ids['ravi']}/ai-draft",
                        json={"channel": "messenger"},
                        headers=WRITE,
                    )
                ).json()
                assert priced["handoff"] is True and priced["reason"] == "price"
                assert "price" in priced["words"]
                async with setup.sessions() as db:
                    suggested = await db.scalar(
                        select(func.count())
                        .select_from(LeadAiReply)
                        .where(
                            LeadAiReply.mode == "suggest", LeadAiReply.requested_by_person_id == me
                        )
                    )
                    assert suggested == 2

                off = await http.put(
                    f"{BASE}/ai-replies/settings",
                    json={**_view(HOMES), "mode": "off"},
                    headers=WRITE,
                )
                assert off.status_code == 200
                refused = await http.post(
                    f"{BASE}/leads/{ids['ravi']}/ai-draft",
                    json={"channel": "messenger"},
                    headers=WRITE,
                )
                assert refused.status_code == 409

                # ----- a lead that leaves takes the drafts -----
                async with setup.sessions() as db, db.begin():
                    await db.execute(delete(LeadEvent).where(LeadEvent.lead_id == ids["ravi"]))
                    await db.execute(delete(Lead).where(Lead.id == ids["ravi"]))
                async with setup.sessions() as db, db.begin():
                    from ac_platform.lead_desk.ai_replies import service

                    assert await service.erasure_sweep(db, datetime.now(UTC)) >= 1
                async with setup.sessions() as db:
                    left = await db.scalar(
                        select(func.count())
                        .select_from(LeadAiReply)
                        .where(LeadAiReply.lead_id == ids["ravi"], LeadAiReply.draft.is_not(None))
                    )
                    assert left == 0

                # ----- only managers set it up -----
                async with setup.sessions() as db, db.begin():
                    await db.execute(
                        update(Membership).where(Membership.person_id == me).values(role="member")
                    )
                assert (await http.get(f"{BASE}/ai-replies/settings")).status_code == 403
        finally:
            await setup.engine.dispose()

    run(exercise())


def _view(value: rules.Settings) -> dict[str, Any]:
    stored = rules.as_config(value)
    return {
        "mode": stored["mode"],
        "channels": stored["channels"],
        "quotePrices": stored["quote_prices"],
        "businessName": stored["business_name"],
        "about": stored["about"],
        "offerings": stored["offerings"],
        "faqs": stored["faqs"],
        "notes": stored["notes"],
    }
