"""A business's own lead stages through the Sales Xray CRM's HTTP API on PostgreSQL.

A real-estate business picks its profile; a seller records a call as "Site visit
booked" (one of the business's stages); an old client without a step still records
Follow-up and lands in the business's stage for it; a manager moves the lead to "Site
visit done" without a call; history and lists use the business's words; the call's
result event keeps every key it had before.
"""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import select, update

from ac_platform.http.routes import RouteContext
from ac_platform.lead_desk.http import install_lead_desk_http
from ac_platform.lead_desk.journey.http import install_journey_http
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
    context = RouteContext(settings, setup.require_actor, setup.sessions)
    install_lead_desk_http(setup.app, context)
    install_journey_http(setup.app, context)


def test_a_business_own_stages_through_the_desk(postgres_harness: Any, tmp_path: Path) -> None:
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

                as_(setup.token)
                first = (await client.get(f"{BASE}/journey")).json()
                assert first["version"] == 0
                assert [s["key"] for s in first["stages"]][:3] == [
                    "new",
                    "not_connected",
                    "follow_up",
                ]
                # A member can read the stages but can't change them.
                as_(seller_token)
                assert (await client.get(f"{BASE}/journey")).status_code == 200
                refused = await client.post(
                    f"{BASE}/journey/template",
                    json={"expectedVersion": 0, "template": "real_estate"},
                    headers=WRITE,
                )
                assert refused.status_code == 403
                as_(setup.token)
                picked = await client.post(
                    f"{BASE}/journey/template",
                    json={"expectedVersion": 0, "template": "real_estate"},
                    headers=WRITE,
                )
                assert picked.status_code == 200, picked.text
                assert picked.json()["industry"] == "real_estate"

                await client.put(
                    f"{BASE}/team/{seller.person_id}",
                    json={"expected_revision": 0, "available": True, "max_open": 10},
                    headers=WRITE,
                )
                await client.put(
                    f"{BASE}/team/{setup.state.person_id}",
                    json={"expected_revision": 0, "available": False, "max_open": 10},
                    headers=WRITE,
                )
                added = await client.post(
                    f"{BASE}/leads",
                    json={
                        "command_id": str(uuid4()),
                        "name": "Fictional Buyer",
                        "phone": "98765 43210",
                    },
                    headers=WRITE,
                )
                assert added.status_code == 201, added.text
                lead = added.json()["lead"]
                assert lead["stage_label"] == "New enquiry" and lead["step"] == "new"

                as_(seller_token)
                detail = (await client.get(f"{BASE}/leads/{lead['lead_id']}")).json()
                labels = [choice["label"] for choice in detail["stage_choices"]]
                assert labels[:3] == ["Contacted", "Site visit booked", "Site visit done"]
                assert "Couldn't reach" not in labels and "New enquiry" not in labels

                later = (datetime.now(UTC) + timedelta(days=1)).isoformat()
                booked = await client.post(
                    f"{BASE}/leads/{lead['lead_id']}/dispose",
                    json={
                        "command_id": str(uuid4()),
                        "expected_revision": detail["lead"]["revision"],
                        "connected": True,
                        "step": "site_visit_booked",
                        "follow_up_at": later,
                    },
                    headers=WRITE,
                )
                assert booked.status_code == 200, booked.text
                row = booked.json()["lead"]
                assert (row["stage"], row["step"], row["stage_label"]) == (
                    "interested",
                    "site_visit_booked",
                    "Site visit booked",
                )
                history = booked.json()["events"]
                assert history[0]["kind"] == "result"
                assert history[0]["stage_label"] == "Site visit booked"

                # An archived or unknown stage is refused; so is Couldn't reach after a talk.
                for step in ("interested_old", "not_connected"):
                    wrong = await client.post(
                        f"{BASE}/leads/{lead['lead_id']}/dispose",
                        json={
                            "command_id": str(uuid4()),
                            "expected_revision": row["revision"],
                            "connected": True,
                            "step": step,
                            "follow_up_at": later,
                        },
                        headers=WRITE,
                    )
                    assert wrong.status_code == 422, (step, wrong.text)

                # A client that sends no step (the phone app) behaves as before.
                plain = await client.post(
                    f"{BASE}/leads/{lead['lead_id']}/dispose",
                    json={
                        "command_id": str(uuid4()),
                        "expected_revision": row["revision"],
                        "connected": True,
                        "stage": "follow_up",
                        "follow_up_at": later,
                    },
                    headers=WRITE,
                )
                assert plain.status_code == 200, plain.text
                row = plain.json()["lead"]
                assert (row["stage"], row["step"], row["stage_label"]) == (
                    "follow_up",
                    "contacted",
                    "Contacted",
                )

                command = str(uuid4())
                moved = await client.post(
                    f"{BASE}/leads/{lead['lead_id']}/stage",
                    json={
                        "commandId": command,
                        "expectedRevision": row["revision"],
                        "step": "site_visit_done",
                        "note": "Visited the 2 BHK on Saturday",
                    },
                    headers=WRITE,
                )
                assert moved.status_code == 200, moved.text
                assert moved.json()["stepLabel"] == "Site visit done"
                again = await client.post(
                    f"{BASE}/leads/{lead['lead_id']}/stage",
                    json={
                        "commandId": command,
                        "expectedRevision": row["revision"],
                        "step": "site_visit_done",
                    },
                    headers=WRITE,
                )
                assert (
                    again.status_code == 200
                    and again.json()["revision"] == moved.json()["revision"]
                )
                detail = (await client.get(f"{BASE}/leads/{lead['lead_id']}")).json()
                assert detail["lead"]["stage_label"] == "Site visit done"
                assert detail["events"][0]["kind"] == "stage"
                assert detail["events"][0]["stage_label"] == "Site visit done"

            async with setup.sessions() as db:
                stored = await db.scalar(select(Lead).where(Lead.id == UUID(lead["lead_id"])))
                assert stored is not None and stored.step == "site_visit_done"
                results = (
                    await db.scalars(
                        select(LeadEvent)
                        .where(LeadEvent.lead_id == stored.id, LeadEvent.kind == "result")
                        .order_by(LeadEvent.created_at)
                    )
                ).all()
                # The result event keeps every key it had, with the stage keys beside them.
                for event in results:
                    for key in (
                        "connected",
                        "stage",
                        "from_stage",
                        "reason",
                        "follow_up_at",
                        "remark",
                        "deal_value",
                        "was_due",
                        "step",
                        "from_step",
                        "step_label",
                    ):
                        assert key in event.data, key
                assert results[0].data["step"] == "site_visit_booked"
                assert results[-1].data["step"] is None and results[-1].data["step_label"] is None
        finally:
            await setup.engine.dispose()

    run(exercise())
