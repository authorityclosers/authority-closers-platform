"""WhatsApp files, first reply with a brochure, drip sequences, broadcasts and their numbers
(0162), on PostgreSQL with Meta faked.

A manager adds a PDF once; the first reply carries it in a document-header template with the
lead's first name and the business's name, and Meta's copy is reused; a sequence sends its
steps on time and stops for a lead who replies, moves stage or writes STOP; a broadcast goes
only to people with a recorded yes, at its pace, keeps their proof, and ends by itself; the
campaign's numbers follow Meta's delivery statuses, the replies and the Won stage.
"""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import select, update

from ac_platform.http.routes import RouteContext
from ac_platform.lead_desk.models import (
    Lead,
    LeadWhatsAppCampaign,
    LeadWhatsAppCampaignLead,
    LeadWhatsAppMedia,
    LeadWhatsAppMessage,
)
from ac_platform.lead_desk.store import LeadDesk, Viewer
from ac_platform.lead_desk.whatsapp import campaigns, cloud, inbox
from ac_platform.lead_desk.whatsapp.http import install_whatsapp_http
from ac_platform.lead_desk.whatsapp.media import MediaStore, pick
from tests.database.test_conversation_postgresql import postgres_harness as _postgres_harness
from tests.database.test_conversation_postgresql import run
from tests.database.test_conversation_submission_http_postgresql import ORIGIN, _setup
from tests.database.test_lead_desk_postgresql import _admin_sells, _organisation
from tests.database.test_lead_desk_whatsapp_postgresql import (
    NUMBER_ID,
    WABA_ID,
    WELCOME,
    FakeCloud,
    _inbound,
    _signed,
    _status,
)
from tests.unit.lead_desk_whatsapp.test_whatsapp_cloud import ENV

WRITE = {"Origin": ORIGIN, "Content-Type": "application/json"}
BASE = "/v1/lead-desk"
PDF = b"%PDF-1.4\n% a fictional brochure\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"
BROCHURE = {
    "id": "77700011",
    "name": "enquiry_brochure",
    "language": "en",
    "category": "UTILITY",
    "status": "APPROVED",
    "components": [
        {"type": "HEADER", "format": "DOCUMENT"},
        {
            "type": "BODY",
            "text": "Hi {{1}}, we received your enquiry with {{2}}. Reply STOP to opt out.",
        },
    ],
}
NUDGE = {
    **WELCOME,
    "id": "77700012",
    "name": "visit_nudge",
    "components": [{"type": "BODY", "text": "Hi {{1}}, shall we talk this week?"}],
}


@pytest.fixture
def postgres_harness() -> Any:
    yield from cast(Any, _postgres_harness).__wrapped__()


class MediaCloud(FakeCloud):
    """The fake Meta account, with file uploads and file sends."""

    uploads: list[dict[str, Any]] = []
    handles: list[str] = []

    async def upload_media(
        self, phone_number_id: str, token: str, *, data: bytes, content_type: str, filename: str
    ) -> str:
        assert data == PDF and content_type == "application/pdf"
        MediaCloud.uploads.append({"filename": filename})
        return f"9990000{len(MediaCloud.uploads)}"

    async def upload_handle(
        self, token: str, *, data: bytes, content_type: str, filename: str
    ) -> str:
        MediaCloud.handles.append(filename)
        return "4::example-handle"

    async def send_media(self, phone_number_id: str, token: str, **kwargs: Any) -> str:
        FakeCloud.sent.append({"to": kwargs["to"], "media": kwargs["media_id"]})
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
        header: dict[str, str] | None = None,
    ) -> str:
        FakeCloud.sent.append(
            {"to": to, "template": name, "language": language, "values": values, "header": header}
        )
        return f"wamid.OUT{len(FakeCloud.sent)}"


def test_whatsapp_files_sequences_broadcasts_and_numbers(
    postgres_harness: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for name, value in ENV.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(cloud, "Cloud", MediaCloud)
    FakeCloud.sent = []
    MediaCloud.uploads = []
    MediaCloud.handles = []
    FakeCloud.templates_at_meta = [WELCOME, BROCHURE, NUDGE]
    cfg = cloud.config()
    assert cfg is not None
    root = tmp_path / "store"
    root.mkdir()
    store = MediaStore(str(root))
    api = MediaCloud(cfg)

    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path)
        try:
            await _organisation(setup)
            await _admin_sells(setup)
            settings = setup.settings.model_copy(
                update={"public_learner_tenant_id": uuid4(), "sales_xray_storage_root": str(root)}
            )
            install_whatsapp_http(
                setup.app, RouteContext(settings, setup.require_actor, setup.sessions)
            )
            tenant = setup.state.tenant_id

            async def add_lead(name: str, phone: str) -> Lead:
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
                    lead, _ = await desk.ingest(
                        {"name": name, "phone": phone},
                        source="manual",
                        actor=setup.state.person_id,
                    )
                    assert lead is not None
                    return lead

            async def loop(at: datetime) -> dict[str, int]:
                async with setup.sessions() as db, db.begin():
                    joined = await campaigns.enrol(db, now=at)
                    out = await campaigns.send_due(db, cfg, api, now=at, store=store)
                    return {**out, "joined": joined}

            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=setup.app), base_url=ORIGIN
            ) as client:
                client.cookies.set(setup.settings.session_cookie_name, setup.token)
                connected = await client.post(
                    f"{BASE}/whatsapp/connect",
                    json={"code": "signup-code", "wabaId": WABA_ID, "phoneNumberId": NUMBER_ID},
                    headers=WRITE,
                )
                assert connected.status_code == 200, connected.text
                number_id = connected.json()["numbers"][0]["id"]
                files = {t["name"]: t["file"] for t in connected.json()["templates"]}
                assert files == {
                    "welcome_lead": None,
                    "enquiry_brochure": "document",
                    "visit_nudge": None,
                }

                # ----- the file library: checked by its bytes, kept once -----
                refused = await client.post(
                    f"{BASE}/whatsapp/media",
                    params={"label": "Not a PDF", "filename": "x.pdf"},
                    content=b"<html>hello</html>",
                    headers={"Origin": ORIGIN, "Content-Type": "application/pdf"},
                )
                assert refused.status_code == 422
                added = await client.post(
                    f"{BASE}/whatsapp/media",
                    params={"label": "Project brochure", "filename": "Brochure (Nov).PDF"},
                    content=PDF,
                    headers={"Origin": ORIGIN, "Content-Type": "application/pdf"},
                )
                assert added.status_code == 201, added.text
                media = added.json()
                assert (media["kind"], media["filename"], media["sizeBytes"]) == (
                    "document",
                    "Brochure (Nov).pdf",
                    len(PDF),
                )
                shown = await client.get(f"{BASE}/whatsapp/media/{media['id']}/file")
                assert shown.status_code == 200 and shown.content == PDF
                assert shown.headers["content-type"] == "application/pdf"
                assert [m["id"] for m in (await client.get(f"{BASE}/whatsapp/media")).json()] == [
                    media["id"]
                ]

                # A template with a document header, with the PDF as Meta's example.
                made = await client.post(
                    f"{BASE}/whatsapp/numbers/{number_id}/templates",
                    json={
                        "name": "price_list",
                        "language": "en",
                        "category": "UTILITY",
                        "body": "Hi {{1}}, here is the price list you asked for.",
                        "example": ["Asha"],
                        "mediaId": media["id"],
                    },
                    headers=WRITE,
                )
                assert made.status_code == 201, made.text
                assert MediaCloud.handles == ["Brochure (Nov).pdf"]
                assert FakeCloud.templates_at_meta[-1]["name"] == "price_list"

                # ----- first reply with the brochure -----
                rules = f"{BASE}/whatsapp/numbers/{number_id}/auto-replies"
                first = {
                    "on": True,
                    "template": "enquiry_brochure",
                    "language": "en",
                    "who": "every_lead",
                    "agreed": True,
                }
                no_file = await client.put(
                    rules, json={"firstReply": first, "outOfHours": {"on": False}}, headers=WRITE
                )
                assert no_file.status_code == 422 and "document" in no_file.json()["detail"]
                saved = await client.put(
                    rules,
                    json={
                        "firstReply": {
                            **first,
                            "mediaId": media["id"],
                            "mediaRules": [{"form": "Diwali form", "mediaId": media["id"]}],
                        },
                        "outOfHours": {"on": False},
                    },
                    headers=WRITE,
                )
                assert saved.status_code == 200, saved.text
                kept = saved.json()["numbers"][0]["autoReplies"]["firstReply"]
                assert kept["mediaId"] == media["id"]
                assert kept["mediaRules"][0]["form"] == "Diwali form"

                ravi = await add_lead("Ravi Kumar", "+919811100021")
                async with setup.sessions() as db, db.begin():
                    sent = await inbox.first_replies(
                        db, cfg, api, now=datetime.now(UTC), store=store
                    )
                assert sent == 1
                out = FakeCloud.sent[-1]
                assert out["template"] == "enquiry_brochure" and out["values"][0] == "Ravi"
                assert len(out["values"]) == 2 and out["values"][1]
                assert out["header"] == {
                    "kind": "document",
                    "id": "99900001",
                    "filename": "Brochure (Nov).pdf",
                }
                await add_lead("Meera Shah", "+919811100022")
                async with setup.sessions() as db, db.begin():
                    assert (
                        await inbox.first_replies(db, cfg, api, now=datetime.now(UTC), store=store)
                        == 1
                    )
                assert FakeCloud.sent[-1]["header"]["id"] == "99900001"
                assert len(MediaCloud.uploads) == 1  # Meta's copy is reused
                async with setup.sessions() as db:
                    message = await db.scalar(
                        select(LeadWhatsAppMessage).where(LeadWhatsAppMessage.lead_id == ravi.id)
                    )
                    assert message is not None and message.auto == "first_reply"
                    assert message.media and message.media["library_id"] == media["id"]
                    row = await db.get(LeadWhatsAppMedia, UUID(media["id"]))
                    assert row is not None and NUMBER_ID in row.meta_ids
                    # The ad form picks the file; another form gets the default.
                    lead = await db.get(Lead, ravi.id)
                    assert lead is not None
                    lead.source_label = "Diwali form"
                    assert pick(kept_rules(kept), lead, None) == UUID(media["id"])
                    lead.source_label = "Other form"
                    assert pick(kept_rules(kept), lead, None) is None

                off = await client.put(
                    rules,
                    json={"firstReply": {"on": False}, "outOfHours": {"on": False}},
                    headers=WRITE,
                )
                assert off.status_code == 200, off.text

                # ----- a drip sequence: now, then 2 minutes later; it stops on its own -----
                drip = await client.post(
                    f"{BASE}/whatsapp/campaigns",
                    json={
                        "commandId": str(uuid4()),
                        "kind": "sequence",
                        "name": "New lead follow-up",
                        "trigger": {"on": "new_lead"},
                        "agreed": True,
                        "steps": [
                            {
                                "template": "enquiry_brochure",
                                "language": "en",
                                "mediaId": media["id"],
                            },
                            {
                                "template": "visit_nudge",
                                "language": "en",
                                "afterMinutes": 2,
                                "values": ["{name}"],
                            },
                        ],
                    },
                    headers=WRITE,
                )
                assert drip.status_code == 201, drip.text
                drip_id = drip.json()["id"]
                quiet = await add_lead("Anil Rao", "+919811100031")
                talker = await add_lead("Sunita Joshi", "+919811100032")
                mover = await add_lead("Vikram Das", "+919811100033")
                stopper = await add_lead("Neha Iyer", "+919811100034")
                # A lead on nobody's desk (not the connector's) still gets automatic steps.
                async with setup.sessions() as db, db.begin():
                    await db.execute(
                        update(Lead)
                        .where(Lead.id == quiet.id)
                        .values(
                            owner_person_id=None,
                            owner_reason=None,
                            assigned_at=None,
                            created_by_person_id=None,
                        )
                    )
                now = datetime.now(UTC)
                first_pass = await loop(now)
                assert first_pass["joined"] == 4 and first_pass["sent"] == 4, first_pass
                assert await loop(now + timedelta(minutes=1)) == {
                    "sent": 0,
                    "failed": 0,
                    "stopped": 0,
                    "ended": 0,
                    "joined": 0,
                }
                # Sunita replies, Vikram moves stage, Neha writes STOP.
                for wamid, sender, text in (
                    ("wamid.IN-talk", "919811100032", "Yes please call me"),
                    ("wamid.IN-stop", "919811100034", "STOP"),
                ):
                    body, headers = _signed(
                        _inbound(wamid, text, now + timedelta(seconds=30), sender)
                    )
                    got = await client.post(
                        f"{BASE}/whatsapp/webhook", content=body, headers=headers
                    )
                    assert got.status_code == 200, got.text
                async with setup.sessions() as db, db.begin():
                    await db.execute(
                        update(Lead).where(Lead.id == mover.id).values(stage="follow_up")
                    )
                    assert await inbox.said_no(db, await db.get(Lead, stopper.id))
                later = await loop(now + timedelta(minutes=3))
                assert (later["sent"], later["stopped"]) == (1, 3), later
                assert FakeCloud.sent[-1]["template"] == "visit_nudge"
                assert FakeCloud.sent[-1]["values"] == ["Anil"]
                async with setup.sessions() as db:
                    states = {
                        row.lead_id: (row.status, row.reason)
                        for row in (
                            await db.scalars(
                                select(LeadWhatsAppCampaignLead).where(
                                    LeadWhatsAppCampaignLead.campaign_id == UUID(drip_id)
                                )
                            )
                        ).all()
                    }
                assert states == {
                    quiet.id: ("done", None),
                    talker.id: ("stopped", "replied"),
                    mover.id: ("stopped", "stage"),
                    stopper.id: ("stopped", "said_stop"),
                }
                seq = (await client.get(f"{BASE}/whatsapp/campaigns/{drip_id}")).json()
                assert seq["numbers"]["sent"] == 5 and seq["numbers"]["replied"] == 2
                assert seq["numbers"]["people"] == {"done": 1, "stopped": 3}
                ended = await client.post(
                    f"{BASE}/whatsapp/campaigns/{drip_id}/status",
                    json={"status": "ended"},
                    headers=WRITE,
                )
                assert ended.json()["status"] == "ended" and ended.json()["endedAt"]

                # ----- a broadcast to people with a recorded yes, at its pace -----
                yes = await add_lead("Kiran Patel", "+919811100041")
                agreed = await client.post(
                    f"{BASE}/leads/{yes.id}/whatsapp/opt-in",
                    json={"commandId": str(uuid4()), "agreed": True, "how": "Said yes at the site"},
                    headers=WRITE,
                )
                assert agreed.status_code == 200, agreed.text
                silent = await add_lead("Farah Khan", "+919811100042")
                offer = {
                    "commandId": str(uuid4()),
                    "kind": "broadcast",
                    "name": "Site visit weekend",
                    "filters": {"leadIds": [str(yes.id), str(silent.id), str(stopper.id)]},
                    "steps": [{"template": "visit_nudge", "language": "en"}],
                    "perMinute": 30,
                }
                preview = (
                    await client.post(
                        f"{BASE}/whatsapp/campaigns/preview", json=offer, headers=WRITE
                    )
                ).json()
                assert preview["ready"] == 1
                assert {s["reason"]: s["count"] for s in preview["skipped"]} == {
                    "no_yes": 1,
                    "said_stop": 1,
                }
                stale = await client.post(
                    f"{BASE}/whatsapp/campaigns", json={**offer, "confirm": 2}, headers=WRITE
                )
                assert stale.status_code == 409
                started = await client.post(
                    f"{BASE}/whatsapp/campaigns", json={**offer, "confirm": 1}, headers=WRITE
                )
                assert started.status_code == 201, started.text
                cast_id = started.json()["id"]
                again = await client.post(
                    f"{BASE}/whatsapp/campaigns", json={**offer, "confirm": 1}, headers=WRITE
                )
                assert again.json()["id"] == cast_id  # the same command, the same broadcast
                done = await loop(datetime.now(UTC) + timedelta(seconds=5))
                assert (done["sent"], done["ended"]) == (1, 1), done
                wamid = f"wamid.OUT{len(FakeCloud.sent)}"
                assert FakeCloud.sent[-1]["to"] == "919811100041"
                for state in ("delivered", "read"):
                    body, headers = _signed(_status(wamid, state, datetime.now(UTC)))
                    await client.post(f"{BASE}/whatsapp/webhook", content=body, headers=headers)
                body, headers = _signed(
                    _inbound(
                        "wamid.IN-kiran",
                        "Saturday works",
                        datetime.now(UTC) + timedelta(1),
                        "919811100041",
                    )
                )
                await client.post(f"{BASE}/whatsapp/webhook", content=body, headers=headers)
                async with setup.sessions() as db, db.begin():
                    await db.execute(update(Lead).where(Lead.id == yes.id).values(stage="won"))
                    proof = await db.scalar(
                        select(LeadWhatsAppCampaignLead.proof).where(
                            LeadWhatsAppCampaignLead.campaign_id == UUID(cast_id),
                            LeadWhatsAppCampaignLead.lead_id == yes.id,
                        )
                    )
                    assert proof and proof["how"] == "Said yes at the site"
                    broadcast = await db.get(LeadWhatsAppCampaign, UUID(cast_id))
                    assert broadcast is not None and broadcast.status == "ended"
                view = (await client.get(f"{BASE}/whatsapp/campaigns/{cast_id}")).json()
                assert view["numbers"] | {"people": None, "reasons": None} == {
                    "people": None,
                    "reasons": None,
                    "sent": 1,
                    "delivered": 1,
                    "read": 1,
                    "failed": 0,
                    "replied": 1,
                    "won": 1,
                }
                assert view["numbers"]["people"] == {"done": 1, "skipped": 2}
                report = (await client.get(f"{BASE}/whatsapp/analytics")).json()
                rows = {(r["sentBy"], r["template"]): r for r in report["rows"]}
                assert rows[("broadcast", "visit_nudge")]["campaign"] == "Site visit weekend"
                assert rows[("first_reply", "enquiry_brochure")]["sent"] == 2
                assert rows[("drip", "enquiry_brochure")]["sent"] == 4
        finally:
            await setup.engine.dispose()

    run(exercise())


def kept_rules(first_reply: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {"stage": rule.get("stage"), "form": rule.get("form"), "media_id": rule["mediaId"]}
        for rule in first_reply["mediaRules"]
    ]
