"""Contract tests for the authenticated planning/analytics proposal seam."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from ac_platform.application.settings import Settings
from ac_platform.db.models import model_metadata
from ac_platform.http.auth import AuthenticatedTransaction
from ac_platform.http.planning import install_planning_http
from ac_platform.http.problem import register_problem_handlers
from ac_platform.identity.application import ResolvedActorContext
from ac_platform.identity.models import Person
from ac_platform.kernel.authz import ActorContext
from ac_platform.learning.planning_models import (
    AnalyticsEvent,
    LearningNextActionProjection,
    LearningPlanItem,
)
from ac_platform.tenancy.models import Membership, Tenant


class _AsyncDatabase:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.run_sync_calls = 0

    async def run_sync(self, operation):  # type: ignore[no-untyped-def]
        self.run_sync_calls += 1
        return operation(self.session)


@pytest.fixture
def planning_harness() -> tuple[TestClient, Session, ActorContext, _AsyncDatabase]:
    tenant_id = uuid4()
    person_id = uuid4()
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    model_metadata().create_all(engine)
    session = Session(engine)
    session.add_all(
        [
            Tenant(id=tenant_id, slug=f"planning-{tenant_id.hex}", name="Planning tenant"),
            Person(id=person_id, email=f"learner-{person_id.hex}@example.test"),
        ]
    )
    session.flush()
    session.add(
        Membership(tenant_id=tenant_id, person_id=person_id, role="learner", status="active")
    )
    session.flush()
    actor = ActorContext(person_id=person_id, session_id=uuid4(), tenant_id=tenant_id)
    database = _AsyncDatabase(session)

    async def require_actor(_request: Request) -> AsyncIterator[AuthenticatedTransaction]:
        yield AuthenticatedTransaction(
            database=database,  # type: ignore[arg-type]
            identity=SimpleNamespace(),  # type: ignore[arg-type]
            resolved=ResolvedActorContext(
                actor=actor,
                membership_role="learner",
                person_revision=0,
                session_revision=0,
                tenant_revision=0,
                membership_revision=0,
            ),
            token="planning-session-token",  # noqa: S106
        )

    settings = Settings(
        environment="test",
        database_url="sqlite://",
        public_app_url="https://app.authorityclosers.test",
        admin_app_url="https://admin.authorityclosers.test",
        api_url="https://api.authorityclosers.test",
    )
    application = FastAPI()
    register_problem_handlers(application)
    install_planning_http(
        application,
        settings=settings,
        require_actor=require_actor,
        consent_resolver=lambda _actor, event: event.consent,
        retention_days=30,
        retention_policy_id="product-analytics-proposal-v1",
    )
    client = TestClient(application)
    try:
        yield client, session, actor, database
    finally:
        session.close()
        engine.dispose()


def _plan_item(actor: ActorContext, *, period: str = "today") -> LearningPlanItem:
    return LearningPlanItem(
        id=uuid4(),
        tenant_id=actor.tenant_id,
        person_id=actor.person_id,
        period=period,
        title="Review the opening question",
        activity_id=uuid4(),
        planned_for=date(2026, 9, 2),
        position=1,
    )


def _analytics_body(
    *, event_id: str = "analytics-event-001", status: str = "granted"
) -> dict[str, object]:
    now = datetime.now(UTC).isoformat()
    return {
        "event_id": event_id,
        "event_name": "analytics.plan_viewed",
        "event_version": "1.0",
        "occurred_at": now,
        "route": "/home",
        "period": "today",
        "payload": {"period": "today"},
        "consent": {
            "status": status,
            "purpose": "product_analytics",
            "scope": "product_analytics",
            "policy_version": "consent-v1",
            "captured_at": now,
        },
    }


def test_empty_dashboard_is_explicit_and_does_not_fabricate_progress(
    planning_harness: tuple[TestClient, Session, ActorContext, _AsyncDatabase],
) -> None:
    client, _session, actor, database = planning_harness

    response = client.get("/v1/learning/home")

    assert response.status_code == 200
    body = response.json()
    assert body["subject_person_id"] == str(actor.person_id)
    assert body["plan"]["status"] == "not_configured"
    assert body["up_next"]["status"] == "not_configured"
    assert body["canonical_progress"]["status"] == "empty"
    assert body["canonical_progress"]["completion_ratio"] is None
    assert body["analytics"]["status"] == "insufficient_signal"
    assert response.headers["cache-control"] == "private, no-store"
    assert database.run_sync_calls == 1


def test_plan_calendar_and_up_next_read_only_use_explicit_rows(
    planning_harness: tuple[TestClient, Session, ActorContext, _AsyncDatabase],
) -> None:
    client, session, actor, _database = planning_harness
    item = _plan_item(actor)
    session.add(item)
    session.flush()
    session.add(
        LearningNextActionProjection(
            id=uuid4(),
            tenant_id=actor.tenant_id,
            person_id=actor.person_id,
            plan_item_id=item.id,
            generated_from_event_id=uuid4(),
        )
    )
    session.commit()

    plan = client.get("/v1/learning/plans?period=today")
    next_action = client.get("/v1/learning/up-next")
    calendar = client.get("/v1/learning/calendar")

    assert plan.status_code == 200
    assert plan.json()["status"] == "available"
    assert plan.json()["items"][0]["id"] == str(item.id)
    assert next_action.status_code == 200
    assert next_action.json()["status"] == "available"
    assert next_action.json()["item"]["id"] == str(item.id)
    assert calendar.status_code == 200
    assert set(calendar.json()["periods"]) == {"today", "week", "month"}
    assert calendar.json()["periods"]["week"]["status"] == "not_configured"


def test_subject_override_cannot_cross_the_existing_authz_boundary(
    planning_harness: tuple[TestClient, Session, ActorContext, _AsyncDatabase],
) -> None:
    client, _session, _actor, _database = planning_harness

    response = client.get(f"/v1/learning/plans?subject_person_id={uuid4()}")

    assert response.status_code == 403
    assert response.json()["code"] == "planning_subject_denied"


def test_analytics_ingestion_is_allowlisted_consent_gated_and_idempotent(
    planning_harness: tuple[TestClient, Session, ActorContext, _AsyncDatabase],
) -> None:
    client, session, _actor, _database = planning_harness
    headers = {"Origin": "https://app.authorityclosers.test"}

    denied = client.post(
        "/v1/analytics/events",
        json=_analytics_body(event_id="analytics-denied-001", status="denied"),
        headers=headers,
    )
    assert denied.status_code == 202
    assert denied.json()["stored"] is False
    assert denied.json()["reason"] == "consent_required"

    first = client.post("/v1/analytics/events", json=_analytics_body(), headers=headers)
    duplicate = client.post("/v1/analytics/events", json=_analytics_body(), headers=headers)
    assert first.status_code == 202
    assert first.json()["stored"] is True
    assert duplicate.status_code == 202
    assert duplicate.json()["duplicate"] is True
    assert session.query(AnalyticsEvent).count() == 1

    rejected = client.post(
        "/v1/analytics/events",
        json=_analytics_body(event_id="analytics-canonical-001")
        | {"event_name": "activity.completed"},
        headers=headers,
    )
    assert rejected.status_code == 422
    assert rejected.json()["code"] == "planning_event_invalid"


def test_analytics_expiry_is_removed_from_descriptive_projection(
    planning_harness: tuple[TestClient, Session, ActorContext, _AsyncDatabase],
) -> None:
    client, session, actor, _database = planning_harness
    now = datetime.now(UTC)
    other_tenant_id = uuid4()
    other_person_id = uuid4()
    session.add_all(
        [
            Tenant(id=other_tenant_id, slug=f"planning-{other_tenant_id.hex}", name="Other tenant"),
            Person(id=other_person_id, email=f"learner-{other_person_id.hex}@example.test"),
        ]
    )
    session.flush()
    session.add(
        Membership(
            tenant_id=other_tenant_id,
            person_id=other_person_id,
            role="learner",
            status="active",
        )
    )
    session.flush()
    session.add(
        AnalyticsEvent(
            event_id="analytics-expired-001",
            tenant_id=actor.tenant_id,
            actor_person_id=actor.person_id,
            subject_person_id=actor.person_id,
            event_name="analytics.plan_viewed",
            event_version="1.0",
            occurred_at=now - timedelta(days=31),
            trace_id="request-expired",
            release_id="test-release",
            route="/home",
            period="today",
            payload={"period": "today"},
            consent_policy_version="consent-v1",
            consent_captured_at=now - timedelta(days=31),
            retention_policy_id="product-analytics-proposal-v1",
            retention_expires_at=now - timedelta(days=1),
            created_at=now - timedelta(days=31),
        )
    )
    session.add(
        AnalyticsEvent(
            event_id="analytics-expired-001",
            tenant_id=other_tenant_id,
            actor_person_id=other_person_id,
            subject_person_id=other_person_id,
            event_name="analytics.plan_viewed",
            event_version="1.0",
            occurred_at=now - timedelta(days=31),
            trace_id="request-other-expired",
            release_id="test-release",
            route="/home",
            period="today",
            payload={"period": "today"},
            consent_policy_version="consent-v1",
            consent_captured_at=now - timedelta(days=31),
            retention_policy_id="product-analytics-proposal-v1",
            retention_expires_at=now - timedelta(days=1),
            created_at=now - timedelta(days=31),
        )
    )
    session.commit()

    response = client.get("/v1/learning/insights?period=today")

    assert response.status_code == 200
    assert response.json()["status"] == "insufficient_signal"
    assert (
        session.query(AnalyticsEvent).filter(AnalyticsEvent.tenant_id == actor.tenant_id).count()
        == 0
    )
    assert (
        session.query(AnalyticsEvent).filter(AnalyticsEvent.tenant_id == other_tenant_id).count()
        == 1
    )


def test_taxonomy_is_explicitly_proposal_only(
    planning_harness: tuple[TestClient, Session, ActorContext, _AsyncDatabase],
) -> None:
    client, _session, _actor, _database = planning_harness

    response = client.get("/v1/analytics/taxonomy")

    assert response.status_code == 200
    event = next(
        entry
        for entry in response.json()["events"]
        if entry["event_name"] == "analytics.plan_viewed"
    )
    assert event["authority"] == "proposal"
    assert event["event_class"] == "product_analytics"
    assert event["consent_required"] is True
    assert event["allowed_payload_keys"] == ["period"]
