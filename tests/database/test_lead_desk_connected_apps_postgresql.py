"""Settings → Connected apps on PostgreSQL, with Meta faked.

Health shows each app for the workspace: what is connected, the newest thing that
arrived, the last error and the tests on offer. The tests are real calls to the faked
Meta:
- a test lead is waited for until it reaches Leads;
- a WhatsApp test goes to the number given and passes when WhatsApp says delivered;
- a Messenger check asks Meta about the Page's subscription, and a test reply needs an
  explicit confirm.
Members can't see or run any of it.
"""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import select, update

from ac_platform.http.routes import RouteContext
from ac_platform.lead_desk import connected_apps
from ac_platform.lead_desk.connected_apps_http import install_connected_apps_http
from ac_platform.lead_desk.connectors import meta
from ac_platform.lead_desk.models import (
    Lead,
    LeadSocialAccount,
    LeadSocialMessage,
    LeadSource,
    LeadWhatsAppMessage,
    LeadWhatsAppNumber,
)
from ac_platform.lead_desk.social import graph
from ac_platform.lead_desk.store import LeadDesk, Viewer
from ac_platform.lead_desk.whatsapp import cloud
from ac_platform.tenancy.models import Membership
from tests.database.test_conversation_postgresql import postgres_harness as _postgres_harness
from tests.database.test_conversation_postgresql import run
from tests.database.test_conversation_submission_http_postgresql import ORIGIN, _setup
from tests.database.test_lead_desk_postgresql import _organisation
from tests.database.test_lead_desk_social_postgresql import FakeGraph
from tests.database.test_lead_desk_whatsapp_postgresql import FakeCloud
from tests.unit.lead_desk_connectors.test_meta import ENV as META_ENV
from tests.unit.lead_desk_whatsapp.test_whatsapp_cloud import ENV as WHATSAPP_ENV

WRITE = {"Origin": ORIGIN, "Content-Type": "application/json"}
BASE = "/v1/lead-desk/integrations"
ENV = {**META_ENV, **WHATSAPP_ENV, "AC_MESSAGING_LOGIN_CONFIG_ID": "5550001"}
PAGE = "100200300"
FORM = "777000111"
TEST_LEAD = "5550000000001"
PSID = "2400000000000001"


@pytest.fixture
def postgres_harness() -> Any:
    yield from cast(Any, _postgres_harness).__wrapped__()


class FakeMeta:
    made: list[str] = []
    earlier: list[str] = []  # the form's test lead from before (Meta keeps one)
    deleted: list[str] = []

    def __init__(self, cfg: meta.MetaConfig, client: Any = None, *, timeout: float = 20) -> None:
        pass

    async def test_leads(self, form_id: str, page_token: str) -> list[str]:
        if form_id == "888888888":
            raise meta.MetaError(
                "Meta refused the request.", code=100, detail="(#100) Unsupported get request"
            )
        return list(FakeMeta.earlier)

    async def delete_lead(self, lead_id: str, page_token: str) -> None:
        FakeMeta.deleted.append(lead_id)
        FakeMeta.earlier.remove(lead_id)

    async def create_test_lead(self, form_id: str, page_token: str) -> str:
        assert page_token == "leads-page-token"  # noqa: S105 - the fake's own token
        FakeMeta.made.append(form_id)
        if form_id == "999999999":
            raise meta.MetaError("You need to be an admin of this Page.", "permission")
        return TEST_LEAD


class SubscribedGraph(FakeGraph):
    fields: list[str] = ["messages", "feed"]

    async def subscribed_apps(self, page_id: str, page_token: str) -> dict[str, list[str]]:
        assert page_token == "page-token"  # noqa: S105 - the fake's own token
        return {self.cfg.app_id: SubscribedGraph.fields, "other-app": ["leadgen"]}


def test_connected_apps_health_and_real_tests(
    postgres_harness: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for name, value in ENV.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(meta, "Graph", FakeMeta)
    monkeypatch.setattr(cloud, "Cloud", FakeCloud)
    monkeypatch.setattr(graph, "Graph", SubscribedGraph)
    FakeCloud.sent, FakeGraph.sent, FakeMeta.made = [], [], []
    FakeMeta.earlier, FakeMeta.deleted = ["5550000000000"], []
    meta_cfg, wa_cfg, social_cfg = meta.config(), cloud.config(), graph.config()
    assert meta_cfg is not None and wa_cfg is not None and social_cfg is not None

    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path)
        try:
            await _organisation(setup)
            settings = setup.settings.model_copy(update={"public_learner_tenant_id": uuid4()})
            install_connected_apps_http(
                setup.app, RouteContext(settings, setup.require_actor, setup.sessions)
            )
            tenant, me = setup.state.tenant_id, setup.state.person_id
            now = datetime.now(UTC)
            async with setup.sessions() as db, db.begin():
                db.add_all(
                    [
                        LeadSource(
                            id=uuid4(),
                            tenant_id=tenant,
                            kind="meta",
                            label="Fictional Homes",
                            token_sha256=None,
                            config={
                                "page_id": PAGE,
                                "page_name": "Fictional Homes",
                                "forms": "all",
                                "token": meta.seal(
                                    meta_cfg.token_key, "leads-page-token", page_id=PAGE
                                ),
                                "last_pulled_at": int(now.timestamp()) - 60,
                            },
                            active=True,
                            received=3,
                            last_received_at=now - timedelta(hours=2),
                            created_by_person_id=me,
                            created_at=now,
                            updated_at=now,
                        ),
                        LeadWhatsAppNumber(
                            id=uuid4(),
                            tenant_id=tenant,
                            waba_id="55500001",
                            phone_number_id="10001",
                            display_number="+91 80000 00000",
                            verified_name="Fictional Homes",
                            quality="GREEN",
                            token=cloud.seal(
                                wa_cfg, "fake-business-token", phone_number_id="10001", what="token"
                            ),
                            status="active",
                            config={"first_reply": {"on": True}},
                            connected_by_person_id=me,
                            created_at=now,
                            updated_at=now,
                        ),
                    ]
                )
                page = LeadSocialAccount(
                    id=uuid4(),
                    tenant_id=tenant,
                    page_id=PAGE,
                    page_name="Fictional Homes",
                    token=graph.seal(social_cfg, "page-token", page_id=PAGE),
                    status="active",
                    config={
                        "last_comment_skip": {
                            "at": now.isoformat(),
                            "channel": "messenger",
                            "why": "no_sender",
                        }
                    },
                    connected_by_person_id=me,
                    created_at=now,
                    updated_at=now,
                )
                db.add(page)
                desk = LeadDesk(
                    db, Viewer(person_id=me, tenant_id=tenant, role="admin", name="Admin")
                )
                ravi, _ = await desk.ingest(
                    {"name": "Ravi Fictional", "messenger": PSID},
                    source="webhook",
                    source_ref=f"fb:{PAGE}:{PSID}",
                    actor=None,
                )
                assert ravi is not None
                db.add(
                    LeadSocialMessage(
                        id=uuid4(),
                        tenant_id=tenant,
                        account_id=page.id,
                        lead_id=ravi.id,
                        channel="messenger",
                        user_id=PSID,
                        direction="in",
                        mid=f"m.{uuid4().hex}",
                        kind="text",
                        body="Is parking covered?",
                        status="received",
                        meta_time=now,
                        created_at=now,
                    )
                )

            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=setup.app), base_url=ORIGIN
            ) as http:
                http.cookies.set(setup.settings.session_cookie_name, setup.token)

                # ----- health -----
                answer = await http.get(f"{BASE}/health")
                assert answer.status_code == 200, answer.text
                found = {item["app"]: item for item in answer.json()["apps"]}
                assert list(found) == list(connected_apps.APPS)
                leads = found["meta_leads"]
                assert (leads["state"], leads["configured"]) == ("ready", True)
                assert leads["connections"][0]["label"] == "Fictional Homes"
                assert leads["lastEvent"]["kind"] == "lead" and leads["nextPullAt"]
                assert leads["tests"][0]["needs"] == ["pageId", "formId"]
                assert found["whatsapp"]["state"] == "ready"
                assert "first reply" in found["whatsapp"]["connections"][0]["detail"]
                assert found["messenger"]["lastEvent"]["kind"] == "message"
                assert found["messenger"]["webhook"]["lastDeliveryAt"]
                assert found["instagram"]["state"] == "not_connected"  # the Page has no IG
                assert found["google_ads"]["state"] == "not_set_up"
                assert found["phone_calls"]["state"] == "not_connected"
                assert found["ai_replies"]["state"] == "off"
                # What a Settings card needs: group, the existing connect and disconnect
                # routes, and whether it can be tested.
                assert (leads["group"], leads["canTest"]) == ("leads", True)
                assert leads["connect"] == {"method": "GET", "path": "/v1/lead-desk/meta/connect"}
                assert leads["connections"][0]["disconnect"] == {
                    "method": "POST",
                    "path": f"/v1/lead-desk/meta/pages/{PAGE}/disconnect",
                }
                assert found["messenger"]["group"] == "messaging"
                assert (
                    "Meta didn't say who wrote it"
                    in (found["messenger"]["connections"][0]["words"])
                )
                assert found["messenger"]["connections"][0]["disconnect"]["path"].startswith(
                    "/v1/lead-desk/messaging/accounts/"
                )
                assert found["google_ads"]["connect"] is None  # not set up here
                assert (found["phone_calls"]["group"], found["phone_calls"]["canTest"]) == (
                    "calls",
                    False,
                )
                assert "₹" not in answer.text

                # ----- lead ads: a test lead, waited for in Leads -----
                made = await http.post(
                    f"{BASE}/meta_leads/test",
                    json={"pageId": PAGE, "formId": FORM},
                    headers=WRITE,
                )
                assert made.status_code == 200, made.text
                assert made.json()["status"] == "waiting" and FakeMeta.made == [FORM]
                # Meta keeps one test lead per form: the earlier one is deleted first.
                assert FakeMeta.deleted == ["5550000000000"]
                assert [(s["label"], s["state"]) for s in made.json()["steps"]] == [
                    ("Clear the form's earlier test lead", "done"),
                    ("Ask Meta for a test lead", "done"),
                    ("Wait for it in Leads", "waiting"),
                ]
                assert made.json()["steps"][0]["words"] == "Deleted 1 test lead."
                test_id = made.json()["testId"]
                assert (await http.get(f"{BASE}/tests/{test_id}")).json()["status"] == "waiting"
                async with setup.sessions() as db, db.begin():
                    desk = LeadDesk(
                        db, Viewer(person_id=me, tenant_id=tenant, role="system", name="Meta")
                    )
                    await desk.ingest(
                        {"name": "Test lead: dummy data", "phone": "+919000000001"},
                        source="meta",
                        source_ref=TEST_LEAD,
                        actor=None,
                    )
                arrived = (await http.get(f"{BASE}/tests/{test_id}")).json()
                assert arrived["status"] == "passed" and arrived["leadId"]
                assert [step["state"] for step in arrived["steps"]] == ["done", "done"]
                late = f"lead-{TEST_LEAD}9-{int((now - timedelta(minutes=5)).timestamp())}"
                assert (await http.get(f"{BASE}/tests/{late}")).json()["status"] == "failed"
                refused = (
                    await http.post(
                        f"{BASE}/meta_leads/test",
                        json={"pageId": PAGE, "formId": "999999999"},
                        headers=WRITE,
                    )
                ).json()
                assert refused["status"] == "failed" and "admin of this Page" in refused["words"]
                assert [s["state"] for s in refused["steps"]] == ["skipped", "failed", "skipped"]
                unlisted = (
                    await http.post(
                        f"{BASE}/meta_leads/test",
                        json={"pageId": PAGE, "formId": "888888888"},
                        headers=WRITE,
                    )
                ).json()
                # Meta's own words and code, not only "refused".
                assert unlisted["status"] == "failed"
                assert "(#100) Unsupported get request" in unlisted["words"]
                assert "(code 100)" in unlisted["words"]
                assert unlisted["steps"][0]["state"] == "failed"
                assert (
                    await http.post(
                        f"{BASE}/meta_leads/test",
                        json={"pageId": "123456789", "formId": FORM},
                        headers=WRITE,
                    )
                ).status_code == 404

                # ----- WhatsApp: a test message, passed at delivered -----
                no_template = await http.post(
                    f"{BASE}/whatsapp/test", json={"to": "+91 98765 43210"}, headers=WRITE
                )
                assert no_template.status_code == 409  # no hello_world, no chat in 24 h
                async with setup.sessions() as db, db.begin():
                    number = await db.scalar(select(LeadWhatsAppNumber))
                    assert number is not None
                    db.add(
                        LeadWhatsAppMessage(
                            id=uuid4(),
                            tenant_id=tenant,
                            number_id=number.id,
                            lead_id=None,
                            wa_id="919876543210",
                            direction="in",
                            wamid=f"wamid.{uuid4().hex}",
                            kind="text",
                            body="hi",
                            status="received",
                            meta_time=datetime.now(UTC),
                            created_at=datetime.now(UTC),
                        )
                    )
                sent = await http.post(
                    f"{BASE}/whatsapp/test", json={"to": "+91 98765 43210"}, headers=WRITE
                )
                assert sent.status_code == 200, sent.text
                assert sent.json()["status"] == "waiting"
                assert FakeCloud.sent == [{"to": "919876543210", "text": connected_apps.TEST_TEXT}]
                wa_test = sent.json()["testId"]
                async with setup.sessions() as db, db.begin():
                    await db.execute(
                        update(LeadWhatsAppMessage)
                        .where(LeadWhatsAppMessage.id == wa_test.removeprefix("wa-"))
                        .values(status="delivered", status_at=datetime.now(UTC))
                    )
                delivered = (await http.get(f"{BASE}/tests/{wa_test}")).json()
                assert delivered["status"] == "passed" and delivered["words"].startswith(
                    "Delivered."
                )
                assert (
                    await http.post(f"{BASE}/whatsapp/test", json={"to": "12"}, headers=WRITE)
                ).status_code == 422

                # ----- Messenger: the subscription, and a test reply only when confirmed -----
                checked = (await http.post(f"{BASE}/messenger/test", json={}, headers=WRITE)).json()
                assert checked["status"] == "passed" and FakeGraph.sent == []
                assert [step["state"] for step in checked["steps"]] == ["done", "done"]
                assert checked["steps"][1]["words"].endswith("UTC")  # when it arrived
                unconfirmed = await http.post(
                    f"{BASE}/messenger/test", json={"sendReply": True}, headers=WRITE
                )
                assert unconfirmed.status_code == 422 and FakeGraph.sent == []
                replied = (
                    await http.post(
                        f"{BASE}/messenger/test",
                        json={"sendReply": True, "confirm": True},
                        headers=WRITE,
                    )
                ).json()
                assert replied["status"] == "passed"
                assert FakeGraph.sent[-1]["to"] == PSID
                assert FakeGraph.sent[-1]["text"] == connected_apps.TEST_TEXT
                SubscribedGraph.fields = ["feed"]
                unsubscribed = (
                    await http.post(f"{BASE}/messenger/test", json={}, headers=WRITE)
                ).json()
                assert (
                    unsubscribed["status"] == "failed"
                    and "Connect it again" in (unsubscribed["words"])
                )
                SubscribedGraph.fields = ["messages", "feed"]

                # ----- reports, and the apps that aren't set up here -----
                assert (
                    await http.post(f"{BASE}/google_ads/test", json={}, headers=WRITE)
                ).status_code == 409
                phones = (
                    await http.post(f"{BASE}/phone_calls/test", json={}, headers=WRITE)
                ).json()
                assert phones["status"] == "failed"
                assert (await http.get(f"{BASE}/tests/nope")).status_code == 404

                # ----- members can't see or test -----
                async with setup.sessions() as db, db.begin():
                    await db.execute(
                        update(Membership).where(Membership.person_id == me).values(role="member")
                    )
                assert (await http.get(f"{BASE}/health")).status_code == 403
                async with setup.sessions() as db:
                    assert await db.scalar(select(Lead.id).where(Lead.source_ref == TEST_LEAD))
        finally:
            await setup.engine.dispose()

    run(exercise())
