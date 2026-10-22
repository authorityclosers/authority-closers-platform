"""The telemetry intake composed for Sales X-Ray: its events, call references and daily cap."""

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
from ac_platform.conversation_intelligence.guest_models import ConversationGuestSubmission
from ac_platform.db.models import model_metadata
from ac_platform.http.auth import AuthenticatedTransaction
from ac_platform.http.problem import register_problem_handlers
from ac_platform.http.routes import telemetry as telemetry_route
from ac_platform.http.telemetry import install_telemetry_http
from ac_platform.identity.application import ResolvedActorContext
from ac_platform.identity.models import Person
from ac_platform.kernel.authz import ActorContext
from ac_platform.learning.planning_models import AnalyticsEvent
from ac_platform.telemetry.ingest import (
    TelemetryConsent,
    TelemetryConsentStatus,
    TelemetrySurface,
)
from ac_platform.telemetry.sales_xray import (
    RETENTION_DAYS,
    RETENTION_POLICY_ID,
    SALES_XRAY_EVENTS,
    SALES_XRAY_SURFACE,
    SalesXrayAdmission,
    call_ref,
)
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
                membership_role="learner",
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


def test_the_composed_route_takes_sales_xray_events_but_stores_none_until_consent(
    harness: _Harness,
) -> None:
    application = FastAPI()
    register_problem_handlers(application)
    context = SimpleNamespace(settings=harness.settings, require_actor=harness.require_actor)
    telemetry_route.install(application, context)  # type: ignore[arg-type]
    client = TestClient(application)
    names = {item["event_name"] for item in client.get("/v1/telemetry/taxonomy").json()["events"]}
    assert names == set(SALES_XRAY_EVENTS)
    response = client.post(
        "/v1/telemetry/events", json={"events": [harness.event()]}, headers=_ORIGIN
    )
    assert response.status_code == 503
    assert response.json()["code"] == "telemetry_consent_unavailable"
    assert harness.stored() == []
