"""Admin → Sellers routes: who may read them, the email lookup and one person's timeline."""

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
from ac_platform.http import admin_sellers
from ac_platform.http.auth import AuthenticatedTransaction
from ac_platform.http.problem import register_problem_handlers
from ac_platform.http.routes import admin_sellers as route
from ac_platform.identity.application import ResolvedActorContext
from ac_platform.identity.models import Person
from ac_platform.identity.models import Session as SignIn
from ac_platform.kernel.authz import ActorContext
from ac_platform.lead_desk.models import LeadDeskSettings, LeadEvent
from ac_platform.learning.planning_models import AnalyticsEvent
from ac_platform.telemetry.sales_xray import NOTICE_VERSION, RETENTION_POLICY_ID
from ac_platform.tenancy.models import Membership, Tenant

OPERATIONS = uuid4()


class _Database:
    def __init__(self, session: Session) -> None:
        self.session = session

    async def run_sync(self, operation):  # type: ignore[no-untyped-def]
        return operation(self.session)


def _event(tenant: Any, person: Any, at: datetime, name: str, **payload: Any) -> AnalyticsEvent:
    return AnalyticsEvent(
        event_id=str(uuid4()),
        tenant_id=tenant,
        actor_person_id=person,
        subject_person_id=person,
        event_name=name,
        event_version="1.0",
        occurred_at=at,
        trace_id="t",
        release_id="v0.88",
        session_id="s",
        route="/leads",
        payload={"app": "android", "device": "phone", "app_version": "1.0.26", **payload},
        consent_status="granted",
        consent_purpose="product_analytics",
        consent_policy_version=NOTICE_VERSION,
        consent_captured_at=at,
        retention_policy_id=RETENTION_POLICY_ID,
        retention_expires_at=at + timedelta(days=180),
        created_at=at,
    )


@pytest.fixture
def setup(monkeypatch: pytest.MonkeyPatch) -> Iterator[dict[str, Any]]:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    model_metadata().create_all(engine)
    session = Session(engine)
    org, other, person, stranger = uuid4(), uuid4(), uuid4(), uuid4()
    now = datetime.now(UTC)
    earlier = now - timedelta(hours=2)
    session.add_all(
        [
            Tenant(id=org, slug=f"org-{org.hex}", name="Fictional Realty"),
            Tenant(id=other, slug=f"org-{other.hex}", name="Someone Else"),
            Person(id=person, email="Seller@Example.test", display_name="Fictional Seller"),
            Person(id=stranger, email="stranger@example.test"),
        ]
    )
    session.flush()
    session.add_all(
        [
            Membership(tenant_id=org, person_id=person, role="member", status="active"),
            Membership(tenant_id=other, person_id=stranger, role="member", status="active"),
        ]
    )
    session.flush()
    lead = uuid4()
    session.add_all(
        [
            SignIn(
                person_id=person,
                token_hash=b"t" * 32,
                created_at=earlier,
                expires_at=now + timedelta(days=30),
                selected_tenant_id=org,
            ),
            *[
                LeadEvent(
                    id=uuid4(),
                    tenant_id=org,
                    lead_id=lead,
                    kind="call",
                    actor_person_id=person,
                    data={"via": "phone", "device_id": "aaaaaaaa-0000-4000-8000-000000000001"},
                    created_at=earlier + timedelta(minutes=index),
                )
                for index in range(3)
            ],
            # Someone else's call in another workspace never shows.
            LeadEvent(
                id=uuid4(),
                tenant_id=other,
                lead_id=uuid4(),
                kind="call",
                actor_person_id=stranger,
                data={},
                created_at=earlier,
            ),
            _event(
                org,
                person,
                earlier,
                "sx.action_timing",
                action="outcome_save",
                ms=200,
                result="settled",
            ),
            _event(org, person, earlier, "sx.writes_waiting", waiting=1),
            # Not one of the events this view reads.
            _event(org, person, earlier, "sx.feature_used", feature="x"),
            LeadDeskSettings(
                tenant_id=org,
                revision=1,
                config={
                    "phones": {
                        str(person): {
                            "device_id": "aaaaaaaa-0000-4000-8000-000000000001",
                            "app_version": "1.0.26",
                            "family": "xiaomi",
                            "reported_at": earlier.isoformat(),
                        }
                    }
                },
                updated_by_person_id=None,
                updated_at=earlier,
            ),
        ]
    )
    session.flush()
    state: dict[str, Any] = {
        "tenant": OPERATIONS,
        "admitted": True,
        "person": person,
        "org": org,
    }

    class _Admin:
        def __init__(self, _application: object) -> None:
            pass

        async def admit(self, _actor: ActorContext) -> None:
            if not state["admitted"]:
                raise ConversationDenied("Sales X-Ray control accounts only.")

    monkeypatch.setattr(admin_sellers, "ConversationProviderAdmin", _Admin)

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
            token="admin-sellers-token",  # noqa: S106
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


def test_an_email_finds_its_person_whatever_its_case(setup: dict[str, Any]) -> None:
    client = setup["client"]
    response = client.get("/v1/admin/sellers?email=%20seller@EXAMPLE.test%20")
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "private, no-store"
    assert response.json() == {
        "person": {
            "id": str(setup["person"]),
            "name": "Fictional Seller",
            "email": "Seller@Example.test",
        }
    }
    assert client.get("/v1/admin/sellers?email=nobody@example.test").status_code == 404
    assert client.get("/v1/admin/sellers?email=not-an-email").status_code == 422
    assert client.get("/v1/admin/sellers?email=a@b.test&page=2").status_code == 422


def test_the_timeline_reads_only_this_persons_days(setup: dict[str, Any]) -> None:
    client = setup["client"]
    response = client.get(f"/v1/admin/sellers/{setup['person']}/timeline?days=7")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["schema"] == "ac.admin.seller-timeline/1"
    assert body["person"]["email"] == "Seller@Example.test"
    assert body["window"]["days"] == 7
    [workspace] = body["workspaces"]
    # No organisation registration here, so the workspace is "other".
    assert (workspace["name"], workspace["kind"], workspace["analytics"]) == (
        "Fictional Realty",
        "other",
        "on",
    )
    assert workspace["sign_ins"] == 1
    assert body["totals"]["calls_logged"] == 3
    assert body["totals"]["results_saved"] == 1
    [day] = body["days"]
    assert day["server"]["calls_logged"] == 3
    assert day["phone"]["waiting"] == 1
    assert body["phones"][0]["install"] == "aaaaaaaa"
    assert body["installs"][0]["calls"] == 3
    assert body["truncated"] == []
    assert body["summary"]["tone"] == "bad"
    assert client.get(f"/v1/admin/sellers/{uuid4()}/timeline").status_code == 404
    assert client.get(f"/v1/admin/sellers/{setup['person']}/timeline?days=90").status_code == 422


def test_only_the_operations_workspace_and_admin_host_and_control_accounts(
    setup: dict[str, Any],
) -> None:
    path = f"/v1/admin/sellers/{setup['person']}/timeline"
    assert setup["outside"].get(path).status_code == 403
    setup["admitted"] = False
    assert setup["client"].get(path).status_code == 403
    assert setup["client"].get("/v1/admin/sellers?email=seller@example.test").status_code == 403
    setup["admitted"] = True
    setup["tenant"] = uuid4()
    assert setup["client"].get(path).status_code == 403
