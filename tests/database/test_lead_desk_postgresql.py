"""Sales Xray CRM (Lead Desk) through its HTTP API on PostgreSQL.

One seller's day: rules route a Hindi lead to the Hindi speaker with a reason,
a repeat enquiry is "asked again" (never a duplicate), the desk queues it,
Start calling serves it, and NeoDove's dispose screen moves it on. Managers
alone see the team; a website form posts with its own key; files import.
"""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

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
        finally:
            await setup.engine.dispose()

    run(exercise())
