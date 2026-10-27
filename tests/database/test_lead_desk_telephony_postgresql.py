"""Company-number calls through the CRM's API on PostgreSQL, with the provider faked.

The owner turns calling on with the company number; a seller adds their mobile; a lead
from an imported list is refused (call from your own phone) while a lead who asked is
called: the seller's phone first, then the lead with the recording notice, the company
number showing. The provider's webhook ends the call; the call lands on the lead's
history as the seller's, with its talk time; the recording goes to the seller's app with
its fingerprint on record; another seller can't see the call; a phone that's switched off
is said plainly; and once the month's budget is spent, calling pauses.
"""

from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import select, update

from ac_platform.audit.models import AuditEvent
from ac_platform.http.routes import RouteContext
from ac_platform.lead_desk.models import Lead, LeadDeskSettings, LeadEvent
from ac_platform.lead_desk.telephony import ledger, policy, providers
from ac_platform.lead_desk.telephony.http import install_telephony_http, sign
from tests.database.test_conversation_account_library_postgresql import _session
from tests.database.test_conversation_postgresql import postgres_harness as _postgres_harness
from tests.database.test_conversation_postgresql import run, seed
from tests.database.test_conversation_submission_http_postgresql import ORIGIN, _setup
from tests.database.test_lead_desk_postgresql import _organisation

WRITE = {"Origin": ORIGIN, "Content-Type": "application/json"}
BASE = "/v1/lead-desk"
SECRET = "hook-secret"  # noqa: S105 - a stand-in for the test
RECORDING = "https://recordings.exotel.com/exotelrecordings/fictional/exo-1.mp3"


@pytest.fixture
def postgres_harness() -> Any:
    yield from cast(Any, _postgres_harness).__wrapped__()


class ScriptedProvider:
    """Exotel as the test tells it to answer."""

    name = "exotel"
    label = "Exotel"
    real = True

    def __init__(self) -> None:
        self.placed: list[providers.BridgeRequest] = []
        self.reports: dict[str, providers.CallReport] = {}
        self.refuse: providers.TelephonyError | None = None

    async def start_bridge(self, request: providers.BridgeRequest) -> providers.ProviderCall:
        if self.refuse is not None:
            raise self.refuse
        self.placed.append(request)
        sid = f"exo-{len(self.placed)}"
        self.reports[sid] = providers.CallReport(sid=sid, status="ringing")
        return providers.ProviderCall(sid=sid, status="queued")

    async def report(self, sid: str) -> providers.CallReport:
        return self.reports[sid]

    async def fetch_recording(self, url: str) -> providers.Recording:
        assert url == RECORDING
        return providers.Recording(b"ID3fictional-audio", "audio/mpeg")


def test_a_company_number_call_from_setup_to_the_leads_history(
    postgres_harness: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = ScriptedProvider()
    monkeypatch.setattr(
        providers, "provider_from_env", lambda env=None, *, environment, client=None: fake
    )
    monkeypatch.setenv("AC_TELEPHONY_TEST_NUMBERS", "+919800000001,+919800000002,+919800000003")
    monkeypatch.setenv("AC_TELEPHONY_WEBHOOK_SECRET", SECRET)

    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path)
        try:
            await _organisation(setup)
            tenant = setup.state.tenant_id
            settings = setup.settings.model_copy(update={"public_learner_tenant_id": uuid4()})
            install_telephony_http(
                setup.app, RouteContext(settings, setup.require_actor, setup.sessions)
            )
            other = await seed(setup.engine, tenant_id=tenant, role="member")
            other_token = await _session(setup, other)
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=setup.app), base_url=ORIGIN
            ) as client:

                def as_(token: str) -> None:
                    client.cookies.set(setup.settings.session_cookie_name, token)

                as_(setup.token)
                # ----- not offered until staff list the organisation -----
                hidden = await client.get(f"{BASE}/calling")
                assert hidden.status_code == 200, hidden.text
                assert hidden.json()["available"] is False
                monkeypatch.setenv("AC_TELEPHONY_TENANTS", str(tenant))

                # ----- the owner turns it on; the seller adds their mobile -----
                view = (await client.get(f"{BASE}/calling")).json()
                assert view["available"] is True and view["on"] is False
                assert view["blockers"][0] == policy.OFF.words
                assert view["notice"]["text"] == "This call is recorded, for quality and training."
                assert [s["key"] for s in view["sources"] if s["on"]] == ["meta", "webhook"]
                assert "rate" not in str(view).lower() and "paise" not in str(view).lower()
                body = {"on": True, "number": "020 0000 0000"}
                refused = await client.put(f"{BASE}/calling", json=body)
                assert refused.status_code == 403  # no Origin: not from our page
                saved = await client.put(f"{BASE}/calling", json=body, headers=WRITE)
                assert saved.status_code == 200, saved.text
                assert saved.json()["number"] == "+912000000000"
                assert saved.json()["blockers"] == [policy.NO_MOBILE.words]
                mine = await client.put(
                    f"{BASE}/calling/me", json={"mobile": "98000 00001"}, headers=WRITE
                )
                assert mine.status_code == 200, mine.text
                ready = mine.json()
                assert ready["myMobile"] == "+919800000001"
                assert ready["ready"] is True and ready["testOnly"] is True
                assert ready["provider"] == "Exotel"
                as_(other_token)
                seller_view = await client.put(f"{BASE}/calling", json=body, headers=WRITE)
                assert seller_view.status_code == 403  # only managers set it up
                as_(setup.token)

                # ----- a lead who asked, and one from an imported list -----
                leads: dict[str, str] = {}
                for name, phone in (("Asha Patil", "98000 00002"), ("Cold Caller", "98000 00003")):
                    added = await client.post(
                        f"{BASE}/leads",
                        json={"command_id": str(uuid4()), "name": name, "phone": phone},
                        headers=WRITE,
                    )
                    assert added.status_code == 201, added.text
                    leads[name] = added.json()["lead"]["lead_id"]
                asked, cold = leads["Asha Patil"], leads["Cold Caller"]
                async with setup.sessions() as db, db.begin():
                    await db.execute(
                        update(Lead).where(Lead.id == UUID(asked)).values(source="webhook")
                    )
                    await db.execute(update(Lead).where(Lead.id == UUID(cold)).values(source="csv"))
                ok = (await client.get(f"{BASE}/calling/leads/{asked}")).json()
                assert ok == {"available": True, "reason": None, "words": None}
                no = (await client.get(f"{BASE}/calling/leads/{cold}")).json()
                assert no["available"] is False and no["reason"] == "not_asked"
                turned_away = await client.post(
                    f"{BASE}/leads/{cold}/calls/company",
                    json={"commandId": str(uuid4())},
                    headers=WRITE,
                )
                assert turned_away.status_code == 409
                assert turned_away.headers["x-company-call-refused"] == "not_asked"
                assert "own phone" in turned_away.json()["detail"]
                assert fake.placed == []

                # ----- the call: the seller's phone first, then the lead -----
                command = str(uuid4())
                started = await client.post(
                    f"{BASE}/leads/{asked}/calls/company",
                    json={"commandId": command},
                    headers=WRITE,
                )
                assert started.status_code == 200, started.text
                call = started.json()
                assert call["status"] == "queued" and call["final"] is False
                again = await client.post(
                    f"{BASE}/leads/{asked}/calls/company",
                    json={"commandId": command},
                    headers=WRITE,
                )
                assert again.json()["id"] == call["id"] and len(fake.placed) == 1
                bridge = fake.placed[0]
                assert (bridge.seller, bridge.lead, bridge.caller_id) == (
                    "+919800000001",
                    "+919800000002",
                    "+912000000000",
                )
                hook = f"{BASE}/telephony/exotel/status/{tenant}/{call['id']}/"
                assert (
                    bridge.status_url == f"{ORIGIN}{hook}{sign(SECRET, tenant, UUID(call['id']))}"
                )
                assert bridge.notice_url == (
                    f"{ORIGIN}{BASE}/telephony/notice/recording-notice-en-v1.wav"
                )
                assert 60 <= bridge.time_limit <= policy.MAX_CALL_SECONDS
                ringing = (await client.get(f"{BASE}/calls/company/{call['id']}")).json()
                assert ringing["status"] == "ringing"

                # ----- the provider's webhook ends it; its API has the last word -----
                fake.reports["exo-1"] = providers.CallReport(
                    sid="exo-1",
                    status="completed",
                    seller_answered=True,
                    lead_answered=True,
                    talk_seconds=187,
                    total_seconds=212,
                    leg_seconds=(205, 187),
                    recording_url=RECORDING,
                )
                forged = await client.post(f"{hook}{'0' * 32}", json={"Status": "completed"})
                assert forged.status_code == 404
                nudged = await client.post(
                    f"{hook}{sign(SECRET, tenant, UUID(call['id']))}",
                    json={"CallSid": "exo-1", "Status": "completed"},
                )
                assert nudged.status_code == 200 and nudged.json() == {"call": "final"}
                done = (await client.get(f"{BASE}/calls/company/{call['id']}")).json()
                assert done["final"] is True and done["connected"] is True
                assert done["talkSeconds"] == 187 and done["recording"] is True
                assert done["eventId"] is not None

                # ----- on the lead's history, as the seller's call -----
                async with setup.sessions() as db:
                    lead = await db.get(Lead, UUID(asked))
                    assert lead is not None and lead.calls == 1 and lead.last_contact_at
                    event = await db.get(LeadEvent, UUID(done["eventId"]))
                    assert event is not None and event.kind == "call"
                    assert event.actor_person_id == setup.state.person_id
                    assert event.data["via"] == "company" and event.data["connected"] is True
                    assert event.data["duration_seconds"] == 187
                detail = (await client.get(f"{BASE}/leads/{asked}")).json()
                calls = [e for e in detail["events"] if e["kind"] == "call"]
                assert len(calls) == 1
                seconds = calls[0].get("duration_seconds", calls[0].get("durationSeconds"))
                assert seconds == 187

                # ----- the recording goes to the seller's app, its fingerprint on record -----
                recording = await client.get(f"{BASE}/calls/company/{call['id']}/recording")
                assert recording.status_code == 200, recording.text
                assert recording.content == b"ID3fictional-audio"
                assert recording.headers["content-type"] == "audio/mpeg"
                assert recording.headers["cache-control"].startswith("private")
                async with setup.sessions() as db:
                    actions = (
                        await db.scalars(
                            select(AuditEvent.action)
                            .where(
                                AuditEvent.tenant_id == tenant,
                                AuditEvent.resource_type == ledger.RESOURCE_TYPE,
                                AuditEvent.resource_id == call["id"],
                            )
                            .order_by(AuditEvent.sequence_no)
                        )
                    ).all()
                assert actions[0] == ledger.REQUESTED and actions[1] == ledger.PLACED
                assert actions[-1] == ledger.RECORDING
                as_(other_token)
                stranger = await client.get(f"{BASE}/calls/company/{call['id']}")
                assert stranger.status_code == 404
                as_(setup.token)

                # ----- a phone that's switched off, said plainly -----
                fake.refuse = providers.TelephonyError(
                    "Your phone seems to be switched off. Turn it on, then call again.",
                    status=409,
                    code="1012",
                )
                off = await client.post(
                    f"{BASE}/leads/{asked}/calls/company",
                    json={"commandId": str(uuid4())},
                    headers=WRITE,
                )
                assert off.status_code == 409 and "switched off" in off.json()["detail"]
                fake.refuse = None

                # ----- the month's budget spent (the call cost 700 paise at the careful rate):
                # calling pauses, with no amounts shown -----
                async with setup.sessions() as db, db.begin():
                    row = await db.get(LeadDeskSettings, tenant)
                    assert row is not None
                    row.config = {**row.config, policy.LIMITS_KEY: {"monthly_paise": 800}}
                paused = (await client.get(f"{BASE}/calling/leads/{asked}")).json()
                assert paused["reason"] == "paused"
                stopped = await client.post(
                    f"{BASE}/leads/{asked}/calls/company",
                    json={"commandId": str(uuid4())},
                    headers=WRITE,
                )
                assert stopped.status_code == 409
                assert stopped.headers["x-company-call-refused"] == "paused"
                settings_view = (await client.get(f"{BASE}/calling")).json()
                assert settings_view["paused"].startswith("Paused until the 1st")
                assert "₹" not in str(settings_view) and len(fake.placed) == 1

                # ----- the notice the lead hears -----
                notice = await client.get(f"{BASE}/telephony/notice/recording-notice-en-v1.wav")
                assert notice.status_code == 200 and notice.content[:4] == b"RIFF"
                assert (await client.get(f"{BASE}/telephony/notice/other.wav")).status_code == 404
        finally:
            await setup.engine.dispose()

    run(exercise())
