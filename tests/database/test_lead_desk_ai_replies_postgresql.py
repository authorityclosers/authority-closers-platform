"""AI replies on PostgreSQL, with Meta and the model faked.

Nothing happens while Admin has AI replies switched off. Once on: in auto mode a lead's
WhatsApp or Messenger question about the business is queued by the API, answered by
the AI replies runner (the only part that asks a model), and sent once by the API
through the channel's own send, marked as an AI reply (which doesn't stop the
first-response clock), with the model, tokens and cost kept. What the rules settle
needs no model: a request for a person is handed to the seller (the hand-off clears
when the seller answers), and STOP is the person's recorded no, with nothing automatic
after. At Admin's cap automatic replies wait for budget and suggestions pause, until
"Raise and resume". In suggest mode the seller gets a draft and nothing is sent. A lead
that leaves takes the drafts with it. Every Admin change is audited.
"""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import delete, func, select, update

from ac_platform.audit.models import AuditEvent
from ac_platform.http.routes import RouteContext
from ac_platform.lead_desk.ai_replies import admin_http, cli, rules, runner
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
ADMIN = "/v1/admin/lead-desk-ai"
ENV = {**WHATSAPP_ENV, "AC_MESSAGING_LOGIN_CONFIG_ID": "5550001"}
CALLER = "919876543210"
PSID = "2400000000000001"
PAGE = "100200300"


@pytest.fixture
def postgres_harness() -> Any:
    yield from cast(Any, _postgres_harness).__wrapped__()


class _Admitted:
    """The operations-control check (its own tests cover it); here everyone is staff."""

    def __init__(self, application: Any) -> None:
        pass

    async def admit(self, actor: Any) -> None:
        return None


def test_ai_replies_answer_hand_off_stop_and_wait_for_budget(
    postgres_harness: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for name, value in ENV.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(cloud, "Cloud", FakeCloud)
    monkeypatch.setattr(graph, "Graph", FakeGraph)
    monkeypatch.setattr(admin_http, "ConversationProviderAdmin", _Admitted)
    monkeypatch.setattr(admin_http, "require_admin_surface", lambda request, settings: None)
    FakeCloud.sent, FakeGraph.sent = [], []
    model = ScriptedModel()
    wa_cfg, social_cfg = cloud.config(), graph.config()
    assert wa_cfg is not None and social_cfg is not None

    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path)
        try:
            await _organisation(setup)
            tenant, me = setup.state.tenant_id, setup.state.person_id
            settings = setup.settings.model_copy(update={"public_learner_tenant_id": uuid4()})
            context = RouteContext(settings, setup.require_actor, setup.sessions)
            install_ai_replies_http(setup.app, context)
            install_whatsapp_http(setup.app, context)
            # Admin answers to the operations workspace; here that is the test's own.
            staff = RouteContext(
                settings.model_copy(update={"operations_tenant_id": tenant}),
                setup.require_actor,
                setup.sessions,
            )
            admin_http.install_ai_replies_admin_http(setup.app, staff)
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

            async def messenger_in(text: str) -> UUID:
                async with setup.sessions() as db, db.begin():
                    row = LeadSocialMessage(
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
                    db.add(row)
                return row.id

            lines: list[dict[str, Any]] = []

            async def think() -> None:
                lines.extend(
                    await cli.thinking_pass(
                        setup.sessions, lambda config: model, now=datetime.now(UTC)
                    )
                )

            async def tick() -> dict[str, int]:
                """The API claims, the runner answers, the API acts."""
                async with httpx.AsyncClient() as client:
                    first = await runner.tick(setup.sessions, client, None, now=datetime.now(UTC))
                    await think()
                    second = await runner.tick(setup.sessions, client, None, now=datetime.now(UTC))
                return {
                    key: first.get(key, 0) + second.get(key, 0)
                    for key in ("claimed", "sent", "handoff", "stopped", "failed")
                }

            async def outcome(message_id: UUID) -> LeadAiReply:
                async with setup.sessions() as db:
                    row = await db.scalar(
                        select(LeadAiReply).where(LeadAiReply.message_id == message_id)
                    )
                assert row is not None
                return row

            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=setup.app), base_url=ORIGIN
            ) as http:
                http.cookies.set(setup.settings.session_cookie_name, setup.token)

                # ----- switched off in Admin (the start): nothing is asked or queued -----
                admin = (await http.get(ADMIN)).json()
                assert admin["config"]["enabled"] is False and admin["revision"] is None
                assert admin["config"]["cap_inr"] == 100 and admin["presets_inr"] == [100, 300, 400]
                assert admin["provider_label"] == "Google Gemini"
                assert "GEMINI" not in str(admin)  # the key is never named or shown
                first = await whatsapp_in("Can I come for a site visit on Sunday?")
                assert (await tick())["claimed"] == 0
                assert lines[-1] == {"stopped": "lead_desk_ai_off"}
                state = (await http.get(f"{BASE}/leads/{ids['asha']}/ai")).json()
                assert state["available"] is False
                refused = await http.post(
                    f"{BASE}/leads/{ids['asha']}/ai-draft",
                    json={"channel": "whatsapp"},
                    headers=WRITE,
                )
                assert refused.status_code == 409

                on = await http.put(
                    f"{ADMIN}/settings",
                    json={
                        "expected_revision": None,
                        "config": {**admin["config"], "enabled": True},
                    },
                    headers=WRITE,
                )
                assert on.status_code == 200, on.text
                assert on.json()["revision"] == 1 and on.json()["config"]["enabled"] is True
                stale = await http.put(
                    f"{ADMIN}/settings",
                    json={"expected_revision": None, "config": admin["config"]},
                    headers=WRITE,
                )
                assert stale.status_code == 409  # someone changed them meanwhile

                # ----- Try it: a draft for a sample message, nothing sent -----
                tried = await http.post(
                    f"{BASE}/ai-replies/try",
                    json={"message": "Are site visits possible on Sunday?"},
                    headers=WRITE,
                )
                assert tried.status_code == 200, tried.text
                assert tried.json()["status"] == "queued"
                status = f"{BASE}/ai-replies/try/{tried.json()['replyId']}"
                await think()
                done_try = (await http.get(status)).json()
                assert done_try["status"] == "drafted" and done_try["draft"]
                assert "Are site visits possible on Sunday?" in model.asked[-1][1]
                assert FakeCloud.sent == [] and FakeGraph.sent == []
                stop_try = (
                    await http.post(
                        f"{BASE}/ai-replies/try", json={"message": "STOP"}, headers=WRITE
                    )
                ).json()
                # Settled by the rules at once; a sample records nobody's stop.
                assert (stop_try["status"], stop_try["reason"]) == ("handoff", "opt_out")
                async with setup.sessions() as db, db.begin():
                    await db.execute(
                        update(LeadAiReply)
                        .where(LeadAiReply.mode == "try")
                        .values(created_at=datetime.now(UTC) - timedelta(days=2))
                    )
                async with setup.sessions() as db, db.begin():
                    from ac_platform.lead_desk.ai_replies import service as ai_service

                    assert await ai_service.erasure_sweep(db, datetime.now(UTC)) == 2
                async with setup.sessions() as db:
                    kept = await db.scalar(
                        select(func.count())
                        .select_from(LeadAiReply)
                        .where(LeadAiReply.mode == "try", LeadAiReply.sample.is_not(None))
                    )
                    assert kept == 0  # samples and drafts emptied after a day

                # ----- auto: a question about the business is answered once -----
                done = await tick()
                assert (done["claimed"], done["sent"]) == (1, 1)
                assert (await tick())["claimed"] == 0  # one try per message
                assert FakeCloud.sent[-1] == {"to": CALLER, "text": "Yes, every day 10am to 7pm."}
                system, user = model.asked[-1]
                assert "Fictional Homes" in system and "site visit on Sunday" in user
                reply = await outcome(first)
                assert (reply.mode, reply.outcome, reply.model, reply.input_tokens) == (
                    "auto",
                    "sent",
                    "fake-small",
                    420,
                )
                assert reply.settled_at is not None
                async with setup.sessions() as db:
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

                # ----- they ask for a person: handed to the seller, no model, no reply -----
                asked = len(model.asked)
                await whatsapp_in("Please call me, I want to talk to someone")
                assert (await tick())["handoff"] == 1
                assert len(model.asked) == asked and len(FakeCloud.sent) == 1
                state = (await http.get(f"{BASE}/leads/{ids['asha']}/ai")).json()
                assert state["mode"] == "auto" and state["ready"] is True
                assert state["available"] is True and state["paused"] is False
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
                assert len(model.asked) == asked

                # ----- Messenger, the same way -----
                await messenger_in("Parking milegi kya?")
                assert (await tick())["sent"] == 1
                assert (
                    FakeGraph.sent[-1]["to"] == PSID
                    and FakeGraph.sent[-1]["channel"] == "messenger"
                )

                # ----- at the cap: automatic replies wait for budget -----
                admin = (await http.get(ADMIN)).json()
                assert admin["status"]["spent_inr"] == pytest.approx(0.0246)
                capped = await http.put(
                    f"{ADMIN}/settings",
                    json={"expected_revision": 1, "config": {**admin["config"], "cap_inr": 0}},
                    headers=WRITE,
                )
                assert capped.status_code == 200, capped.text
                sent_before, asked = len(FakeGraph.sent), len(model.asked)
                held = await messenger_in("Is there a gym in the society?")
                assert (await tick())["sent"] == 0
                assert (await outcome(held)).outcome == "waiting"
                assert len(FakeGraph.sent) == sent_before and len(model.asked) == asked
                stop = next(line for line in reversed(lines) if line.get("stopped"))
                assert stop["stopped"] == "lead_desk_ai_cap" and stop["waiting"] == 1
                assert stop["period"] == "daily" and stop["cap_inr"] == "0"
                admin = (await http.get(ADMIN)).json()
                assert admin["status"]["at_cap"] is True and admin["status"]["waiting"] == 1
                assert admin["status"]["raise_to_inr"] == 100
                state = (await http.get(f"{BASE}/leads/{ids['ravi']}/ai")).json()
                assert state["paused"] is True

                # ----- Raise and resume: one click, and the waiting reply goes -----
                raised = await http.post(
                    f"{ADMIN}/raise", json={"expected_revision": 2}, headers=WRITE
                )
                assert raised.status_code == 200, raised.text
                assert raised.json()["config"]["cap_inr"] == 100
                assert raised.json()["revision"] == 3
                assert (await tick())["sent"] == 1
                assert (await outcome(held)).outcome == "sent"
                assert len(FakeGraph.sent) == sent_before + 1
                async with setup.sessions() as db:
                    audited = (
                        await db.execute(
                            select(AuditEvent.action, AuditEvent.payload)
                            .where(AuditEvent.resource_type == "lead_desk_ai_settings")
                            .order_by(AuditEvent.sequence_no)
                        )
                    ).all()
                assert [action for action, _ in audited] == [
                    "lead_desk_ai.settings_saved",
                    "lead_desk_ai.settings_saved",
                    "lead_desk_ai.cap_raised",
                ]
                assert audited[-1][1]["old"]["cap_inr"] == 0
                assert audited[-1][1]["new"]["cap_inr"] == 100

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
                asked_for = await http.post(
                    f"{BASE}/leads/{ids['ravi']}/ai-draft",
                    json={"channel": "messenger"},
                    headers=WRITE,
                )
                assert asked_for.status_code == 200, asked_for.text
                queued = asked_for.json()
                assert queued["status"] == "queued" and queued["handoff"] is False
                status = f"{BASE}/leads/{ids['ravi']}/ai-draft/{queued['replyId']}"
                assert (await http.get(status)).json()["status"] == "queued"
                await think()
                ready = (await http.get(status)).json()
                assert ready["status"] == "drafted" and ready["draft"]
                assert len(FakeGraph.sent) == sent_before
                await messenger_in("What is the price of a 3 BHK?")
                asked = len(model.asked)
                priced = (
                    await http.post(
                        f"{BASE}/leads/{ids['ravi']}/ai-draft",
                        json={"channel": "messenger"},
                        headers=WRITE,
                    )
                ).json()
                # Settled by the rules at once, no model.
                assert priced["status"] == "handoff" and priced["reason"] == "price"
                assert "price" in priced["words"] and len(model.asked) == asked
                async with setup.sessions() as db:
                    suggested = await db.scalar(
                        select(func.count())
                        .select_from(LeadAiReply)
                        .where(
                            LeadAiReply.mode == "suggest", LeadAiReply.requested_by_person_id == me
                        )
                    )
                    assert suggested == 2

                # ----- at the cap, suggestions pause -----
                admin = (await http.get(ADMIN)).json()
                await http.put(
                    f"{ADMIN}/settings",
                    json={"expected_revision": 3, "config": {**admin["config"], "cap_inr": 0}},
                    headers=WRITE,
                )
                await messenger_in("Is there a clubhouse?")
                paused = (
                    await http.post(
                        f"{BASE}/leads/{ids['ravi']}/ai-draft",
                        json={"channel": "messenger"},
                        headers=WRITE,
                    )
                ).json()
                assert paused["status"] == "paused" and paused["words"] == (
                    "AI replies are paused for now."
                )
                assert "₹" not in str(paused)  # no amount is ever shown to sellers

                # ----- switched off again in Admin: no drafts at all -----
                admin = (await http.get(ADMIN)).json()
                await http.put(
                    f"{ADMIN}/settings",
                    json={"expected_revision": 4, "config": {**admin["config"], "enabled": False}},
                    headers=WRITE,
                )
                assert (
                    await http.post(
                        f"{BASE}/leads/{ids['ravi']}/ai-draft",
                        json={"channel": "messenger"},
                        headers=WRITE,
                    )
                ).status_code == 409
                assert (
                    await http.post(f"{BASE}/ai-replies/try", json={"message": "Hi"}, headers=WRITE)
                ).status_code == 409

                off = await http.put(
                    f"{BASE}/ai-replies/settings",
                    json={**_view(HOMES), "mode": "off"},
                    headers=WRITE,
                )
                assert off.status_code == 200

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
