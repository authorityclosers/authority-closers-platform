"""Lead events and customer hand-overs end to end on disposable loopback PostgreSQL (0102).

Fictional data only. The imported-report fixture gives an organisation, a
member and a saved call; a fictional lead is added with Lead Desk's own event
shapes. Every HTTP call goes to an ``httpx.MockTransport`` that answers like
the partner's service API: no network, no real key, no real endpoint.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from ac_platform.lead_desk.models import Lead, LeadEvent
from ac_platform.partner_events import delivery, endpoints, lead_events
from ac_platform.partner_events.models import PartnerLeadAttempt, PartnerLeadEvent
from tests.database.test_conversation_postgresql import (
    postgres_harness as _postgres_harness,
)
from tests.database.test_conversation_postgresql import run
from tests.database.test_conversation_reports_postgresql import ReportFixture, _build_fixture
from tests.database.test_partner_events_postgresql import _draft, _submission

HANDOVER_REF = "AC_PARTNER_WEBHOOK_SECRET__FICTIONAL_HANDOVER"  # noqa: S105 - a variable name
HANDOVER_KEY = "psvc_00000000-0000-4000-8000-000000000000_fictional"  # noqa: S105 - fictional
WEBHOOK_REF = "AC_PARTNER_WEBHOOK_SECRET__FICTIONAL_EVENTS"  # noqa: S105 - a variable name
WEBHOOK_SECRET = "whsec-fictional-events"  # noqa: S105 - fictional
HANDOVER_URL = "https://crm.example.test/api/v1/service/customers/handover"
WEBHOOK_URL = "https://hooks.example.test/sx"
APP_URL = "https://xray.example.test"
APPROVED = {
    "send": [
        "email",
        "address",
        "attribution",
        "requirement",
        "salesperson",
        "consents",
        "history",
        "links",
    ],
    "questions": {
        "address.line1": "Address",
        "address.pin_code": "Pincode",
        "address.city": "City",
        "attribution.campaign": "campaign_name",
        "requirement.system_type": "System type",
        "requirement.capacity_kw": "Capacity (kW)",
    },
    "consents": [
        {"question": "OK to message on WhatsApp?", "purpose": "contact", "channel": "whatsapp"}
    ],
}
FORM = {
    "full_name": "Customer Example",
    "Address": "12 Example Lane",
    "Pincode": "411038",
    "City": "Pune",
    "campaign_name": "Example rooftop campaign",
    "System type": "On-grid rooftop",
    "Capacity (kW)": "5 kW",
    "OK to message on WhatsApp?": "Yes",
    "Monthly bill": "never sent: not on the list",
}


@pytest.fixture
def postgres_harness() -> Any:
    # Each case seeds its own verified control person, so each needs its own schema.
    yield from _postgres_harness.__wrapped__()  # type: ignore[attr-defined]


@pytest.fixture
def report_fixture(
    postgres_harness: Any, tmp_path_factory: pytest.TempPathFactory
) -> ReportFixture:
    fixture: ReportFixture = run(
        _build_fixture(postgres_harness, tmp_path_factory.mktemp("partner-lead-events"))
    )
    return fixture


@pytest.fixture(autouse=True)
def secrets(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(HANDOVER_REF, HANDOVER_KEY)
    monkeypatch.setenv(WEBHOOK_REF, WEBHOOK_SECRET)


@pytest.fixture(autouse=True)
def owner_alerts(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    sent: list[str] = []

    def record(text: str) -> str:
        sent.append(text)
        return "sent"

    monkeypatch.setattr(delivery, "notify_owner", record)
    return sent


class Partner:
    """A fictional partner: hand-overs answer like the service API, events get 200."""

    def __init__(self) -> None:
        self.handovers: list[httpx.Request] = []
        self.events: list[httpx.Request] = []
        self.answers: list[tuple[int, dict[str, Any]]] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/customers/handover"):
            self.handovers.append(request)
            status, body = (
                self.answers.pop(0)
                if self.answers
                else (
                    201,
                    {"customerId": str(uuid4()), "customerCode": "XX-000001", "result": "created"},
                )
            )
            return httpx.Response(status, json=body)
        self.events.append(request)
        return httpx.Response(200)

    def client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(self), follow_redirects=False)


async def _register(sessions: Any, tenant_id: UUID, now: datetime) -> None:
    async with sessions() as session, session.begin():
        await endpoints.register(
            session,
            tenant_id=tenant_id,
            url=HANDOVER_URL,
            secret_ref=HANDOVER_REF,
            secret_ref_next=None,
            events=["lead.handover"],
            facts_profile=None,
            kind="handover",
            lead_fields=APPROVED,
            reason="fictional hand-over test",
            operator_reference="fictional admin approval",
            supersede=False,
            apply=True,
            environment="development",
            now=now,
        )
        await endpoints.register(
            session,
            tenant_id=tenant_id,
            url=WEBHOOK_URL,
            secret_ref=WEBHOOK_REF,
            secret_ref_next=None,
            events=["lead.created", "lead.stage_changed", "lead.closed"],
            facts_profile=None,
            reason="fictional lead events test",
            operator_reference="fictional admin approval",
            supersede=False,
            apply=True,
            environment="development",
            now=now,
        )


async def _event(
    sessions: Any,
    tenant_id: UUID,
    lead_id: UUID,
    kind: str,
    data: dict[str, Any],
    at: datetime,
    actor: UUID | None = None,
) -> UUID:
    event_id = uuid4()
    async with sessions() as session, session.begin():
        session.add(
            LeadEvent(
                id=event_id,
                tenant_id=tenant_id,
                lead_id=lead_id,
                kind=kind,
                actor_person_id=actor,
                data=data,
                created_at=at,
            )
        )
    return event_id


async def _lead(
    sessions: Any, tenant_id: UUID, owner: UUID, at: datetime, *, phone: str = "+919999900001"
) -> UUID:
    lead_id = uuid4()
    async with sessions() as session, session.begin():
        session.add(
            Lead(
                id=lead_id,
                tenant_id=tenant_id,
                revision=1,
                source="meta",
                source_label="Example rooftop form",
                payload=dict(FORM),
                name="Customer Example",
                phone=phone,
                email="customer@example.test",
                city="Pune",
                stage="new",
                owner_person_id=owner,
                assigned_at=at,
                attempts=0,
                calls=0,
                repeats=0,
                test_data=False,
                created_at=at,
                updated_at=at,
            )
        )
    await _event(sessions, tenant_id, lead_id, "captured", {"source": "meta"}, at)
    return lead_id


async def _rows(sessions: Any) -> list[PartnerLeadEvent]:
    async with sessions() as session:
        return list(
            (
                await session.scalars(
                    select(PartnerLeadEvent).order_by(
                        PartnerLeadEvent.occurred_at, PartnerLeadEvent.created_at
                    )
                )
            ).all()
        )


async def _drain(sessions: Any, partner: Partner, clock: Any) -> list[dict[str, Any]]:
    lines: list[dict[str, Any]] = []
    async with partner.client() as client:
        while True:
            line = await lead_events.deliver_one(
                sessions, client, environment="development", clock=clock
            )
            if line is None:
                return lines
            lines.append(line)


def test_won_lead_hands_over_once_per_win_with_only_approved_fields(
    postgres_harness: Any, report_fixture: Any, owner_alerts: list[str]
) -> None:
    async def scenario() -> None:
        engine = create_async_engine(postgres_harness.url)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        try:
            draft = await _draft(sessions, report_fixture)
            submission = await _submission(sessions, report_fixture, draft)
            state = report_fixture.prepared.state
            tenant, person = state.tenant_id, state.person_id
            start = datetime.now(UTC) - timedelta(hours=2)
            await _register(sessions, tenant, start)
            lead = await _lead(sessions, tenant, person, start + timedelta(minutes=1))
            await _event(
                sessions,
                tenant,
                lead,
                "call",
                {"submission_id": str(submission), "duration_seconds": 61},
                start + timedelta(minutes=5),
            )
            won_at = start + timedelta(minutes=10)
            await _event(
                sessions,
                tenant,
                lead,
                "result",
                {"connected": True, "from_stage": "new", "stage": "won", "deal_value": "250000"},
                won_at,
                actor=person,
            )
            now = start + timedelta(minutes=11)
            clock = lambda: now  # noqa: E731
            await lead_events.collect(sessions, environment="development", app_url=APP_URL, now=now)
            rows = await _rows(sessions)
            assert sorted(row.event_type for row in rows) == [
                "lead.closed",
                "lead.created",
                "lead.handover",
                "lead.stage_changed",
            ]
            # Collecting again adds nothing.
            await lead_events.collect(sessions, environment="development", app_url=APP_URL, now=now)
            assert len(await _rows(sessions)) == 4

            partner = Partner()
            lines = await _drain(sessions, partner, clock)
            assert {line["status"] for line in lines} == {"delivered"}
            [request] = partner.handovers
            assert request.headers["authorization"] == f"Bearer {HANDOVER_KEY}"
            handover = next(
                row for row in await _rows(sessions) if row.event_type == "lead.handover"
            )
            assert request.headers["idempotency-key"] == str(handover.id)
            assert "x-sx-signature" not in request.headers
            body = json.loads(request.content)
            assert set(body) == {
                "source",
                "customer",
                "attribution",
                "requirement",
                "closing",
                "consents",
                "history",
                "links",
            }
            assert body["source"] == {
                "system": "sales_xray",
                "accountId": str(tenant),
                "leadId": str(lead),
                "leadUrl": f"{APP_URL}/leads#lead={lead}",
            }
            assert body["customer"]["address"] == {
                "line1": "12 Example Lane",
                "pinCode": "411038",
                "city": "Pune",
            }
            assert body["requirement"] == {"systemType": "On-grid rooftop", "capacityKw": 5}
            assert body["attribution"] == {
                "source": "Example rooftop form",
                "campaign": "Example rooftop campaign",
            }
            assert body["consents"][0]["granted"] is True
            assert body["closing"]["closedAt"].startswith(won_at.strftime("%Y-%m-%dT%H:%M"))
            assert body["links"] == [
                {
                    "kind": "analysis",
                    "url": f"{APP_URL}/analysis/calls/{submission}",
                    "at": body["links"][0]["at"],
                }
            ]
            assert "never sent" not in request.content.decode()
            assert "250000" not in request.content.decode()  # a deal value is not a field
            assert handover.result == "created" and handover.partner_ref == "XX-000001"
            # Lead events go to the webhook, signed as before.
            assert len(partner.events) == 3
            assert all("x-sx-signature" in item.headers for item in partner.events)

            # Reopened, then won again: one more hand-over (seq 2), none for the reopen.
            await _event(
                sessions,
                tenant,
                lead,
                "repeat",
                {"source": "meta", "reopened": True, "payload": {"Capacity (kW)": "6"}},
                start + timedelta(minutes=20),
            )
            await _event(
                sessions,
                tenant,
                lead,
                "result",
                {"connected": True, "from_stage": "new", "stage": "won"},
                start + timedelta(minutes=30),
                actor=person,
            )
            now = start + timedelta(minutes=31)
            await lead_events.collect(sessions, environment="development", app_url=APP_URL, now=now)
            partner.answers.append(
                (
                    200,
                    {"customerId": str(uuid4()), "customerCode": "XX-000001", "result": "updated"},
                )
            )
            await _drain(sessions, partner, lambda: now)
            handovers = [row for row in await _rows(sessions) if row.event_type == "lead.handover"]
            assert [row.handover_seq for row in handovers] == [1, 2]
            assert handovers[1].result == "updated"
            second = json.loads(partner.handovers[1].content)
            assert second["requirement"]["capacityKw"] == 6
            assert "correctionOf" not in second
            reopen = [
                row.payload
                for row in await _rows(sessions)
                if row.event_type == "lead.stage_changed"
                and row.payload is not None
                and row.payload["to_stage"] == "new"
            ]
            assert reopen and reopen[0]["from_stage"] == "won"

            # The partner rejects a hand-over: it keeps its key and the problems, then a
            # correction names it.
            other = await _lead(
                sessions, tenant, person, start + timedelta(minutes=40), phone="+919999900002"
            )
            await _event(
                sessions,
                tenant,
                other,
                "result",
                {"connected": True, "from_stage": "new", "stage": "won"},
                start + timedelta(minutes=41),
                actor=person,
            )
            now = start + timedelta(minutes=42)
            await lead_events.collect(sessions, environment="development", app_url=APP_URL, now=now)
            partner.answers.append(
                (
                    422,
                    {
                        "error": "invalid",
                        "fields": [{"path": "/customer/address/pinCode", "problem": "unknown"}],
                    },
                )
            )
            lines = await _drain(sessions, partner, lambda: now)
            rejected = next(line for line in lines if line.get("status") == "rejected")
            assert any("rejected" in text for text in owner_alerts)
            async with sessions() as session, session.begin():
                fixed = await lead_events.correct(
                    session,
                    event_id=UUID(rejected["lead_event"]),
                    app_url=APP_URL,
                    reason="fictional fix",
                    operator_reference="fictional operator",
                    apply=True,
                    now=now,
                )
            assert fixed["applied"] and fixed["correction_of_sent"]
            await _drain(sessions, partner, lambda: now)
            last = json.loads(partner.handovers[-1].content)
            assert last["correctionOf"] == rejected["lead_event"]
            async with sessions() as session:
                row = await session.get(PartnerLeadEvent, UUID(rejected["lead_event"]))
                assert row is not None and row.status == "rejected"
                assert row.rejection == {
                    "by": "partner",
                    "http_status": 422,
                    "error": "invalid",
                    "fields": [{"path": "/customer/address/pinCode", "problem": "unknown"}],
                }
                assert await session.get(PartnerLeadAttempt, (row.id, 1)) is not None

            # A phone that is not E.164 is rejected before sending: nothing goes out.
            bad = await _lead(
                sessions, tenant, person, start + timedelta(minutes=50), phone="099999"
            )
            await _event(
                sessions,
                tenant,
                bad,
                "result",
                {"connected": True, "from_stage": "new", "stage": "won"},
                start + timedelta(minutes=51),
                actor=person,
            )
            sent_before = len(partner.handovers)
            now = start + timedelta(minutes=52)
            await lead_events.collect(sessions, environment="development", app_url=APP_URL, now=now)
            await _drain(sessions, partner, lambda: now)
            assert len(partner.handovers) == sent_before
            local = next(
                row
                for row in await _rows(sessions)
                if row.lead_id == bad and row.event_type == "lead.handover"
            )
            assert local.status == "rejected"
            assert local.rejection == {
                "by": "sales_xray",
                "fields": [{"path": "/customer/phone", "problem": "not E.164"}],
            }

            # After 90 days the bodies are emptied; ids, results and attempts stay.
            async with sessions() as session, session.begin():
                emptied = await lead_events.erasure_sweep(session, now + timedelta(days=91))
            assert emptied == len(await _rows(sessions))
            assert all(row.payload is None for row in await _rows(sessions))
        finally:
            await engine.dispose()

    run(scenario())


def test_recipient_rules_are_checked_at_registration(
    postgres_harness: Any, report_fixture: Any
) -> None:
    async def scenario() -> None:
        engine = create_async_engine(postgres_harness.url)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        tenant = report_fixture.prepared.state.tenant_id
        now = datetime.now(UTC)
        base = {
            "tenant_id": tenant,
            "secret_ref": HANDOVER_REF,
            "secret_ref_next": None,
            "facts_profile": None,
            "reason": "fictional",
            "operator_reference": "fictional",
            "supersede": False,
            "apply": False,
            "environment": "development",
            "now": now,
        }
        try:
            async with sessions() as session:
                for changes, code in (
                    (
                        {
                            "url": "https://crm.example.test/other",
                            "events": ["lead.handover"],
                            "kind": "handover",
                        },
                        "handover_path_invalid",
                    ),
                    (
                        {
                            "url": HANDOVER_URL,
                            "events": ["lead.handover", "lead.created"],
                            "kind": "handover",
                        },
                        "handover_options_invalid",
                    ),
                    (
                        {"url": WEBHOOK_URL, "events": ["lead.handover"]},
                        "events_invalid",
                    ),
                    (
                        {"url": WEBHOOK_URL, "events": ["lead.created"], "lead_fields": APPROVED},
                        "lead_fields_only_for_handover",
                    ),
                    (
                        {
                            "url": HANDOVER_URL,
                            "events": ["lead.handover"],
                            "kind": "handover",
                            "lead_fields": {"send": [], "questions": {"address.line1": "Address"}},
                        },
                        "lead_fields_question_path",
                    ),
                ):
                    with pytest.raises(endpoints.EndpointError, match=code):
                        await endpoints.register(session, **{**base, **changes})
        finally:
            await engine.dispose()

    run(scenario())
