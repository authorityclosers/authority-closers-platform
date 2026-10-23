"""Sales Xray CRM (Lead Desk) through its HTTP API on PostgreSQL.

One seller's day: rules route a Hindi lead to the Hindi speaker with a reason,
a repeat enquiry is "asked again" (never a duplicate), the desk queues it,
Start calling serves it, and NeoDove's dispose screen moves it on. Managers
alone see the team; a website form posts with its own key; files import.
"""

import io
import zipfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import func, select, update

from ac_platform.http.routes import RouteContext
from ac_platform.lead_desk.http import install_lead_desk_http
from ac_platform.lead_desk.models import Lead, LeadEvent
from ac_platform.tenancy.models import Membership, Organisation
from tests.database.test_conversation_account_library_postgresql import _session
from tests.database.test_conversation_postgresql import postgres_harness as _postgres_harness
from tests.database.test_conversation_postgresql import run, seed
from tests.database.test_conversation_submission_http_postgresql import ORIGIN, _setup

WRITE = {"Origin": ORIGIN, "Content-Type": "application/json"}
BASE = "/v1/lead-desk"


@pytest.fixture
def postgres_harness() -> Any:
    yield from cast(Any, _postgres_harness).__wrapped__()


async def _organisation(setup: Any) -> None:
    async with setup.sessions() as db, db.begin():
        db.add(
            Organisation(
                tenant_id=setup.state.tenant_id,
                created_by_person_id=setup.state.person_id,
                creation_command_id=uuid4(),
                domain_verification_token=uuid4().hex + uuid4().hex,
            )
        )
        await db.execute(
            update(Membership)
            .where(Membership.person_id == setup.state.person_id)
            .values(role="admin")
        )
    settings = setup.settings.model_copy(update={"public_learner_tenant_id": uuid4()})
    install_lead_desk_http(setup.app, RouteContext(settings, setup.require_actor, setup.sessions))


def _far_column_xlsx() -> bytes:
    """A <1 KB workbook whose one cell claims column ZZZZZZ (AUT-2029's probe)."""
    ns = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
    rel = 'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "xl/workbook.xml",
            f'<workbook {ns} {rel}><sheets><sheet name="L" sheetId="1" r:id="rId1"/></sheets>'
            "</workbook>",
        )
        archive.writestr(
            "xl/_rels/workbook.xml.rels",
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Target="worksheets/sheet1.xml"/></Relationships>',
        )
        archive.writestr(
            "xl/worksheets/sheet1.xml",
            f'<worksheet {ns}><sheetData><row r="1"><c r="A1" t="inlineStr"><is><t>Name</t>'
            '</is></c></row><row r="2"><c r="ZZZZZZ2"><v>1</v></c></row></sheetData></worksheet>',
        )
    return buffer.getvalue()


def test_a_sellers_day_on_the_desk(postgres_harness: Any, tmp_path: Path) -> None:
    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path)
        try:
            await _organisation(setup)
            seller = await seed(setup.engine, tenant_id=setup.state.tenant_id, role="member")
            other = await seed(setup.engine, tenant_id=setup.state.tenant_id, role="member")
            seller_token = await _session(setup, seller)
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=setup.app), base_url=ORIGIN
            ) as client:

                def as_(token: str) -> None:
                    client.cookies.set(setup.settings.session_cookie_name, token)

                as_(setup.token)
                team = (await client.get(f"{BASE}/team")).json()
                assert len(team["reps"]) == 3 and team["settings"]["auto_reassign"] is False
                admin_id = str(setup.state.person_id)
                # The admin doesn't take leads; the seller speaks Hindi; the other doesn't.
                for person, rules in (
                    (admin_id, {"available": False, "languages": []}),
                    (str(seller.person_id), {"available": True, "languages": ["Hindi"]}),
                    (str(other.person_id), {"available": True, "languages": ["Tamil"]}),
                ):
                    saved = await client.put(
                        f"{BASE}/team/{person}",
                        json={"expected_revision": 0, "max_open": 10, **rules},
                        headers=WRITE,
                    )
                    assert saved.status_code == 200, saved.text
                stale = await client.put(
                    f"{BASE}/team/{admin_id}",
                    json={"expected_revision": 0, "available": True, "max_open": 10},
                    headers=WRITE,
                )
                assert stale.status_code == 409

                added = await client.post(
                    f"{BASE}/leads",
                    json={
                        "command_id": str(uuid4()),
                        "name": "Asha Patil",
                        "phone": "98765 43210",
                        "language": "Hindi",
                        "city": "Pune",
                    },
                    headers=WRITE,
                )
                assert added.status_code == 201, added.text
                lead = added.json()
                lead_id = lead["lead"]["lead_id"]
                assert lead["lead"]["owner_person_id"] == str(seller.person_id)
                assert lead["owner_reason"].startswith("Speaks Hindi")
                assert lead["phone"] == "+919876543210"

                command = str(uuid4())
                again = await client.post(
                    f"{BASE}/leads",
                    json={"command_id": command, "name": "Asha", "phone": "+91 98765-43210"},
                    headers=WRITE,
                )
                assert again.json()["lead"]["lead_id"] == lead_id
                retried = await client.post(
                    f"{BASE}/leads",
                    json={"command_id": command, "name": "Asha", "phone": "+91 98765-43210"},
                    headers=WRITE,
                )
                assert retried.json()["lead"]["lead_id"] == lead_id
                async with setup.sessions() as db:
                    stored = await db.get(Lead, lead_id)
                    assert stored is not None and stored.repeats == 1
                    assert await db.scalar(select(func.count()).select_from(Lead)) == 1

                as_(seller_token)
                assert (await client.get(f"{BASE}/team")).status_code == 403
                assert (await client.get(f"{BASE}/leads?scope=team")).status_code == 403
                desk = (await client.get(BASE)).json()
                assert desk["me"]["can_manage"] is False
                assert [row["lead_id"] for row in desk["queue"]] == [lead_id]
                assert desk["queue"][0]["why_kind"] == "due"
                assert desk["queue"][0]["why"].startswith("Asked again")
                assert desk["counts"]["open"] == 1 and desk["counts"]["unassigned"] is None
                start = (await client.get(f"{BASE}/next")).json()
                assert start["lead"]["lead_id"] == lead_id
                assert (await client.get(f"{BASE}/next?skip={lead_id}")).json() is None

                missed = await client.post(
                    f"{BASE}/leads/{lead_id}/dispose",
                    json={
                        "command_id": str(uuid4()),
                        "expected_revision": start["lead"]["revision"],
                        "connected": False,
                        "reason": "did_not_pick",
                    },
                    headers=WRITE,
                )
                assert missed.status_code == 200, missed.text
                row = missed.json()["lead"]
                assert row["stage"] == "not_connected" and row["attempts"] == 1
                retry_at = datetime.fromisoformat(row["next_action_at"])
                assert timedelta(minutes=55) < retry_at - datetime.now(UTC) < timedelta(minutes=65)

                no_time = await client.post(
                    f"{BASE}/leads/{lead_id}/dispose",
                    json={
                        "command_id": str(uuid4()),
                        "expected_revision": row["revision"],
                        "connected": True,
                        "stage": "interested",
                    },
                    headers=WRITE,
                )
                assert no_time.status_code == 422
                follow = (datetime.now(UTC) + timedelta(days=1)).isoformat()
                talked = await client.post(
                    f"{BASE}/leads/{lead_id}/dispose",
                    json={
                        "command_id": str(uuid4()),
                        "expected_revision": row["revision"],
                        "connected": True,
                        "stage": "interested",
                        "follow_up_at": follow,
                        "remark": "Send the 60K package details",
                        "deal_value": "60,000",
                    },
                    headers=WRITE,
                )
                assert talked.status_code == 200, talked.text
                detail = talked.json()
                assert detail["lead"]["stage"] == "interested"
                assert detail["next_action_note"] == "Send the 60K package details"
                kinds = [event["kind"] for event in detail["events"]]
                assert kinds[:2] == ["result", "result"] and "captured" in kinds
                stale_dispose = await client.post(
                    f"{BASE}/leads/{lead_id}/dispose",
                    json={
                        "command_id": str(uuid4()),
                        "expected_revision": row["revision"],
                        "connected": True,
                        "stage": "won",
                    },
                    headers=WRITE,
                )
                assert stale_dispose.status_code == 409
                numbers = (await client.get(BASE)).json()["numbers"]
                assert numbers["calls"] == 2 and numbers["connected"] == 1

                # The other seller can't see or touch it.
                as_(await _session(setup, other))
                assert (await client.get(f"{BASE}/leads/{lead_id}")).status_code == 404

                # A manager moves it; the history keeps both owners.
                as_(setup.token)
                moved = await client.post(
                    f"{BASE}/leads/{lead_id}/assign",
                    json={
                        "command_id": str(uuid4()),
                        "expected_revision": detail["lead"]["revision"],
                        "person_id": str(other.person_id),
                    },
                    headers=WRITE,
                )
                assert moved.status_code == 200, moved.text
                assert moved.json()["lead"]["owner_person_id"] == str(other.person_id)
                async with setup.sessions() as db:
                    history = (
                        await db.scalars(
                            select(LeadEvent.kind)
                            .where(LeadEvent.lead_id == lead_id)
                            .order_by(LeadEvent.created_at)
                        )
                    ).all()
                assert history == [
                    "captured",
                    "assigned",
                    "repeat",
                    "result",
                    "result",
                    "reassigned",
                ]

                # Home for owners and admins: outcomes first, sellers ranked by them.
                report = await client.get(f"{BASE}/reports/performance", params={"days": 7})
                assert report.status_code == 200, report.text
                week = report.json()
                assert week["days"] == 7
                assert week["current"]["calls"] == 2 and week["current"]["connected"] == 1
                assert week["current"]["leads_called"] == 1
                assert (week["current"]["interested"], week["current"]["won"]) == (1, 0)
                assert week["current"]["new_leads"] == 1
                assert week["previous"]["calls"] == 0 and week["previous"]["new_leads"] == 0
                top = week["sellers"][0]
                assert top["person_id"] == str(seller.person_id)
                assert (top["calls"], top["interested"]) == (2, 1)
                assert week["pipeline"] == {"interested": 1}
                odd = await client.get(f"{BASE}/reports/performance", params={"days": 3})
                assert odd.status_code == 422
                as_(seller_token)
                mine = await client.get(f"{BASE}/reports/performance", params={"days": 7})
                assert mine.status_code == 403
        finally:
            await setup.engine.dispose()

    run(exercise())


def test_website_form_and_file_capture(postgres_harness: Any, tmp_path: Path) -> None:
    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path)
        try:
            await _organisation(setup)
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=setup.app), base_url=ORIGIN
            ) as client:
                client.cookies.set(setup.settings.session_cookie_name, setup.token)
                made = await client.post(
                    f"{BASE}/sources", json={"kind": "webhook", "label": "Website"}, headers=WRITE
                )
                assert made.status_code == 201, made.text
                source = made.json()
                token = source["token"]
                assert token and source["endpoint"].endswith(f"/capture/{source['source_id']}")
                assert (await client.get(f"{BASE}/sources")).json()["sources"][0]["token"] is None

                client.cookies.clear()
                capture = f"{BASE}/capture/{source['source_id']}"
                lead = {"full_name": "Ravi Kumar", "phone_number": "9800000001", "city": "Pune"}
                denied = await client.post(capture, json=lead, headers={"X-Lead-Desk-Key": "x"})
                assert denied.status_code == 401
                first = await client.post(capture, json=lead, headers={"X-Lead-Desk-Key": token})
                assert first.status_code == 202 and first.json()["outcome"] == "created"
                same = await client.post(capture, json=lead, headers={"X-Lead-Desk-Key": token})
                assert same.json()["outcome"] == "known"
                form = await client.post(
                    f"{capture}?key={token}",
                    content="name=Neha&mobile=9800000002&interest=Coaching",
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                )
                assert form.json()["outcome"] == "created"

                client.cookies.set(setup.settings.session_cookie_name, setup.token)
                csv = (
                    b"Customer,Mobile No,City\nAsha,98000 00003,Pune\nRavi again,9800000001,\n,,\n"
                )
                preview = await client.post(
                    f"{BASE}/imports/preview",
                    content=csv,
                    headers={"Origin": ORIGIN, "Content-Type": "text/csv", "X-File-Name": "a.csv"},
                )
                assert preview.status_code == 200, preview.text
                shown = preview.json()
                assert shown["total_rows"] == 2 and shown["mapping"]["phone"] == "Mobile No"
                # AUT-2029: a cell far to the right is refused, never expanded into a row.
                far = await client.post(
                    f"{BASE}/imports/preview",
                    content=_far_column_xlsx(),
                    headers={"Origin": ORIGIN, "X-File-Name": "far.xlsx"},
                )
                assert far.status_code == 422, far.text
                assert "more than 200 columns" in far.json()["detail"]
                done = await client.post(
                    f"{BASE}/imports",
                    json={
                        "command_id": str(uuid4()),
                        "file_name": "a.csv",
                        "mapping": {**shown["mapping"], "name": "Customer"},
                        "rows": shown["rows"],
                    },
                    headers=WRITE,
                )
                assert done.status_code == 200, done.text
                assert done.json()["created"] == 1 and done.json()["repeats"] == 1
                again = await client.post(
                    f"{BASE}/imports",
                    json={
                        "command_id": str(uuid4()),
                        "file_name": "a.csv",
                        "mapping": {**shown["mapping"], "name": "Customer"},
                        "rows": shown["rows"],
                    },
                    headers=WRITE,
                )
                assert again.json()["created"] == 0
                page = (await client.get(f"{BASE}/leads?scope=team&stage=open")).json()
                assert page["total"] == 3
                assert {row["source"] for row in page["leads"]} == {"webhook", "csv"}
                # The stage tabs' counts: every stage, whatever stage is asked for.
                assert page["stage_counts"] == {"new": 3}
                won = (await client.get(f"{BASE}/leads?scope=team&stage=won")).json()
                assert won["total"] == 0 and won["stage_counts"] == {"new": 3}
                none = (await client.get(f"{BASE}/leads?scope=team&search=zzzz")).json()
                assert none["stage_counts"] == {}

                # Stage and owner columns (paste import, 23 Oct 2026): a row names its
                # lead's stage and owner; a number already a lead keeps its own.
                me = next(
                    rep
                    for rep in (await client.get(f"{BASE}/team")).json()["reps"]
                    if rep["person_id"] == str(setup.state.person_id)
                )
                sheet = (
                    "Name,Phone,Status,Assigned to\n"
                    f"Meera,9800000010,interested,{me['name'].upper()}\n"
                    "Karan,9800000011,Hot lead,Nobody Known\n"
                    "Asha,98000 00003,Won,\n"
                ).encode()
                looked = await client.post(
                    f"{BASE}/imports/preview",
                    content=sheet,
                    headers={"Origin": ORIGIN, "Content-Type": "text/csv", "X-File-Name": "b.csv"},
                )
                assert looked.status_code == 200, looked.text
                seen = looked.json()
                assert seen["mapping"]["stage"] == "Status"
                assert seen["mapping"]["owner"] == "Assigned to"
                assert seen["known_leads"] == 1
                added = await client.post(
                    f"{BASE}/imports",
                    json={
                        "command_id": str(uuid4()),
                        "file_name": "b.csv",
                        "mapping": seen["mapping"],
                        "rows": seen["rows"],
                    },
                    headers=WRITE,
                )
                assert added.status_code == 200, added.text
                result = added.json()
                assert (result["created"], result["repeats"]) == (2, 1)
                assert (result["staged"], result["owned"]) == (1, 1)
                assert result["unmatched_stages"] == ["Hot lead"]
                assert result["unmatched_owners"] == ["Nobody Known"]
                rows = {
                    row["name"]: row
                    for row in (await client.get(f"{BASE}/leads?scope=team")).json()["leads"]
                }
                assert rows["Meera"]["stage"] == "interested"
                assert rows["Meera"]["owner_person_id"] == str(setup.state.person_id)
                assert rows["Karan"]["stage"] == "new"
                assert rows["Asha"]["stage"] == "new"
        finally:
            await setup.engine.dispose()

    run(exercise())


def test_personal_workspace_has_no_desk(postgres_harness: Any, tmp_path: Path) -> None:
    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path)
        install_lead_desk_http(
            setup.app, RouteContext(setup.settings, setup.require_actor, setup.sessions)
        )
        try:
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=setup.app), base_url=ORIGIN
            ) as client:
                client.cookies.set(setup.settings.session_cookie_name, setup.token)
                refused = await client.get(BASE)
                assert refused.status_code == 403
                assert "organisation" in refused.json()["detail"]
        finally:
            await setup.engine.dispose()

    run(exercise())


def test_edit_details_and_notes_keep_history(postgres_harness: Any, tmp_path: Path) -> None:
    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path)
        try:
            await _organisation(setup)
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=setup.app), base_url=ORIGIN
            ) as client:
                client.cookies.set(setup.settings.session_cookie_name, setup.token)

                async def add(name: str, phone: str) -> dict[str, Any]:
                    made = await client.post(
                        f"{BASE}/leads",
                        json={
                            "command_id": str(uuid4()),
                            "name": name,
                            "phone": phone,
                            "assign": "me",
                        },
                        headers=WRITE,
                    )
                    assert made.status_code == 201, made.text
                    return made.json()

                first = await add("Asha", "9800000011")
                await add("Ravi", "9800000012")
                lead_id, revision = first["lead"]["lead_id"], first["lead"]["revision"]
                clash = await client.patch(
                    f"{BASE}/leads/{lead_id}",
                    json={
                        "command_id": str(uuid4()),
                        "expected_revision": revision,
                        "phone": "98000 00012",
                    },
                    headers=WRITE,
                )
                assert clash.status_code == 409 and "Ravi" in clash.json()["detail"]
                no_name = await client.patch(
                    f"{BASE}/leads/{lead_id}",
                    json={"command_id": str(uuid4()), "expected_revision": revision, "name": " "},
                    headers=WRITE,
                )
                assert no_name.status_code == 422
                edited = await client.patch(
                    f"{BASE}/leads/{lead_id}",
                    json={
                        "command_id": str(uuid4()),
                        "expected_revision": revision,
                        "city": "Pune",
                        "email": "Asha@Example.com",
                        "phone": "",
                    },
                    headers=WRITE,
                )
                assert edited.status_code == 200, edited.text
                detail = edited.json()
                assert detail["lead"]["city"] == "Pune" and detail["email"] == "asha@example.com"
                assert detail["phone"] is None
                assert detail["events"][0]["kind"] == "edited"
                assert set(detail["events"][0]["changed"]) == {"city", "email", "phone"}
                noted = await client.post(
                    f"{BASE}/leads/{lead_id}/notes",
                    json={"command_id": str(uuid4()), "note": "Prefers WhatsApp after 6 pm"},
                    headers=WRITE,
                )
                assert noted.status_code == 200
                assert noted.json()["events"][0] == {
                    **noted.json()["events"][0],
                    "kind": "note",
                    "note": "Prefers WhatsApp after 6 pm",
                }
                # A call from the seller's own phone is logged; nothing is simulated.
                assert noted.json()["call_mode"] == "phone"
                called = await client.post(
                    f"{BASE}/leads/{lead_id}/calls/phone",
                    json={"command_id": str(uuid4()), "duration_seconds": 95},
                    headers=WRITE,
                )
                assert called.status_code == 200, called.text
                call = called.json()["events"][0]
                assert call["kind"] == "call" and call["simulated"] is False
                assert call["duration_seconds"] == 95
                assert called.json()["lead"]["revision"] > noted.json()["lead"]["revision"]
                # Its recording, uploaded afterwards, joins the lead without a second call.
                recording = str(uuid4())
                attached = await client.post(
                    f"{BASE}/leads/{lead_id}/recordings",
                    json={"command_id": str(uuid4()), "submission_id": recording},
                    headers=WRITE,
                )
                assert attached.status_code == 200, attached.text
                event = attached.json()["events"][0]
                assert event["kind"] == "call" and event["recording"] is True
                assert event["submission_id"] == recording
                assert attached.json()["lead"]["calls"] == called.json()["lead"]["calls"]
        finally:
            await setup.engine.dispose()

    run(exercise())


def test_booked_calls_ready_messages_and_phone_alerts(
    postgres_harness: Any, tmp_path: Path
) -> None:
    """UX study, 17 Oct: book the next call from the list, log a ready message, see what
    is overdue and coming up, and send each phone alert once with no lead details."""
    import json
    from uuid import UUID

    from ac_platform.lead_desk import push
    from ac_platform.lead_desk.models import LeadDevice

    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path)
        try:
            await _organisation(setup)
            seller = await seed(setup.engine, tenant_id=setup.state.tenant_id, role="member")
            other = await seed(setup.engine, tenant_id=setup.state.tenant_id, role="member")
            seller_token = await _session(setup, seller)
            other_token = await _session(setup, other)
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=setup.app), base_url=ORIGIN
            ) as client:

                def as_(token: str) -> None:
                    client.cookies.set(setup.settings.session_cookie_name, token)

                async def add_for_seller(name: str, phone: str) -> dict[str, Any]:
                    as_(setup.token)
                    made = await client.post(
                        f"{BASE}/leads",
                        json={
                            "command_id": str(uuid4()),
                            "name": name,
                            "phone": phone,
                            "interest": "Solar rooftop",
                            "assign": "person",
                            "person_id": str(seller.person_id),
                        },
                        headers=WRITE,
                    )
                    assert made.status_code == 201, made.text
                    return made.json()

                asha = await add_for_seller("Asha Patil", "9800000031")
                ravi = await add_for_seller("Ravi Kumar", "9800000032")

                # The seller's phone asks for alerts; the API stays off without FCM here.
                as_(seller_token)
                assert (await client.get(f"{BASE}/push")).json()["enabled"] is False
                device = {"token": "fcm-token-" + "a" * 40, "app_version": "0.3.20"}
                saved = await client.post(f"{BASE}/devices", json=device, headers=WRITE)
                assert saved.status_code == 200 and saved.json()["registered"] is True
                again = await client.post(f"{BASE}/devices", json=device, headers=WRITE)
                assert again.status_code == 200
                bad = await client.post(f"{BASE}/devices", json={"token": "short"}, headers=WRITE)
                assert bad.status_code == 422

                # Two new leads for the seller: one alert for both, ids and counts only.
                now = datetime.now(UTC)
                async with setup.sessions() as db, db.begin():
                    alerts = await push.collect(db, now)
                assert len(alerts) == 1
                data = alerts[0].data()
                assert data["kind"] == "many" and data["alerts"] == "2" and data["count"] == "2"
                assert alerts[0].tokens == [device["token"]]
                assert "Asha" not in json.dumps(data) and "98000" not in json.dumps(data)
                async with setup.sessions() as db, db.begin():
                    assert await push.collect(db, now) == []

                # The phone reads the words on the seller's own session.
                asha_id = asha["lead"]["lead_id"]
                text = (await client.get(f"{BASE}/leads/{asha_id}/alert")).json()
                assert text["title"] == "New lead: Asha Patil"
                assert text["url"] == f"/leads#lead={asha_id}"
                assert "Solar rooftop" in text["body"]
                summary = (await client.get(f"{BASE}/alert")).json()
                assert summary["title"] == "2 leads to call now"
                as_(other_token)
                assert (await client.get(f"{BASE}/leads/{asha_id}/alert")).status_code == 404
                as_(seller_token)

                # A ready message is logged by its template, never its text.
                sent = await client.post(
                    f"{BASE}/leads/{asha_id}/messages",
                    json={"command_id": str(uuid4()), "channel": "whatsapp", "template": "intro"},
                    headers=WRITE,
                )
                assert sent.status_code == 200, sent.text
                event = sent.json()["events"][0]
                assert event["kind"] == "message" and event["channel"] == "WhatsApp"
                assert event["template_label"] == "Introduction"
                unknown = await client.post(
                    f"{BASE}/leads/{asha_id}/messages",
                    json={"command_id": str(uuid4()), "channel": "sms", "template": "spam"},
                    headers=WRITE,
                )
                assert unknown.status_code == 422

                # Book Asha's call for later without calling; it leaves New.
                lead = sent.json()["lead"]
                booked = await client.post(
                    f"{BASE}/leads/{asha_id}/follow-up",
                    json={
                        "command_id": str(uuid4()),
                        "expected_revision": lead["revision"],
                        "at": (now + timedelta(days=2)).isoformat(),
                    },
                    headers=WRITE,
                )
                assert booked.status_code == 200, booked.text
                assert booked.json()["events"][0]["kind"] == "scheduled"
                assert booked.json()["lead"]["why"] == "Call booked"
                stale = await client.post(
                    f"{BASE}/leads/{asha_id}/follow-up",
                    json={
                        "command_id": str(uuid4()),
                        "expected_revision": lead["revision"],
                        "at": (now + timedelta(days=1)).isoformat(),
                    },
                    headers=WRITE,
                )
                assert stale.status_code == 409

                # Ravi waited two hours: overdue on the desk and on the badge.
                async with setup.sessions() as db, db.begin():
                    await db.execute(
                        update(Lead)
                        .where(Lead.id == UUID(ravi["lead"]["lead_id"]))
                        .values(created_at=now - timedelta(hours=2))
                    )
                desk = (await client.get(BASE)).json()
                assert desk["counts"]["overdue"] == 1
                rows = {row["name"]: row for row in desk["queue"]}
                assert rows["Ravi Kumar"]["overdue"] is True
                assert [row["name"] for row in desk["upcoming"]] == ["Asha Patil"]
                assert {item["key"] for item in desk["templates"]} >= {"intro", "missed_call"}
                badge = (await client.get(f"{BASE}/badge")).json()
                assert badge["overdue"] == 1 and badge["to_call"] == 1

                # When Asha's booked time comes, one "due" alert; then nothing.
                async with setup.sessions() as db, db.begin():
                    await db.execute(
                        update(Lead)
                        .where(Lead.id == UUID(asha_id))
                        .values(next_action_at=now - timedelta(minutes=1))
                    )
                async with setup.sessions() as db, db.begin():
                    alerts = await push.collect(db, now)
                assert [alert.data()["kind"] for alert in alerts] == ["due"]
                assert alerts[0].data()["lead"] == asha_id
                async with setup.sessions() as db, db.begin():
                    assert await push.collect(db, now) == []
                text = (await client.get(f"{BASE}/leads/{asha_id}/alert")).json()
                assert text["title"] == "Call Asha Patil now"

                # Someone else signing in on the same phone takes its alerts over.
                as_(other_token)
                taken = await client.post(f"{BASE}/devices", json=device, headers=WRITE)
                assert taken.status_code == 200
                async with setup.sessions() as db:
                    owners = (await db.scalars(select(LeadDevice.person_id))).all()
                assert owners == [other.person_id]
                forgot = await client.post(f"{BASE}/devices/forget", json=device, headers=WRITE)
                assert forgot.status_code == 200 and forgot.json()["registered"] is False
                async with setup.sessions() as db:
                    assert await db.scalar(select(func.count()).select_from(LeadDevice)) == 0
        finally:
            await setup.engine.dispose()

    run(exercise())


def test_a_seller_turns_new_leads_off_and_on(postgres_harness: Any, tmp_path: Path) -> None:
    """UX study item 8, 18 Oct: a seller's own "Taking new leads" switch. While it is
    off the lead rules give them nothing new; managers see it on Team."""

    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path)
        try:
            await _organisation(setup)
            seller = await seed(setup.engine, tenant_id=setup.state.tenant_id, role="member")
            other = await seed(setup.engine, tenant_id=setup.state.tenant_id, role="member")
            seller_token = await _session(setup, seller)
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=setup.app), base_url=ORIGIN
            ) as client:

                def as_(token: str) -> None:
                    client.cookies.set(setup.settings.session_cookie_name, token)

                as_(setup.token)
                # The admin takes no leads, so the two sellers share them.
                saved = await client.put(
                    f"{BASE}/team/{setup.state.person_id}",
                    json={"expected_revision": 0, "available": False, "max_open": 10},
                    headers=WRITE,
                )
                assert saved.status_code == 200, saved.text

                as_(seller_token)
                assert (await client.get(BASE)).json()["me"]["taking_leads"] is True
                off = await client.put(f"{BASE}/me/taking", json={"taking": False}, headers=WRITE)
                assert off.status_code == 200, off.text
                assert off.json()["taking_leads"] is False
                assert (await client.get(BASE)).json()["me"]["taking_leads"] is False
                # Switching off twice changes nothing.
                again = await client.put(f"{BASE}/me/taking", json={"taking": False}, headers=WRITE)
                assert again.status_code == 200 and again.json()["taking_leads"] is False
                refused = await client.put(f"{BASE}/me/taking", json={"taking": "yes please"})
                assert refused.status_code in {403, 422}

                as_(setup.token)
                for index, name in enumerate(("Ravi Kulkarni", "Meena Shah")):
                    added = await client.post(
                        f"{BASE}/leads",
                        json={
                            "command_id": str(uuid4()),
                            "name": name,
                            "phone": f"98765 4321{index}",
                        },
                        headers=WRITE,
                    )
                    assert added.status_code == 201, added.text
                    assert added.json()["lead"]["owner_person_id"] == str(other.person_id)
                team = (await client.get(f"{BASE}/team")).json()
                row = next(rep for rep in team["reps"] if rep["person_id"] == str(seller.person_id))
                assert row["available"] is False and row["revision"] == 1

                as_(seller_token)
                on = await client.put(f"{BASE}/me/taking", json={"taking": True}, headers=WRITE)
                assert on.json()["taking_leads"] is True
                as_(setup.token)
                added = await client.post(
                    f"{BASE}/leads",
                    json={"command_id": str(uuid4()), "name": "Kiran Rao", "phone": "98765 43299"},
                    headers=WRITE,
                )
                # Back on, with fewer open leads than the other seller: it comes to them.
                assert added.json()["lead"]["owner_person_id"] == str(seller.person_id)
        finally:
            await setup.engine.dispose()

    run(exercise())


def test_calls_the_phone_logged_by_itself_reach_their_leads(
    postgres_harness: Any, tmp_path: Path
) -> None:
    """UX study item 5, 18 Oct: work calls made from the phone dialer, not from a lead
    in the app, land on the lead's history and in the day's numbers. The phone sends
    only its leads' numbers; anything else is dropped here too, and nothing twice."""

    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path)
        try:
            await _organisation(setup)
            seller = await seed(setup.engine, tenant_id=setup.state.tenant_id, role="member")
            other = await seed(setup.engine, tenant_id=setup.state.tenant_id, role="member")
            seller_token = await _session(setup, seller)
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=setup.app), base_url=ORIGIN
            ) as client:

                def as_(token: str) -> None:
                    client.cookies.set(setup.settings.session_cookie_name, token)

                as_(setup.token)
                leads: dict[str, str] = {}
                for name, phone, owner in (
                    ("Ravi Kulkarni", "98765 43210", seller.person_id),
                    ("Meena Shah", "98765 43211", other.person_id),
                ):
                    added = await client.post(
                        f"{BASE}/leads",
                        json={
                            "command_id": str(uuid4()),
                            "name": name,
                            "phone": phone,
                            "assign": "person",
                            "person_id": str(owner),
                        },
                        headers=WRITE,
                    )
                    assert added.status_code == 201, added.text
                    leads[name] = added.json()["lead"]["lead_id"]

                as_(seller_token)
                book = await client.get(f"{BASE}/phone-book")
                assert book.status_code == 200, book.text
                # Only the seller's own lead: another seller's lead is not in their book.
                assert book.json()["numbers"] == ["+919876543210"]
                assert book.json()["person_id"] == str(seller.person_id)
                assert book.headers["cache-control"] == "private, no-store"

                now = datetime.now(UTC)
                device = str(uuid4())

                def row(log_id: str, number: str, minutes: float, **extra: Any) -> dict[str, Any]:
                    return {
                        "log_id": log_id,
                        "number": number,
                        "started_at": (now - timedelta(minutes=minutes)).isoformat(),
                        "duration_seconds": 0,
                        "direction": "outgoing",
                        **extra,
                    }

                calls = [
                    row("101", "098765 43210", 3, duration_seconds=192),
                    row("102", "+91 98765 43210", 2, direction="missed"),
                    row("103", "9876543211", 2),  # another seller's lead
                    row("104", "9123456789", 2),  # nobody's
                    row("105", "9876543210", 60 * 24 * 8),  # older than a week
                ]
                body = {"device_id": device, "calls": calls}
                refused = await client.post(f"{BASE}/phone-log", json=body)
                assert refused.status_code == 403
                sent = await client.post(f"{BASE}/phone-log", json=body, headers=WRITE)
                assert sent.status_code == 200, sent.text
                assert sent.json() | {"schema": None, "calls": None} == {
                    "schema": None,
                    "logged": 2,
                    "already": 0,
                    "skipped": 3,
                    "calls": None,
                }
                # Each row now on a lead names its call, so the phone can attach that
                # call's own recording to it (owner, 22 Oct 2026).
                refs = {ref["log_id"]: ref for ref in sent.json()["calls"]}
                assert sorted(refs) == ["101", "102"]
                assert {ref["lead_id"] for ref in refs.values()} == {leads["Ravi Kulkarni"]}
                assert (refs["101"]["connected"], refs["102"]["connected"]) == (True, False)
                # The phone sends the same rows again after a dropped connection.
                again = await client.post(f"{BASE}/phone-log", json=body, headers=WRITE)
                assert (again.json()["logged"], again.json()["already"]) == (0, 2)
                assert {ref["log_id"]: ref for ref in again.json()["calls"]} == refs

                # A call placed from the lead in the app is logged by its after-call sheet;
                # the same call found in the call history later is not counted twice.
                in_app = await client.post(
                    f"{BASE}/leads/{leads['Ravi Kulkarni']}/calls/phone",
                    json={"command_id": str(uuid4()), "duration_seconds": 40},
                    headers=WRITE,
                )
                assert in_app.status_code == 200, in_app.text
                same = await client.post(
                    f"{BASE}/phone-log",
                    json={
                        "device_id": device,
                        "calls": [row("106", "9876543210", 1, duration_seconds=31)],
                    },
                    headers=WRITE,
                )
                assert (same.json()["logged"], same.json()["already"]) == (0, 1)
                # Its recording is offered by the after-call sheet, not the call log.
                assert same.json()["calls"] == []

                detail = (await client.get(f"{BASE}/leads/{leads['Ravi Kulkarni']}")).json()
                phone_events = [event for event in detail["events"] if event.get("via")]
                assert [
                    (e["direction"], e["duration_seconds"], e["connected"]) for e in phone_events
                ] == [("missed", 0, False), ("outgoing", 192, True)]
                # Each sits at the time of the call, not the time it was sent.
                assert datetime.fromisoformat(phone_events[1]["at"]) < now - timedelta(minutes=2)
                # One call out from the dialer plus the app's own call.
                assert detail["lead"]["calls"] == 2
                assert detail["lead"]["stage"] == "new"
                assert detail["first_call_minutes"] == 0

                # The dialler call's recording, uploaded later, joins that call's row
                # (Redmi audit #55): no second "call" row, and the call count stays.
                ravi = leads["Ravi Kulkarni"]
                submission = str(uuid4())
                attached = await client.post(
                    f"{BASE}/leads/{ravi}/recordings",
                    json={
                        "command_id": str(uuid4()),
                        "submission_id": submission,
                        "call_event_id": refs["101"]["event_id"],
                    },
                    headers=WRITE,
                )
                assert attached.status_code == 200, attached.text
                calls_now = [e for e in attached.json()["events"] if e["kind"] == "call"]
                assert len(calls_now) == len([e for e in detail["events"] if e["kind"] == "call"])
                joined = next(e for e in calls_now if e.get("event_id") == refs["101"]["event_id"])
                assert (joined["via"], joined["recording"], joined["submission_id"]) == (
                    "phone",
                    True,
                    submission,
                )
                assert attached.json()["lead"]["calls"] == 2
                # A call that isn't on this lead is refused.
                stray = await client.post(
                    f"{BASE}/leads/{ravi}/recordings",
                    json={
                        "command_id": str(uuid4()),
                        "submission_id": str(uuid4()),
                        "call_event_id": str(uuid4()),
                    },
                    headers=WRITE,
                )
                assert stray.status_code == 404, stray.text
                # Without a call, a recording is still its own row, as before.
                loose = await client.post(
                    f"{BASE}/leads/{ravi}/recordings",
                    json={"command_id": str(uuid4()), "submission_id": str(uuid4())},
                    headers=WRITE,
                )
                assert loose.status_code == 200, loose.text
                assert sum(1 for e in loose.json()["events"] if e.get("recording")) == 2

                desk = (await client.get(BASE)).json()
                # The dialer call counts in My day; the missed call does not.
                assert desk["numbers"]["calls"] == 1
                assert desk["numbers"]["connected"] == 1
                assert desk["numbers"]["talk_seconds"] == 192 + 40

                as_(setup.token)
                team = (await client.get(f"{BASE}/team")).json()
                mine = next(
                    rep for rep in team["reps"] if rep["person_id"] == str(seller.person_id)
                )
                assert (mine["calls_today"], mine["connected_today"]) == (1, 1)
                assert len((await client.get(f"{BASE}/phone-book")).json()["numbers"]) == 2
        finally:
            await setup.engine.dispose()

    run(exercise())


def test_a_sellers_phone_setup_shows_on_team(postgres_harness: Any, tmp_path: Path) -> None:
    """UX study item 7, 18 Oct: the phone app reports its setup checklist; managers
    see each seller's phone on Team, with when its call history last came in. It is
    stored beside the workspace's settings without touching their revision."""

    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path)
        try:
            await _organisation(setup)
            seller = await seed(setup.engine, tenant_id=setup.state.tenant_id, role="member")
            seller_token = await _session(setup, seller)
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=setup.app), base_url=ORIGIN
            ) as client:

                def as_(token: str) -> None:
                    client.cookies.set(setup.settings.session_cookie_name, token)

                device = str(uuid4())
                checks = {
                    "calls": True,
                    "recordings": True,
                    "notifications": False,
                    "recorder": True,
                    "folder": True,
                    "battery": False,
                    "autostart": True,
                    "testCall": False,
                    "callLog": True,
                }
                report = {
                    "device_id": device,
                    "app_version": "0.3.20",
                    "family": "xiaomi",
                    "checks": checks,
                }
                as_(seller_token)
                assert (await client.post(f"{BASE}/me/phone", json=report)).status_code == 403
                odd = await client.post(
                    f"{BASE}/me/phone",
                    json={**report, "checks": {"wifi": True}},
                    headers=WRITE,
                )
                assert odd.status_code == 422
                sent = await client.post(f"{BASE}/me/phone", json=report, headers=WRITE)
                assert sent.status_code == 200, sent.text
                assert (sent.json()["done"], sent.json()["total"]) == (6, 9)
                assert sent.json()["synced_at"] is None
                # The 15-minute call-history look, with no new calls, says the phone is alive.
                seen = await client.post(
                    f"{BASE}/phone-log", json={"device_id": device, "calls": []}, headers=WRITE
                )
                assert seen.json()["logged"] == 0
                again = await client.post(
                    f"{BASE}/me/phone",
                    json={**report, "checks": {**checks, "battery": True}},
                    headers=WRITE,
                )
                assert again.json()["done"] == 7
                assert again.json()["synced_at"] is not None

                as_(setup.token)
                team = (await client.get(f"{BASE}/team")).json()
                rows = {rep["person_id"]: rep for rep in team["reps"]}
                phone = rows[str(seller.person_id)]["phone"]
                assert phone["family"] == "xiaomi" and phone["app_version"] == "0.3.20"
                assert phone["checks"]["battery"] is True and phone["checks"]["testCall"] is False
                assert phone["call_log_on"] is True and phone["synced_at"] is not None
                assert rows[str(setup.state.person_id)]["phone"] is None
                # A manager's settings save keeps every phone's report.
                revision = team["settings"]["revision"]
                saved = await client.put(
                    f"{BASE}/settings",
                    json={
                        "expected_revision": revision,
                        "auto_reassign": True,
                        "reassign_minutes": 15,
                    },
                    headers=WRITE,
                )
                assert saved.status_code == 200, saved.text
                after = {rep["person_id"]: rep for rep in saved.json()["reps"]}
                assert after[str(seller.person_id)]["phone"]["done"] == 7
                assert saved.json()["settings"]["revision"] == revision + 1
                # A report only moves the revision when it creates the settings row.
                as_(seller_token)
                await client.post(f"{BASE}/me/phone", json=report, headers=WRITE)
                as_(setup.token)
                assert (await client.get(f"{BASE}/team")).json()["settings"][
                    "revision"
                ] == revision + 1
        finally:
            await setup.engine.dispose()

    run(exercise())


def test_work_hours_hold_night_leads_and_keep_calls_on_the_phone(
    postgres_harness: Any, tmp_path: Path
) -> None:
    """Salestrail rows and UX study item 8, 18 Oct: a manager sets work hours. Outside
    them a new lead waits and goes to a seller when work starts, and a call is never
    logged. Clearing the hours gives out what waited."""
    from ac_platform.lead_desk import hours

    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path)
        try:
            await _organisation(setup)
            seller = await seed(setup.engine, tenant_id=setup.state.tenant_id, role="member")
            seller_token = await _session(setup, seller)
            today = datetime.now(hours.IST).weekday()
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=setup.app), base_url=ORIGIN
            ) as client:

                def as_(token: str) -> None:
                    client.cookies.set(setup.settings.session_cookie_name, token)

                as_(setup.token)
                await client.put(
                    f"{BASE}/team/{setup.state.person_id}",
                    json={"expected_revision": 0, "available": False, "max_open": 10},
                    headers=WRITE,
                )
                # Work only tomorrow, so right now is outside work hours.
                body = {
                    "expected_revision": 0,
                    "days": [(today + 1) % 7],
                    "start": "09:30",
                    "end": "19:00",
                    "pause_leads": True,
                }
                bad = await client.put(
                    f"{BASE}/work-hours", json={**body, "end": "08:00"}, headers=WRITE
                )
                assert bad.status_code == 422
                saved = await client.put(f"{BASE}/work-hours", json=body, headers=WRITE)
                assert saved.status_code == 200, saved.text
                view = saved.json()["settings"]["work_hours"]
                assert view["days"] == [(today + 1) % 7] and view["pause_leads"] is True
                assert view["inside"] is False and view["next_start"] is not None
                assert saved.json()["settings"]["revision"] == 1

                added = await client.post(
                    f"{BASE}/leads",
                    json={"command_id": str(uuid4()), "name": "Night Lead", "phone": "98765 40001"},
                    headers=WRITE,
                )
                lead = added.json()
                assert lead["lead"]["owner_person_id"] is None
                assert lead["owner_reason"].startswith("Outside work hours. It goes to a seller")

                as_(seller_token)
                desk = (await client.get(BASE)).json()
                assert desk["me"]["paused_until"] is not None
                book = (await client.get(f"{BASE}/phone-book")).json()
                assert book["work_hours"]["start"] == "09:30"
                # A call now is outside work hours: it is never logged.
                seller_lead = await client.post(
                    f"{BASE}/leads",
                    json={
                        "command_id": str(uuid4()),
                        "name": "Own Lead",
                        "phone": "98765 40002",
                        "assign": "me",
                    },
                    headers=WRITE,
                )
                assert seller_lead.status_code == 201, seller_lead.text
                logged = await client.post(
                    f"{BASE}/phone-log",
                    json={
                        "device_id": str(uuid4()),
                        "calls": [
                            {
                                "log_id": "1",
                                "number": "9876540002",
                                "started_at": datetime.now(UTC).isoformat(),
                                "duration_seconds": 30,
                                "direction": "outgoing",
                            }
                        ],
                    },
                    headers=WRITE,
                )
                assert (logged.json()["logged"], logged.json()["skipped"]) == (0, 1)

            # Work starts: the waiting lead goes to the seller.
            async with setup.sessions() as db, db.begin():
                start = datetime.fromisoformat(view["next_start"].replace("Z", "+00:00"))
                assert await hours.release_held(db, start + timedelta(minutes=1)) == 1
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=setup.app), base_url=ORIGIN
            ) as client:
                client.cookies.set(setup.settings.session_cookie_name, setup.token)
                detail = (await client.get(f"{BASE}/leads/{lead['lead']['lead_id']}")).json()
                assert detail["lead"]["owner_person_id"] == str(seller.person_id)
                assert detail["owner_reason"].startswith("Work hours started.")
                # Clearing the hours: nothing waits and every call counts again.
                cleared = await client.put(
                    f"{BASE}/work-hours",
                    json={"expected_revision": 1, "days": []},
                    headers=WRITE,
                )
                assert cleared.status_code == 200, cleared.text
                assert cleared.json()["settings"]["work_hours"] is None
                late = await client.post(
                    f"{BASE}/leads",
                    json={"command_id": str(uuid4()), "name": "Day Lead", "phone": "98765 40003"},
                    headers=WRITE,
                )
                assert late.json()["lead"]["owner_person_id"] == str(seller.person_id)
        finally:
            await setup.engine.dispose()

    run(exercise())


def test_a_missed_call_from_a_lead_waits_on_the_desk_until_called_back(
    postgres_harness: Any, tmp_path: Path
) -> None:
    """Salestrail's missed-call queue, 18 Oct: when a lead calls and nobody picks up, the
    seller's desk shows Call back with how many calls were missed; it clears when the
    seller calls them (from the app or the phone dialer)."""

    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path)
        try:
            await _organisation(setup)
            seller = await seed(setup.engine, tenant_id=setup.state.tenant_id, role="member")
            seller_token = await _session(setup, seller)
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=setup.app), base_url=ORIGIN
            ) as client:
                client.cookies.set(setup.settings.session_cookie_name, seller_token)
                added = await client.post(
                    f"{BASE}/leads",
                    json={
                        "command_id": str(uuid4()),
                        "name": "Asha Rao",
                        "phone": "98765 41111",
                        "assign": "me",
                    },
                    headers=WRITE,
                )
                lead_id = added.json()["lead"]["lead_id"]
                now = datetime.now(UTC)
                device = str(uuid4())

                async def phone(
                    log_id: str, minutes: int, direction: str, seconds: int = 0
                ) -> None:
                    sent = await client.post(
                        f"{BASE}/phone-log",
                        json={
                            "device_id": device,
                            "calls": [
                                {
                                    "log_id": log_id,
                                    "number": "9876541111",
                                    "started_at": (now - timedelta(minutes=minutes)).isoformat(),
                                    "duration_seconds": seconds,
                                    "direction": direction,
                                }
                            ],
                        },
                        headers=WRITE,
                    )
                    assert sent.json()["logged"] == 1, sent.text

                await phone("1", 4, "missed")
                await phone("2", 3, "rejected")
                desk = (await client.get(BASE)).json()
                assert desk["counts"]["call_back"] == 1
                [row] = desk["call_back"]
                assert row["lead_id"] == lead_id and row["missed_calls"] == 2
                assert datetime.fromisoformat(row["missed_at"]) < now - timedelta(minutes=2)
                # The badge counts them once: a new lead is due, and waits for a call back.
                assert (await client.get(f"{BASE}/badge")).json()["to_call"] == 1
                # Booked for later today, they still wait for a call back: still counted.
                async with setup.sessions() as db, db.begin():
                    await db.execute(
                        update(Lead)
                        .where(Lead.id == UUID(lead_id))
                        .values(stage="follow_up", next_action_at=now + timedelta(hours=3))
                    )
                assert (await client.get(f"{BASE}/badge")).json()["to_call"] == 1
                # The seller calls them back from the phone dialer: the row clears.
                await phone("3", 1, "outgoing", 45)
                desk = (await client.get(BASE)).json()
                assert desk["counts"]["call_back"] == 0 and desk["call_back"] == []
                assert (await client.get(f"{BASE}/badge")).json()["to_call"] == 0
        finally:
            await setup.engine.dispose()

    run(exercise())


def test_calls_by_seller_by_day(postgres_harness: Any, tmp_path: Path) -> None:
    """Build list row 18, 18 Oct: managers see each seller's calls per day (India time)
    for a date range, counted the way My day counts them; sellers can't read it."""
    from ac_platform.lead_desk import hours

    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path)
        try:
            await _organisation(setup)
            seller = await seed(setup.engine, tenant_id=setup.state.tenant_id, role="member")
            seller_token = await _session(setup, seller)
            today = datetime.now(hours.IST).date()
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=setup.app), base_url=ORIGIN
            ) as client:
                client.cookies.set(setup.settings.session_cookie_name, seller_token)
                await client.post(
                    f"{BASE}/leads",
                    json={
                        "command_id": str(uuid4()),
                        "name": "Asha Rao",
                        "phone": "98765 42222",
                        "assign": "me",
                    },
                    headers=WRITE,
                )
                now = datetime.now(UTC)
                calls = [
                    ("1", 3, "outgoing", 120),
                    ("2", 2, "outgoing", 0),
                    ("3", 1, "missed", 0),
                ]
                sent = await client.post(
                    f"{BASE}/phone-log",
                    json={
                        "device_id": str(uuid4()),
                        "calls": [
                            {
                                "log_id": log_id,
                                "number": "9876542222",
                                "started_at": (now - timedelta(minutes=ago)).isoformat(),
                                "duration_seconds": seconds,
                                "direction": direction,
                            }
                            for log_id, ago, direction, seconds in calls
                        ],
                    },
                    headers=WRITE,
                )
                assert sent.json()["logged"] == 3
                query = {"start": str(today - timedelta(days=1)), "end": str(today)}
                assert (await client.get(f"{BASE}/reports/calls", params=query)).status_code == 403

                client.cookies.set(setup.settings.session_cookie_name, setup.token)
                report = await client.get(f"{BASE}/reports/calls", params=query)
                assert report.status_code == 200, report.text
                rows = {row["person_id"]: row for row in report.json()["sellers"]}
                mine = rows[str(seller.person_id)]
                assert [day["day"] for day in mine["days"]] == [query["start"], query["end"]]
                assert mine["days"][1] == {
                    "day": query["end"],
                    "calls": 2,
                    "connected": 1,
                    "talk_seconds": 120,
                    "missed": 1,
                }
                assert (mine["calls"], mine["missed"]) == (2, 1)
                assert rows[str(setup.state.person_id)]["calls"] == 0
                too_long = {"start": str(today - timedelta(days=100)), "end": str(today)}
                assert (
                    await client.get(f"{BASE}/reports/calls", params=too_long)
                ).status_code == 422
                assert (
                    await client.get(f"{BASE}/reports/calls", params={"start": "soon"})
                ).status_code == 422
        finally:
            await setup.engine.dispose()

    run(exercise())


def test_a_seller_marks_a_phone_logged_call_private(postgres_harness: Any, tmp_path: Path) -> None:
    """Salestrail's untracked calls, 18 Oct: the seller hides a call their phone logged.
    It stays on the lead for them, marked private, and leaves My day, Team, the report
    and the lead for everyone else; marking it again shows it. Nothing is deleted."""
    from ac_platform.lead_desk import hours

    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path)
        try:
            await _organisation(setup)
            seller = await seed(setup.engine, tenant_id=setup.state.tenant_id, role="member")
            other = await seed(setup.engine, tenant_id=setup.state.tenant_id, role="member")
            seller_token = await _session(setup, seller)
            other_token = await _session(setup, other)
            today = str(datetime.now(hours.IST).date())
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=setup.app), base_url=ORIGIN
            ) as client:

                def as_(token: str) -> None:
                    client.cookies.set(setup.settings.session_cookie_name, token)

                as_(seller_token)
                added = await client.post(
                    f"{BASE}/leads",
                    json={
                        "command_id": str(uuid4()),
                        "name": "Personal Friend",
                        "phone": "98765 43333",
                        "assign": "me",
                    },
                    headers=WRITE,
                )
                lead_id = added.json()["lead"]["lead_id"]
                logged = await client.post(
                    f"{BASE}/phone-log",
                    json={
                        "device_id": str(uuid4()),
                        "calls": [
                            {
                                "log_id": "1",
                                "number": "9876543333",
                                "started_at": (
                                    datetime.now(UTC) - timedelta(minutes=2)
                                ).isoformat(),
                                "duration_seconds": 300,
                                "direction": "outgoing",
                            }
                        ],
                    },
                    headers=WRITE,
                )
                assert logged.json()["logged"] == 1
                detail = (await client.get(f"{BASE}/leads/{lead_id}")).json()
                [call] = [event for event in detail["events"] if event.get("via")]
                assert call["can_hide"] is True and call["private"] is False
                assert (await client.get(BASE)).json()["numbers"]["calls"] == 1

                as_(other_token)
                refused = await client.post(
                    f"{BASE}/calls/{call['event_id']}/private",
                    json={"command_id": str(uuid4()), "private": True},
                    headers=WRITE,
                )
                assert refused.status_code == 404

                as_(seller_token)
                hide = {"command_id": str(uuid4()), "private": True}
                hidden = await client.post(
                    f"{BASE}/calls/{call['event_id']}/private", json=hide, headers=WRITE
                )
                assert hidden.status_code == 200, hidden.text
                mine = [event for event in hidden.json()["events"] if event.get("via")]
                assert [event["private"] for event in mine] == [True]
                assert hidden.json()["lead"]["calls"] == 0
                # The same request again changes nothing.
                again = await client.post(
                    f"{BASE}/calls/{call['event_id']}/private", json=hide, headers=WRITE
                )
                assert again.status_code == 200
                assert (await client.get(BASE)).json()["numbers"]["calls"] == 0

                as_(setup.token)
                seen = (await client.get(f"{BASE}/leads/{lead_id}")).json()
                assert not [event for event in seen["events"] if event.get("via")]
                assert not [event for event in seen["events"] if event["kind"] == "edited"]
                team = {
                    rep["person_id"]: rep
                    for rep in (await client.get(f"{BASE}/team")).json()["reps"]
                }
                assert team[str(seller.person_id)]["calls_today"] == 0
                report = (
                    await client.get(f"{BASE}/reports/calls", params={"start": today, "end": today})
                ).json()
                assert {row["person_id"]: row["calls"] for row in report["sellers"]}[
                    str(seller.person_id)
                ] == 0

                as_(seller_token)
                shown = await client.post(
                    f"{BASE}/calls/{call['event_id']}/private",
                    json={"command_id": str(uuid4()), "private": False},
                    headers=WRITE,
                )
                assert shown.json()["lead"]["calls"] == 1
                assert (await client.get(BASE)).json()["numbers"]["calls"] == 1
                as_(setup.token)
                seen = (await client.get(f"{BASE}/leads/{lead_id}")).json()
                assert [event["direction"] for event in seen["events"] if event.get("via")] == [
                    "outgoing"
                ]
        finally:
            await setup.engine.dispose()

    run(exercise())


def test_the_account_sheet_reads_and_sets_taking_new_leads(
    postgres_harness: Any, tmp_path: Path
) -> None:
    """UX study item 8 leftover, 18 Oct: the account sheet reads the seller's own switch
    (GET /me) and changes it with the same PUT as the desk."""

    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path)
        try:
            await _organisation(setup)
            seller = await seed(setup.engine, tenant_id=setup.state.tenant_id, role="member")
            seller_token = await _session(setup, seller)
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=setup.app), base_url=ORIGIN
            ) as client:
                client.cookies.set(setup.settings.session_cookie_name, seller_token)
                me = await client.get(f"{BASE}/me")
                assert me.status_code == 200, me.text
                assert me.json()["taking_leads"] is True and me.json()["paused_until"] is None
                assert me.headers["cache-control"] == "private, no-store"
                off = await client.put(f"{BASE}/me/taking", json={"taking": False}, headers=WRITE)
                assert off.json()["taking_leads"] is False
                assert (await client.get(f"{BASE}/me")).json()["taking_leads"] is False
                assert (await client.get(f"{BASE}/me?x=1")).status_code == 422
        finally:
            await setup.engine.dispose()

    run(exercise())
