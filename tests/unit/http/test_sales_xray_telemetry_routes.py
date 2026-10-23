"""The telemetry intake composed for Sales X-Ray: its events, call references, daily cap,
consent (option B: on unless a person or workspace turns it off) and Settings, Privacy."""

from __future__ import annotations

import json
import os
from collections.abc import AsyncIterator, Iterator
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from ac_platform.application.settings import Settings
from ac_platform.audit.models import AuditEvent
from ac_platform.conversation_intelligence.guest_models import ConversationGuestSubmission
from ac_platform.conversation_intelligence.synthetic_import_models import (
    ConversationSandboxOrganisation,
)
from ac_platform.db.models import model_metadata
from ac_platform.http.auth import AuthenticatedTransaction
from ac_platform.http.problem import register_problem_handlers
from ac_platform.http.routes import telemetry as telemetry_route
from ac_platform.http.telemetry import install_telemetry_http
from ac_platform.identity.application import ResolvedActorContext
from ac_platform.identity.models import Person
from ac_platform.kernel.authz import ActorContext
from ac_platform.learning.planning_models import AnalyticsEvent
from ac_platform.telemetry import sales_xray_consent
from ac_platform.telemetry.ingest import (
    TelemetryConsent,
    TelemetryConsentStatus,
    TelemetrySurface,
)
from ac_platform.telemetry.sales_xray import (
    NOTICE_VERSION,
    NOTICES,
    RETENTION_DAYS,
    RETENTION_POLICY_ID,
    SALES_XRAY_EVENTS,
    SALES_XRAY_SURFACE,
    SalesXrayAdmission,
    call_ref,
)
from ac_platform.telemetry.sales_xray_consent import PERSON_ACTION, RESOURCE_TYPE
from ac_platform.tenancy.models import Membership, Tenant
from ac_platform.usage_people.models import MetricsPseudonymKey
from ac_platform.usage_people.pseudonyms import pads

_ORIGIN = {"Origin": "https://app.authorityclosers.test"}


class _AsyncDatabase:
    def __init__(self, session: Session) -> None:
        self.session = session

    async def run_sync(self, operation):  # type: ignore[no-untyped-def]
        return operation(self.session)


class _Harness:
    def __init__(self) -> None:
        self.engine = create_engine(
            "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
        )
        model_metadata().create_all(self.engine)
        self.session = Session(self.engine)
        self.tenant_id = uuid4()
        self.person_id = uuid4()
        self.session.add_all(
            [
                Tenant(id=self.tenant_id, slug=f"sx-{self.tenant_id.hex}", name="Sales X-Ray"),
                Person(id=self.person_id, email=f"seller-{self.person_id.hex}@example.test"),
            ]
        )
        self.session.flush()
        self.session.add(
            Membership(
                tenant_id=self.tenant_id, person_id=self.person_id, role="learner", status="active"
            )
        )
        self.session.flush()
        self.actor = ActorContext(
            person_id=self.person_id, session_id=uuid4(), tenant_id=self.tenant_id
        )
        self.role = "member"
        self.sequence = 0
        self.settings = Settings(
            environment="test",
            release_id="sx-telemetry-test-release",
            database_url="sqlite://",
            public_app_url="https://app.authorityclosers.test",
            admin_app_url="https://admin.authorityclosers.test",
            api_url="https://api.authorityclosers.test",
        )

    async def require_actor(self, _request: Request) -> AsyncIterator[AuthenticatedTransaction]:
        yield AuthenticatedTransaction(
            database=_AsyncDatabase(self.session),  # type: ignore[arg-type]
            identity=SimpleNamespace(),  # type: ignore[arg-type]
            resolved=ResolvedActorContext(
                actor=self.actor,
                membership_role=self.role,
                person_revision=0,
                session_revision=0,
                tenant_revision=0,
                membership_revision=0,
            ),
            token="sx-telemetry-session-token",  # noqa: S106
        )

    def consent(self, _database: object, actor: ActorContext) -> TelemetryConsent:
        assert actor.tenant_id is not None
        return TelemetryConsent(
            status=TelemetryConsentStatus.GRANTED,
            policy_version="sx-product-analytics-test",
            captured_at=datetime.now(UTC) - timedelta(minutes=1),
            tenant_id=actor.tenant_id,
            person_id=actor.person_id,
            session_id=actor.session_id,
        )

    def client(self, surface: TelemetrySurface = SALES_XRAY_SURFACE) -> TestClient:
        application = FastAPI()
        register_problem_handlers(application)
        install_telemetry_http(
            application,
            settings=self.settings,
            require_actor=self.require_actor,
            consent_resolver=self.consent,
            retention_days=RETENTION_DAYS,
            retention_policy_id=RETENTION_POLICY_ID,
            admission=SalesXrayAdmission(),
            surface=surface,
        )
        return TestClient(application)

    def call(self) -> tuple[UUID, UUID]:
        """A call (submission) of this workspace and its recording."""
        submission_id, recording_id = uuid4(), uuid4()
        self.session.add(
            ConversationGuestSubmission(
                tenant_id=self.tenant_id,
                submission_id=submission_id,
                person_id=self.person_id,
                recording_id=recording_id,
                processing_lease_id=uuid4(),
                usage_id=uuid4(),
                source_sha256="a" * 64,
                capture_source=None,
                created_at=datetime.now(UTC),
            )
        )
        self.session.flush()
        return submission_id, recording_id

    def key(self) -> tuple[bytes, bytes]:
        inner, outer = pads(os.urandom(32))
        made = datetime.now(UTC)
        self.session.add(
            MetricsPseudonymKey(id=1, inner_pad=inner, outer_pad=outer, created_at=made)
        )
        self.session.flush()
        return inner, outer

    def event(self, name: str = "sx.section_read", **fields: Any) -> dict[str, Any]:
        payload = fields.pop("payload", {"section": "analysis", "read_band": "5_30s"})
        return {
            "event_id": str(uuid4()),
            "event_name": name,
            "event_version": "1.0",
            "occurred_at": datetime.now(UTC).isoformat(),
            "session_id": str(self.actor.session_id),
            "route": "/analysis/calls/[callId]",
            "payload": payload,
            **fields,
        }

    def stored(self) -> list[AnalyticsEvent]:
        return list(self.session.scalars(select(AnalyticsEvent)))

    def composed(self) -> TestClient:
        """The app's own composition (routes/telemetry.py), consent resolver and all."""
        application = FastAPI()
        register_problem_handlers(application)
        context = SimpleNamespace(settings=self.settings, require_actor=self.require_actor)
        telemetry_route.install(application, context)  # type: ignore[arg-type]
        return TestClient(application)

    def choice(
        self,
        resource_id: str,
        enabled: bool,
        *,
        at: datetime | None = None,
        action: str = PERSON_ACTION,
    ) -> None:
        """An analytics choice in this workspace's audit chain."""
        self.sequence += 1
        moment = at or datetime.now(UTC)
        self.session.add(
            AuditEvent(
                id=uuid4(),
                tenant_id=self.tenant_id,
                sequence_no=self.sequence,
                actor_person_id=self.person_id,
                actor_type="person",
                action=action,
                resource_type=RESOURCE_TYPE,
                resource_id=resource_id,
                payload={"enabled": enabled, "notice_version": NOTICE_VERSION},
                occurred_at=moment,
                recorded_at=moment,
                previous_hash="0" * 64,
                event_hash=f"{self.sequence:064x}",
            )
        )
        self.session.flush()


@pytest.fixture
def harness() -> Iterator[_Harness]:
    made = _Harness()
    try:
        yield made
    finally:
        made.session.close()
        made.engine.dispose()


def test_the_taxonomy_lists_sales_xray_events_and_which_name_a_call(harness: _Harness) -> None:
    body = harness.client().get("/v1/telemetry/taxonomy").json()
    names = {item["event_name"]: item for item in body["events"]}
    assert set(names) == set(SALES_XRAY_EVENTS)
    assert names["sx.section_read"]["takes_call"] is True
    assert names["sx.error_shown"]["takes_call"] is False
    assert "never call content" in body["disclaimer"]


def test_a_section_read_stores_its_call_reference_never_the_call_id(harness: _Harness) -> None:
    inner, outer = harness.key()
    submission_id, recording_id = harness.call()
    response = harness.client().post(
        "/v1/telemetry/events",
        json={
            "events": [
                harness.event(
                    call_id=str(submission_id),
                    payload={
                        "section": "analysis",
                        "skill": "d07",
                        "look": "brain4",
                        "read_band": "30_120s",
                        "dwell_ms": 41_250,
                        "device": "phone",
                        "app": "android",
                    },
                )
            ]
        },
        headers=_ORIGIN,
    )
    assert response.status_code == 202, response.text
    body = response.json()
    assert body["accepted"] == 1
    assert body["provenance_source"] == "authenticated_sales_xray_api"
    assert body["provenance_version"] == "sales-xray-product-telemetry-v1"
    [row] = harness.stored()
    assert row.payload["call_ref"] == call_ref(inner, outer, recording_id)
    assert row.payload["skill"] == "d07"
    assert row.route == "/analysis/calls/[callId]"
    assert row.retention_policy_id == "sx-product-analytics-v1"
    assert row.consent_policy_version == "sx-product-analytics-test"
    kept = json.dumps(
        {column.key: str(getattr(row, column.key)) for column in AnalyticsEvent.__table__.columns}
    )
    assert str(submission_id) not in kept
    assert str(recording_id) not in kept


def test_a_call_outside_the_workspace_is_left_unnamed(harness: _Harness) -> None:
    harness.key()
    response = harness.client().post(
        "/v1/telemetry/events",
        json={
            "events": [
                harness.event(
                    "sx.full_report_requested",
                    call_id=str(uuid4()),
                    payload={"surface": "report", "level": "data_only"},
                )
            ]
        },
        headers=_ORIGIN,
    )
    assert response.status_code == 202, response.text
    [row] = harness.stored()
    assert row.payload == {"surface": "report", "level": "data_only"}


@pytest.mark.parametrize(
    "change",
    [
        {"event_name": "analytics.plan_viewed", "payload": {"period": "today"}},
        {"route": "/home"},
        {"route": "/analysis/calls/3f2b7d10-0000-4000-8000-000000000000"},
        {"event_name": "sx.error_shown", "payload": {"surface": "x", "code": "y"}, "call_id": None},
        {"payload": {"section": "summary", "read_band": "5_30s"}},
        {"payload": {"section": "analysis", "read_band": "5_30s", "dwell_ms": 600_001}},
        {"payload": {"section": "analysis", "read_band": "5_30s", "skill": "D07"}},
        {"payload": {"section": "analysis"}},
        {"event_name": "sx.error_shown", "payload": {"surface": "report", "code": "Read failed"}},
    ],
)
def test_values_routes_and_calls_are_checked_and_a_bad_batch_stores_nothing(
    harness: _Harness, change: dict[str, Any]
) -> None:
    event = harness.event()
    event.update(change)
    if "call_id" in change:
        event["call_id"] = str(uuid4())  # an event that names no call
    response = harness.client().post(
        "/v1/telemetry/events", json={"events": [harness.event(), event]}, headers=_ORIGIN
    )
    assert response.status_code == 422, response.text
    assert response.json()["code"] == "telemetry_event_invalid"
    assert harness.stored() == []


def test_one_person_stores_at_most_the_daily_cap(harness: _Harness) -> None:
    client = harness.client(replace(SALES_XRAY_SURFACE, person_daily_cap=3))
    first = client.post(
        "/v1/telemetry/events",
        json={"events": [harness.event(), harness.event()]},
        headers=_ORIGIN,
    )
    assert first.status_code == 202, first.text
    second = client.post(
        "/v1/telemetry/events",
        json={"events": [harness.event(), harness.event()]},
        headers=_ORIGIN,
    )
    assert second.status_code == 503
    assert second.json()["code"] == "telemetry_backpressure"
    assert len(harness.stored()) == 2


def test_the_composed_route_records_by_default_and_purges_expired_rows(
    harness: _Harness,
) -> None:
    long_ago = datetime.now(UTC) - timedelta(days=200)
    harness.session.add(
        AnalyticsEvent(
            event_id=str(uuid4()),
            tenant_id=harness.tenant_id,
            actor_person_id=harness.person_id,
            subject_person_id=harness.person_id,
            event_name="sx.screen_viewed",
            event_version="1.0",
            occurred_at=long_ago,
            trace_id="old-trace",
            release_id="old",
            session_id=str(harness.actor.session_id),
            route="/leads",
            payload={"screen": "leads", "nav": "push"},
            consent_status="granted",
            consent_purpose="product_analytics",
            consent_policy_version=NOTICE_VERSION,
            consent_captured_at=long_ago,
            retention_policy_id=RETENTION_POLICY_ID,
            retention_expires_at=long_ago + timedelta(days=180),
            created_at=long_ago,
        )
    )
    harness.session.flush()
    client = harness.composed()
    names = {item["event_name"] for item in client.get("/v1/telemetry/taxonomy").json()["events"]}
    assert names == set(SALES_XRAY_EVENTS)
    response = client.post(
        "/v1/telemetry/events",
        json={
            "events": [
                harness.event(
                    "sx.action_timing",
                    route="/leads",
                    payload={
                        "action": "lead_open",
                        "ms": 1840,
                        "result": "settled",
                        "paint_ms": 96,
                        "screen": "leads",
                        "device": "phone",
                        "tier": "low",
                        "net": "4g",
                        "link": "cellular",
                        "app": "android",
                        "app_version": "0.3.88",
                    },
                )
            ]
        },
        headers=_ORIGIN,
    )
    assert response.status_code == 202, response.text
    [row] = harness.stored()
    assert row.event_name == "sx.action_timing"
    assert row.consent_policy_version == NOTICE_VERSION
    # Kept 180 days; the expired row went with this write.
    assert (row.retention_expires_at - row.created_at).days == 180


def test_an_opted_out_person_is_listed_nothing_and_stores_nothing(harness: _Harness) -> None:
    harness.choice(str(harness.person_id), False)
    client = harness.composed()
    assert client.get("/v1/telemetry/taxonomy").json()["events"] == []
    response = client.post(
        "/v1/telemetry/events", json={"events": [harness.event()]}, headers=_ORIGIN
    )
    assert response.status_code == 202
    assert response.json()["reason"] == "consent_required"
    assert harness.stored() == []


def test_a_workspace_switched_off_or_a_sandbox_records_nothing(harness: _Harness) -> None:
    harness.choice("workspace", False)
    client = harness.composed()
    assert client.get("/v1/telemetry/taxonomy").json()["events"] == []
    harness.choice("workspace", True)
    assert client.get("/v1/telemetry/taxonomy").json()["events"] != []
    harness.session.add(
        ConversationSandboxOrganisation(
            tenant_id=harness.tenant_id,
            approved_by_person_id=harness.person_id,
            approval_reference="test sandbox",
            created_at=datetime.now(UTC),
        )
    )
    harness.session.flush()
    assert client.get("/v1/telemetry/taxonomy").json()["events"] == []
    response = client.post(
        "/v1/telemetry/events", json={"events": [harness.event()]}, headers=_ORIGIN
    )
    assert response.status_code == 503
    assert response.json()["code"] == "telemetry_consent_unavailable"
    assert harness.stored() == []


def test_privacy_settings_show_and_change_both_switches(
    harness: _Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    appended: list[dict[str, Any]] = []

    class _Audit:
        def __init__(self, _database: object) -> None:
            pass

        async def append(self, **fields: Any) -> None:
            appended.append(fields)
            harness.choice(
                fields["resource_id"],
                fields["payload"]["enabled"],
                at=fields["now"],
                action=fields["action"],
            )

    monkeypatch.setattr(sales_xray_consent, "AuditRepository", _Audit)
    client = harness.composed()
    view = client.get("/v1/telemetry/preferences").json()
    assert view["collecting"] is True
    assert view["notice"] == {
        "version": NOTICE_VERSION,
        "paragraphs": list(NOTICES[NOTICE_VERSION]),
    }
    assert view["you"] == {"enabled": True, "changed_at": None}
    assert view["workspace"]["can_change"] is False

    off = client.put("/v1/telemetry/preferences/you", json={"enabled": False}, headers=_ORIGIN)
    assert off.status_code == 200, off.text
    assert off.json()["you"]["enabled"] is False
    assert off.json()["collecting"] is False
    assert appended[-1]["resource_id"] == str(harness.person_id)
    assert appended[-1]["payload"] == {"enabled": False, "notice_version": NOTICE_VERSION}
    assert client.get("/v1/telemetry/taxonomy").json()["events"] == []

    refused = client.put(
        "/v1/telemetry/preferences/workspace", json={"enabled": False}, headers=_ORIGIN
    )
    assert refused.status_code == 403
    harness.role = "owner"
    workspace = client.put(
        "/v1/telemetry/preferences/workspace", json={"enabled": False}, headers=_ORIGIN
    )
    assert workspace.status_code == 200, workspace.text
    assert workspace.json()["workspace"]["enabled"] is False
    assert workspace.json()["workspace"]["can_change"] is True
    back = client.put("/v1/telemetry/preferences/you", json={"enabled": True}, headers=_ORIGIN)
    assert back.json()["you"]["enabled"] is True
    assert back.json()["collecting"] is False  # the workspace is still off
    assert appended[-2]["resource_id"] == "workspace"
    # A bad body or a foreign origin changes nothing.
    assert (
        client.put(
            "/v1/telemetry/preferences/you", json={"enabled": "no"}, headers=_ORIGIN
        ).status_code
        == 422
    )
    count = len(appended)
    client.put(
        "/v1/telemetry/preferences/you",
        json={"enabled": False},
        headers={"Origin": "https://evil.example"},
    )
    assert len(appended) == count
