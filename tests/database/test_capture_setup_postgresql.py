"""Call capture setup through the HTTP API on PostgreSQL (owner, 30 Oct 2026: "simple clicks
and disclosure one by one, so that all our old as well as new users have to agree").

A seller in an organisation must go through it; agreeing is the standing consent (recorded
by /auto-analysis, never here); a phone that finished is recorded with its install id and
what it found, and only once the profile and consent are in place; a no is recorded and
asked again the next day; owners, admins and managers see everyone's state in Team. A
personal workspace is never required. Fictional people only.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import delete, select, update

from ac_platform.audit.models import AuditEvent
from ac_platform.call_ai import capture_setup
from ac_platform.call_ai.capture_setup_http import install_capture_setup_http
from ac_platform.call_ai.http import install_call_ai_http
from ac_platform.http.routes import RouteContext
from ac_platform.identity.sales_xray_profile_models import SalesXrayProfile
from ac_platform.lead_desk import connected_apps
from ac_platform.lead_desk.models import LeadDeskSettings
from ac_platform.lead_desk.store import PHONES_KEY
from ac_platform.tenancy.models import Membership
from tests.database.test_conversation_account_library_postgresql import _session
from tests.database.test_conversation_postgresql import postgres_harness as _postgres_harness
from tests.database.test_conversation_postgresql import run, seed
from tests.database.test_conversation_submission_http_postgresql import ORIGIN, PREFIX, _setup
from tests.database.test_lead_desk_postgresql import _organisation

WRITE = {"Origin": ORIGIN, "Content-Type": "application/json"}
AUTO = "/v1/sales-xray/call-ai/auto-analysis"
SETUP = "/v1/sales-xray/call-ai/capture-setup"
PHONE = {
    "device": "install-fictional-1",
    "model": "Redmi 13",
    "family": "xiaomi",
    "app_version": "1.0.50",
    "recordings": True,
    "background": True,
    "uploads": True,
}


@pytest.fixture
def postgres_harness() -> Any:
    yield from cast(Any, _postgres_harness).__wrapped__()


def _install(setup: Any) -> None:
    settings = setup.settings.model_copy(update={"public_learner_tenant_id": uuid4()})
    context = RouteContext(settings, setup.require_actor, setup.sessions)
    install_call_ai_http(setup.app, context)
    install_capture_setup_http(setup.app, context)


async def _agree(client: httpx.AsyncClient) -> httpx.Response:
    shown = (await client.get(AUTO)).json()["notice"]
    terms = (await client.get(PREFIX + "/upload-policy")).json()["policy_sha256"]
    return await client.post(
        AUTO,
        json={
            "decision": "granted",
            "policy_sha256": shown["policy_sha256"],
            "upload_policy_sha256": terms,
            "language": "en",
        },
        headers=WRITE,
    )


async def _events(setup: Any, person: UUID) -> list[AuditEvent]:
    async with setup.sessions() as db:
        rows = await db.scalars(
            select(AuditEvent)
            .where(
                AuditEvent.tenant_id == setup.state.tenant_id,
                AuditEvent.resource_type == capture_setup.RESOURCE_TYPE,
                AuditEvent.resource_id == str(person),
            )
            .order_by(AuditEvent.sequence_no)
        )
        return list(rows.all())


def test_a_seller_agrees_finishes_on_a_phone_and_team_sees_it(
    postgres_harness: Any, tmp_path: Path
) -> None:
    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path)
        try:
            await _organisation(setup)  # the signed-in person is an admin here
            _install(setup)
            seller = await seed(setup.engine, tenant_id=setup.state.tenant_id, role="member")
            seller_token = await _session(setup, seller)
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=setup.app), base_url=ORIGIN
            ) as client:

                def as_(token: str) -> None:
                    client.cookies.clear()
                    client.cookies.set(setup.settings.session_cookie_name, token)

                as_(seller_token)
                first = await client.get(SETUP)
                assert first.status_code == 200, first.text
                assert first.headers["cache-control"] == "private, no-store"
                assert first.json() == {
                    "schema": "sales-xray-capture-setup/1",
                    "workspace": "organisation",
                    "required": True,
                    "profile_complete": True,
                    "consent": "ask",
                    "consent_since": None,
                    "declined_at": None,
                    "ask_again_at": None,
                    "phones": [],
                    "finished_devices": [],
                }

                # A phone can't claim to be finished before the seller agreed.
                early = await client.post(
                    SETUP, json={"outcome": "completed", "phone": PHONE}, headers=WRITE
                )
                assert early.status_code == 409
                assert "Agree to call capture first" in early.text
                # Nor from another site, nor without its install id.
                elsewhere = await client.post(
                    SETUP,
                    json={"outcome": "declined"},
                    headers={"Content-Type": "application/json"},
                )
                assert elsewhere.status_code == 403
                assert (await _agree(client)).status_code == 200
                bare = await client.post(SETUP, json={"outcome": "completed"}, headers=WRITE)
                assert bare.status_code == 422

                # Agreed through /auto-analysis: this API records the phone, twice-tapped once.
                once = {**WRITE, "Idempotency-Key": str(uuid4())}
                for _ in range(2):
                    done = await client.post(
                        SETUP,
                        json={"outcome": "completed", "phone": {**PHONE, "number": "+1555"}},
                        headers=once,
                    )
                    assert done.status_code == 422  # unknown fields are refused
                for _ in range(2):
                    done = await client.post(
                        SETUP, json={"outcome": "completed", "phone": PHONE}, headers=once
                    )
                    assert done.status_code == 200, done.text
                view = done.json()
                assert view["consent"] == "on"
                assert [phone["device"] for phone in view["phones"]] == ["install-fictional-1"]
                # The install is done for this person in every workspace (ph2-15).
                assert view["finished_devices"] == ["install-fictional-1"]
                assert view["phones"][0]["uploads"] is True
                events = await _events(setup, seller.person_id)
                assert len(events) == 1
                assert events[0].action == capture_setup.ACTION
                assert events[0].actor_person_id == seller.person_id
                assert events[0].payload["outcome"] == "completed"
                assert "number" not in events[0].payload

                # Agreed, so a no is refused: it is turned off in Settings, Privacy.
                no = await client.post(SETUP, json={"outcome": "declined"}, headers=WRITE)
                assert no.status_code == 409

                # A member can't read Team; an admin reads everyone who sells.
                assert (await client.get(SETUP + "/team")).status_code == 403
                as_(setup.token)
                team = await client.get(SETUP + "/team")
                assert team.status_code == 200, team.text
                rows = {row["person_id"]: row for row in team.json()["people"]}
                assert rows[str(seller.person_id)]["state"] == "set_up"
                assert rows[str(seller.person_id)]["phone"] == "Redmi 13"
                assert rows[str(setup.state.person_id)]["state"] == "not_started"
                # Who still needs it comes first.
                assert team.json()["people"][-1]["state"] == "set_up"
                assert set(rows[str(seller.person_id)]) == {
                    "person_id",
                    "name",
                    "role",
                    "state",
                    "at",
                    "phone",
                    "missing_today",
                    "call_log_off",
                    "recording",
                }
                # No lead calls today: nothing without a recording, each or in all.
                assert team.json()["missing_today"] == 0
                assert rows[str(seller.person_id)]["missing_today"] == 0
                assert team.json()["call_log_off"] == 0

                # ph1-23: one rule for Team and Connections. A Play build never reports
                # call logging (never "off"); a phone that can and has it off is named.
                name = rows[str(seller.person_id)]["name"]
                for checks, off in (({"calls": True}, None), ({"callLog": False}, "Redmi 13")):
                    async with setup.sessions() as db, db.begin():
                        desk = await db.get(LeadDeskSettings, setup.state.tenant_id)
                        report = {
                            str(seller.person_id): {
                                "device_id": PHONE["device"],
                                "family": "xiaomi",
                                "checks": checks,
                                "reported_at": datetime.now(UTC).isoformat(),
                            }
                        }
                        if desk is None:
                            db.add(
                                LeadDeskSettings(
                                    tenant_id=setup.state.tenant_id,
                                    revision=1,
                                    config={PHONES_KEY: report},
                                    updated_by_person_id=None,
                                    updated_at=datetime.now(UTC),
                                )
                            )
                        else:
                            desk.config = {**desk.config, PHONES_KEY: report}
                    team = await client.get(SETUP + "/team")
                    row = next(
                        row
                        for row in team.json()["people"]
                        if row["person_id"] == str(seller.person_id)
                    )
                    assert row["call_log_off"] == off
                    assert team.json()["call_log_off"] == (1 if off else 0)
                    async with setup.sessions() as db:
                        health = await connected_apps._phones(db, setup.state.tenant_id)
                    assert health.state == ("problem" if off else "ready")
                    line = health.connections[0]
                    assert line.label == f"{name} · Redmi 13"
                    if off:
                        assert health.words == f"Call logging is off on {name}'s Redmi 13."
                        assert line.fix is not None and line.fix.path == "/settings/selling"
                    else:
                        assert health.words == "1 phone logging calls."
                        assert line.fix is None

                # Teardown #7: the seller's phone says when it last found a call recording
                # (never the file or a number), and Team shows the line and its fix.
                assert row["recording"] == {"state": "late", "last_at": None, "fix": "test"}
                as_(seller_token)
                last = datetime.now(UTC) - timedelta(minutes=12)
                told = await client.post(
                    SETUP + "/recording-health",
                    json={"device": PHONE["device"], "newest_recording_at": last.isoformat()},
                    headers=WRITE,
                )
                assert told.status_code == 200, told.text
                assert (
                    await client.post(
                        SETUP + "/recording-health",
                        json={"device": PHONE["device"], "file": "call.mp3"},
                        headers=WRITE,
                    )
                ).status_code == 422
                as_(setup.token)
                team = await client.get(SETUP + "/team")
                row = next(
                    row
                    for row in team.json()["people"]
                    if row["person_id"] == str(seller.person_id)
                )
                assert row["recording"]["state"] == "ok"
                assert row["recording"]["fix"] is None
                assert row["recording"]["last_at"].startswith(last.isoformat()[:16])
                as_(seller_token)
                mine = await client.get(SETUP + "/missing")
                assert mine.status_code == 200, mine.text
                assert mine.json() == {
                    "schema": "sales-xray-missing-recordings/1",
                    "calls": 0,
                    "tried": 0,
                    "latest_at": None,
                }
        finally:
            await setup.engine.dispose()

    run(exercise())


def test_a_no_is_recorded_and_asked_again_the_next_day(
    postgres_harness: Any, tmp_path: Path
) -> None:
    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path)
        try:
            await _organisation(setup)
            _install(setup)
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=setup.app), base_url=ORIGIN
            ) as client:
                client.cookies.set(setup.settings.session_cookie_name, setup.token)
                said_no = await client.post(
                    SETUP,
                    json={"outcome": "declined"},
                    headers={**WRITE, "Idempotency-Key": str(uuid4())},
                )
                assert said_no.status_code == 200, said_no.text
                view = said_no.json()
                assert view["consent"] == "ask"
                declined = datetime.fromisoformat(view["declined_at"])
                assert datetime.fromisoformat(view["ask_again_at"]) == declined + timedelta(days=1)
                # Saying no records no consent either way.
                assert (await client.get(AUTO)).json()["state"] == "ask"
                team = (await client.get(SETUP + "/team")).json()["people"]
                assert [row["state"] for row in team] == ["declined"]

                # Agreeing later, then turning it off in Privacy, counts as the newest no.
                assert (await _agree(client)).status_code == 200
                await client.post(AUTO, json={"decision": "withdrawn"}, headers=WRITE)
                off = (await client.get(SETUP)).json()
                assert off["consent"] == "off"
                assert datetime.fromisoformat(off["declined_at"]) >= declined
                team = (await client.get(SETUP + "/team")).json()["people"]
                assert [row["state"] for row in team] == ["turned_off"]
        finally:
            await setup.engine.dispose()

    run(exercise())


def test_a_phone_needs_the_name_and_phone_first(postgres_harness: Any, tmp_path: Path) -> None:
    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path)
        try:
            await _organisation(setup)
            _install(setup)
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=setup.app), base_url=ORIGIN
            ) as client:
                client.cookies.set(setup.settings.session_cookie_name, setup.token)
                assert (await _agree(client)).status_code == 200
                async with setup.sessions() as db, db.begin():
                    await db.execute(
                        delete(SalesXrayProfile).where(
                            SalesXrayProfile.person_id == setup.state.person_id
                        )
                    )
                view = (await client.get(SETUP)).json()
                assert view["profile_complete"] is False
                refused = await client.post(
                    SETUP, json={"outcome": "completed", "phone": PHONE}, headers=WRITE
                )
                assert refused.status_code == 403
                assert "name and phone number" in refused.text
                assert await _events(setup, setup.state.person_id) == []
        finally:
            await setup.engine.dispose()

    run(exercise())


def test_viewers_and_personal_workspaces_are_never_required(
    postgres_harness: Any, tmp_path: Path
) -> None:
    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path)
        try:
            _install(setup)  # no organisation yet: the person's own workspace
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=setup.app), base_url=ORIGIN
            ) as client:
                client.cookies.set(setup.settings.session_cookie_name, setup.token)
                personal = await client.get(SETUP)
                assert personal.status_code == 200, personal.text
                assert personal.json() == {
                    "schema": "sales-xray-capture-setup/1",
                    "workspace": "personal",
                    "required": False,
                    "consent": "unavailable",
                    "declined_at": None,
                    "ask_again_at": None,
                    "phones": [],
                }
                refused = await client.post(SETUP, json={"outcome": "declined"}, headers=WRITE)
                assert refused.status_code == 403

                await _organisation(setup)
                async with setup.sessions() as db, db.begin():
                    await db.execute(
                        update(Membership)
                        .where(Membership.person_id == setup.state.person_id)
                        .values(role="viewer")
                    )
                viewer = (await client.get(SETUP)).json()
                assert (viewer["workspace"], viewer["required"]) == ("organisation", False)
                assert (await client.get(SETUP + "/team")).status_code == 403
        finally:
            await setup.engine.dispose()

    run(exercise())
