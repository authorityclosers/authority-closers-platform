"""Admin → Product telemetry routes: who may read them and what they answer."""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from ac_platform.application.settings import Settings
from ac_platform.conversation_intelligence.application import ConversationDenied
from ac_platform.db.models import model_metadata
from ac_platform.http import admin_telemetry
from ac_platform.http.auth import AuthenticatedTransaction
from ac_platform.http.problem import register_problem_handlers
from ac_platform.http.routes import admin_telemetry as route
from ac_platform.identity.application import ResolvedActorContext
from ac_platform.kernel.authz import ActorContext
from ac_platform.learning.planning_models import AnalyticsEvent
from ac_platform.telemetry.sales_xray import NOTICE_VERSION, RETENTION_POLICY_ID
from ac_platform.usage_people.models import MetricsPseudonymKey
from ac_platform.usage_people.pseudonyms import pads

OPERATIONS = uuid4()


class _Database:
    def __init__(self, session: Session) -> None:
        self.session = session

    async def run_sync(self, operation):  # type: ignore[no-untyped-def]
        return operation(self.session)


@pytest.fixture
def setup(monkeypatch: pytest.MonkeyPatch) -> Iterator[dict[str, Any]]:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    model_metadata().create_all(engine)
    session = Session(engine)
    inner, outer = pads(b"k" * 32)
    session.add(
        MetricsPseudonymKey(id=1, inner_pad=inner, outer_pad=outer, created_at=datetime.now(UTC))
    )
    at = datetime.now(UTC) - timedelta(hours=1)
    session.add(
        AnalyticsEvent(
            event_id=str(uuid4()),
            tenant_id=uuid4(),
            actor_person_id=uuid4(),
            subject_person_id=uuid4(),
            event_name="sx.action_timing",
            event_version="1.0",
            occurred_at=at,
            trace_id="t",
            release_id="v0.86",
            session_id="s",
            route="/leads",
            payload={"action": "lead_open", "ms": 1_400, "result": "settled", "tier": "low"},
            consent_status="granted",
            consent_purpose="product_analytics",
            consent_policy_version=NOTICE_VERSION,
            consent_captured_at=at,
            retention_policy_id=RETENTION_POLICY_ID,
            retention_expires_at=at + timedelta(days=180),
            created_at=at,
        )
    )
    session.flush()
    state: dict[str, Any] = {"tenant": OPERATIONS, "admitted": True, "session": session}

    class _Admin:
        def __init__(self, _application: object) -> None:
            pass

        async def admit(self, _actor: ActorContext) -> None:
            if not state["admitted"]:
                raise ConversationDenied("Sales X-Ray control accounts only.")

    monkeypatch.setattr(admin_telemetry, "ConversationProviderAdmin", _Admin)

    async def require_actor(_request: Request) -> AsyncIterator[AuthenticatedTransaction]:
        yield AuthenticatedTransaction(
            database=_Database(session),  # type: ignore[arg-type]
            identity=SimpleNamespace(),  # type: ignore[arg-type]
            resolved=ResolvedActorContext(
                actor=ActorContext(
                    person_id=uuid4(), session_id=uuid4(), tenant_id=state["tenant"]
                ),
                membership_role="owner",
                person_revision=0,
                session_revision=0,
                tenant_revision=0,
                membership_revision=0,
            ),
            token="admin-telemetry-token",  # noqa: S106
        )

    settings = Settings(
        environment="development",
        release_id="test",
        database_url="sqlite://",
        public_app_url="https://app.authorityclosers.test",
        admin_app_url="https://admin.authorityclosers.test",
        api_url="https://api.authorityclosers.test",
        operations_tenant_id=OPERATIONS,
        metrics_store_root=None,
    )
    application = FastAPI()
    register_problem_handlers(application)
    route.install(
        application,
        SimpleNamespace(settings=settings, require_actor=require_actor),  # type: ignore[arg-type]
    )
    state["client"] = TestClient(application, base_url="https://admin.authorityclosers.test")
    state["outside"] = TestClient(application, base_url="https://app.authorityclosers.test")
    try:
        yield state
    finally:
        session.close()
        engine.dispose()


def test_the_overview_reads_this_environments_events_for_control_accounts(
    setup: dict[str, Any],
) -> None:
    response = setup["client"].get("/v1/admin/telemetry/overview?window=24h&tier=low")
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "private, no-store"
    body = response.json()
    assert body["schema"] == "ac.sales-xray.product-telemetry/1"
    assert body["environment"] == "development"
    [lead] = body["speed"]
    assert (lead["action"], lead["taps"], lead["slow_share"]) == ("lead_open", 1, 1.0)
    assert body["filters"]["releases"] == ["v0.86"]
    assert setup["client"].get("/v1/admin/telemetry/overview?window=1y").status_code == 422
    assert setup["client"].get("/v1/admin/telemetry/overview?device=watch").status_code == 422


def test_only_the_operations_workspace_and_admin_host_and_control_accounts(
    setup: dict[str, Any],
) -> None:
    assert setup["outside"].get("/v1/admin/telemetry/overview").status_code == 403
    setup["admitted"] = False
    assert setup["client"].get("/v1/admin/telemetry/overview").status_code == 403
    setup["admitted"] = True
    setup["tenant"] = uuid4()
    assert setup["client"].get("/v1/admin/telemetry/overview").status_code == 403


def test_the_daily_export_takes_a_recent_india_day(setup: dict[str, Any]) -> None:
    response = setup["client"].get("/v1/admin/telemetry/daily")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["schema"] == "ac.sales-xray.telemetry-daily/1"
    assert body["cost_store"] is False
    assert body["truncated"] is False
    assert setup["client"].get("/v1/admin/telemetry/daily?day=2020-01-01").status_code == 422
    future = (datetime.now(UTC) + timedelta(days=3)).date().isoformat()
    assert setup["client"].get(f"/v1/admin/telemetry/daily?day={future}").status_code == 422
