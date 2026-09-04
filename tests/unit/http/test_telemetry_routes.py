"""Contract tests for the bounded learner product-telemetry intake."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from ac_platform.application.settings import Settings
from ac_platform.db.models import model_metadata
from ac_platform.http.auth import AuthenticatedTransaction
from ac_platform.http.problem import register_problem_handlers
from ac_platform.http.telemetry import install_telemetry_http
from ac_platform.identity.application import ResolvedActorContext
from ac_platform.identity.models import Person
from ac_platform.kernel.authz import ActorContext
from ac_platform.learning.planning_models import AnalyticsEvent
from ac_platform.telemetry.ingest import (
    MAX_BATCH_EVENTS,
    TelemetryConsent,
    TelemetryConsentStatus,
)
from ac_platform.tenancy.models import Membership, Tenant


class _AsyncDatabase:
    def __init__(self, session: Session) -> None:
        self.session = session

    async def run_sync(self, operation):  # type: ignore[no-untyped-def]
        return operation(self.session)


class _Admission:
    def __init__(self) -> None:
        self.reject = False
        self.calls: list[tuple[UUID, int, int]] = []

    def admit(self, *, tenant_id: UUID, event_count: int, payload_bytes: int) -> bool:
        self.calls.append((tenant_id, event_count, payload_bytes))
        return not self.reject


@pytest.fixture
def telemetry_harness() -> tuple[TestClient, Session, ActorContext, dict[str, object]]:
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
            Tenant(id=tenant_id, slug=f"telemetry-{tenant_id.hex}", name="Telemetry tenant"),
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
    state: dict[str, object] = {"consent": _granted_consent(actor)}
    state["consent_calls"] = 0
    state["revoke_on_second"] = False

    def resolve_consent(_database: object, _actor: ActorContext) -> TelemetryConsent:
        calls = int(state["consent_calls"])
        state["consent_calls"] = calls + 1
        if bool(state["revoke_on_second"]) and calls >= 1:
            current = state["consent"]
            assert isinstance(current, TelemetryConsent)
            return current.model_copy(update={"status": TelemetryConsentStatus.DENIED})
        current = state["consent"]
        assert isinstance(current, TelemetryConsent)
        return current

    admission = _Admission()
    state["admission"] = admission

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
            token="telemetry-session-token",  # noqa: S106
        )

    settings = Settings(
        environment="test",
        release_id="telemetry-test-release",
        database_url="sqlite://",
        public_app_url="https://app.authorityclosers.test",
        admin_app_url="https://admin.authorityclosers.test",
        api_url="https://api.authorityclosers.test",
    )
    state["require_actor"] = require_actor
    state["settings"] = settings
    application = FastAPI()
    register_problem_handlers(application)
    install_telemetry_http(
        application,
        settings=settings,
        require_actor=require_actor,
        consent_resolver=resolve_consent,
        retention_days=30,
        retention_policy_id="learner-telemetry-v1",
        admission=admission,
    )
    client = TestClient(application)
    try:
        yield client, session, actor, state
    finally:
        session.close()
        engine.dispose()


def _granted_consent(
    actor: ActorContext,
    *,
    captured_at: datetime | None = None,
    tenant_id: UUID | None = None,
    person_id: UUID | None = None,
    session_id: UUID | None = None,
) -> TelemetryConsent:
    return TelemetryConsent(
        status=TelemetryConsentStatus.GRANTED,
        policy_version="consent-v1",
        captured_at=captured_at or datetime.now(UTC),
        tenant_id=tenant_id or actor.tenant_id,
        person_id=person_id or actor.person_id,
        session_id=session_id or actor.session_id,
    )


def _event(actor: ActorContext, *, event_id: str | None = None) -> dict[str, object]:
    return {
        "event_id": event_id or str(uuid4()),
        "event_name": "analytics.plan_viewed",
        "event_version": "1.0",
        "occurred_at": datetime.now(UTC).isoformat(),
        "session_id": str(actor.session_id),
        "route": "/home",
        "payload": {"period": "today"},
    }


def _headers() -> dict[str, str]:
    return {"Origin": "https://app.authorityclosers.test"}


def test_telemetry_acceptance_derives_scope_and_records_provenance_metadata(
    telemetry_harness: tuple[TestClient, Session, ActorContext, dict[str, object]],
) -> None:
    client, session, actor, _state = telemetry_harness
    event = _event(actor)

    response = client.post(
        "/v1/telemetry/events",
        json={"events": [event]},
        headers=_headers(),
    )

    assert response.status_code == 202
    body = response.json()
    assert body["accepted"] == 1
    assert body["duplicate"] == 0
    assert body["accepted_event_ids"] == [event["event_id"]]
    assert body["provenance_source"] == "authenticated_learner_api"
    assert body["provenance_version"] == "learner-product-telemetry-v1"

    row = session.query(AnalyticsEvent).one()
    assert row.tenant_id == actor.tenant_id
    assert row.actor_person_id == actor.person_id
    assert row.subject_person_id == actor.person_id
    assert row.session_id == str(actor.session_id)
    assert row.release_id == "telemetry-test-release"
    assert row.trace_id
    assert row.consent_policy_version == "consent-v1"
    assert row.retention_policy_id == "learner-telemetry-v1"
    assert row.retention_expires_at > row.created_at
    assert row.payload == {"period": "today"}


def test_missing_server_consent_resolver_fails_closed_without_storage() -> None:
    application = FastAPI()
    register_problem_handlers(application)

    tenant_id = uuid4()
    actor = ActorContext(person_id=uuid4(), session_id=uuid4(), tenant_id=tenant_id)
    database = _AsyncDatabase(Session(create_engine("sqlite://")))

    async def require_actor(_request: Request) -> AsyncIterator[AuthenticatedTransaction]:
        yield AuthenticatedTransaction(
            database=database,  # type: ignore[arg-type]
            identity=SimpleNamespace(),  # type: ignore[arg-type]
            resolved=ResolvedActorContext(
                actor=actor,
                membership_role="learner",
                person_revision=0,
                session_revision=0,
            ),
            token="telemetry-session-token",  # noqa: S106
        )

    install_telemetry_http(
        application,
        settings=Settings(
            environment="test",
            public_app_url="https://app.authorityclosers.test",
            admin_app_url="https://admin.authorityclosers.test",
            api_url="https://api.authorityclosers.test",
        ),
        require_actor=require_actor,
        retention_days=30,
        retention_policy_id="learner-telemetry-v1",
    )
    response = TestClient(application).post(
        "/v1/telemetry/events",
        json={"events": [_event(actor)]},
        headers=_headers(),
    )

    assert response.status_code == 503
    assert response.json()["code"] == "telemetry_consent_unavailable"


def test_missing_tenant_context_is_rejected_before_consent_or_storage(
    telemetry_harness: tuple[TestClient, Session, ActorContext, dict[str, object]],
) -> None:
    _client, session, _actor, state = telemetry_harness
    tenantless_actor = ActorContext(person_id=uuid4(), session_id=uuid4(), tenant_id=None)
    database = _AsyncDatabase(session)
    application = FastAPI()
    register_problem_handlers(application)

    async def require_actor(_request: Request) -> AsyncIterator[AuthenticatedTransaction]:
        yield AuthenticatedTransaction(
            database=database,  # type: ignore[arg-type]
            identity=SimpleNamespace(),  # type: ignore[arg-type]
            resolved=ResolvedActorContext(
                actor=tenantless_actor,
                membership_role="learner",
                person_revision=0,
                session_revision=0,
            ),
            token="telemetry-session-token",  # noqa: S106
        )

    install_telemetry_http(
        application,
        settings=state["settings"],  # type: ignore[arg-type]
        require_actor=require_actor,
        consent_resolver=lambda _database, _actor: None,
        retention_days=30,
        retention_policy_id="learner-telemetry-v1",
        admission=_Admission(),
    )
    response = TestClient(application).post(
        "/v1/telemetry/events",
        json={"events": [_event(tenantless_actor)]},
        headers=_headers(),
    )

    assert response.status_code == 403
    assert response.json()["code"] == "telemetry_tenant_context_required"
    assert session.query(AnalyticsEvent).count() == 0


def test_denied_consent_drops_batch_without_persisting(
    telemetry_harness: tuple[TestClient, Session, ActorContext, dict[str, object]],
) -> None:
    client, session, actor, state = telemetry_harness
    state["consent"] = TelemetryConsent(
        status=TelemetryConsentStatus.DENIED,
        policy_version="consent-v1",
        captured_at=datetime.now(UTC),
        tenant_id=actor.tenant_id,
        person_id=actor.person_id,
        session_id=actor.session_id,
    )

    response = client.post(
        "/v1/telemetry/events",
        json={"events": [_event(actor)]},
        headers=_headers(),
    )

    assert response.status_code == 202
    assert response.json()["accepted"] == 0
    assert response.json()["dropped"] == 1
    assert response.json()["reason"] == "consent_required"
    assert session.query(AnalyticsEvent).count() == 0


def test_consent_revoke_between_checks_drops_and_does_not_insert(
    telemetry_harness: tuple[TestClient, Session, ActorContext, dict[str, object]],
) -> None:
    client, session, actor, state = telemetry_harness
    state["revoke_on_second"] = True

    response = client.post(
        "/v1/telemetry/events",
        json={"events": [_event(actor)]},
        headers=_headers(),
    )

    assert response.status_code == 202
    assert response.json()["accepted"] == 0
    assert response.json()["dropped"] == 1
    assert response.json()["reason"] == "consent_required"
    assert state["consent_calls"] == 2
    assert session.query(AnalyticsEvent).count() == 0


def test_admission_seam_rejects_before_storage(
    telemetry_harness: tuple[TestClient, Session, ActorContext, dict[str, object]],
) -> None:
    client, session, actor, state = telemetry_harness
    admission = state["admission"]
    assert isinstance(admission, _Admission)
    admission.reject = True

    response = client.post(
        "/v1/telemetry/events",
        json={"events": [_event(actor)]},
        headers=_headers(),
    )

    assert response.status_code == 503
    assert response.json()["code"] == "telemetry_backpressure"
    assert len(admission.calls) == 1
    assert admission.calls[0][0] == actor.tenant_id
    assert admission.calls[0][1] == 1
    assert admission.calls[0][2] > 0
    assert session.query(AnalyticsEvent).count() == 0


def test_missing_tenant_aware_admission_fails_closed_before_storage(
    telemetry_harness: tuple[TestClient, Session, ActorContext, dict[str, object]],
) -> None:
    _client, session, actor, state = telemetry_harness
    application = FastAPI()
    register_problem_handlers(application)
    require_actor = state["require_actor"]
    settings = state["settings"]
    install_telemetry_http(
        application,
        settings=settings,  # type: ignore[arg-type]
        require_actor=require_actor,  # type: ignore[arg-type]
        consent_resolver=lambda _database, _actor: _granted_consent(actor),
        retention_days=30,
        retention_policy_id="learner-telemetry-v1",
    )
    response = TestClient(application).post(
        "/v1/telemetry/events",
        json={"events": [_event(actor)]},
        headers=_headers(),
    )

    assert response.status_code == 503
    assert response.json()["code"] == "telemetry_admission_unavailable"
    assert session.query(AnalyticsEvent).count() == 0


def test_consent_identity_mismatch_is_rejected_without_storage(
    telemetry_harness: tuple[TestClient, Session, ActorContext, dict[str, object]],
) -> None:
    client, session, actor, state = telemetry_harness
    state["consent"] = _granted_consent(actor, session_id=uuid4())

    response = client.post(
        "/v1/telemetry/events",
        json={"events": [_event(actor)]},
        headers=_headers(),
    )

    assert response.status_code == 403
    assert response.json()["code"] == "telemetry_consent_identity_mismatch"
    assert session.query(AnalyticsEvent).count() == 0


@pytest.mark.parametrize("field", ["tenant_id", "person_id"])
def test_consent_tenant_or_person_mismatch_is_rejected(
    telemetry_harness: tuple[TestClient, Session, ActorContext, dict[str, object]],
    field: str,
) -> None:
    client, session, actor, state = telemetry_harness
    state["consent"] = _granted_consent(actor, **{field: uuid4()})

    response = client.post(
        "/v1/telemetry/events",
        json={"events": [_event(actor)]},
        headers=_headers(),
    )

    assert response.status_code == 403
    assert response.json()["code"] == "telemetry_consent_identity_mismatch"
    assert session.query(AnalyticsEvent).count() == 0


def test_non_uuid_event_id_is_rejected_without_storage(
    telemetry_harness: tuple[TestClient, Session, ActorContext, dict[str, object]],
) -> None:
    client, session, actor, _state = telemetry_harness
    response = client.post(
        "/v1/telemetry/events",
        json={"events": [_event(actor, event_id="client-secret-looking-id")]},
        headers=_headers(),
    )

    assert response.status_code == 422
    assert response.json()["code"] == "telemetry_event_invalid"
    assert session.query(AnalyticsEvent).count() == 0


def test_trace_id_is_server_owned_even_when_request_header_is_supplied(
    telemetry_harness: tuple[TestClient, Session, ActorContext, dict[str, object]],
) -> None:
    client, session, actor, _state = telemetry_harness
    client_trace = "client-secret-looking-request-id"
    response = client.post(
        "/v1/telemetry/events",
        json={"events": [_event(actor)]},
        headers=_headers() | {"x-request-id": client_trace},
    )

    assert response.status_code == 202
    assert response.json()["trace_id"] != client_trace
    assert session.query(AnalyticsEvent).one().trace_id != client_trace


@pytest.mark.parametrize(
    ("mutation", "code"),
    [
        ({"session_id": str(uuid4())}, "telemetry_session_binding_denied"),
        ({"event_name": "activity.completed"}, "telemetry_event_invalid"),
        ({"tenant_id": str(uuid4())}, "telemetry_event_invalid"),
        ({"trace_id": "client-secret-looking-trace"}, "telemetry_event_invalid"),
        ({"release_id": "client-release"}, "telemetry_event_invalid"),
        ({"payload": {"email": "learner@example.test"}}, "telemetry_event_invalid"),
        ({"payload": {"unexpected": "value"}}, "telemetry_event_invalid"),
        ({"route": "/learning/plans?secret=1"}, "telemetry_event_invalid"),
    ],
)
def test_binding_allowlist_and_privacy_rejections_are_fail_closed(
    telemetry_harness: tuple[TestClient, Session, ActorContext, dict[str, object]],
    mutation: dict[str, object],
    code: str,
) -> None:
    client, session, actor, _state = telemetry_harness
    event = _event(actor) | mutation

    response = client.post(
        "/v1/telemetry/events",
        json={"events": [event]},
        headers=_headers(),
    )

    assert response.status_code in {403, 422}
    assert response.json()["code"] == code
    assert session.query(AnalyticsEvent).count() == 0


def test_timestamp_batch_bounds_and_replay_conflicts_are_enforced(
    telemetry_harness: tuple[TestClient, Session, ActorContext, dict[str, object]],
) -> None:
    client, session, actor, _state = telemetry_harness
    old_event = _event(actor, event_id=str(uuid4())) | {
        "occurred_at": (datetime.now(UTC) - timedelta(days=8)).isoformat()
    }
    old = client.post("/v1/telemetry/events", json={"events": [old_event]}, headers=_headers())
    assert old.status_code == 422
    assert old.json()["code"] == "telemetry_event_invalid"

    original_event = _event(actor)
    first = client.post(
        "/v1/telemetry/events",
        json={"events": [original_event]},
        headers=_headers(),
    )
    duplicate = client.post(
        "/v1/analytics/events/batch",
        json={"events": [original_event]},
        headers=_headers(),
    )
    conflict = client.post(
        "/v1/telemetry/events",
        json={"events": [original_event | {"route": "/progress"}]},
        headers=_headers(),
    )

    assert first.status_code == 202
    assert duplicate.status_code == 202
    assert duplicate.json()["accepted"] == 0
    assert duplicate.json()["duplicate"] == 1
    assert conflict.status_code == 409
    assert conflict.json()["code"] == "telemetry_idempotency_conflict"
    assert session.query(AnalyticsEvent).count() == 1

    too_many = client.post(
        "/v1/telemetry/events",
        json={
            "events": [
                _event(actor, event_id=str(uuid4())) for index in range(MAX_BATCH_EVENTS + 1)
            ]
        },
        headers=_headers(),
    )
    assert too_many.status_code == 422
    assert too_many.json()["code"] == "telemetry_event_invalid"


def test_taxonomy_is_authenticated_and_server_owned(
    telemetry_harness: tuple[TestClient, Session, ActorContext, dict[str, object]],
) -> None:
    client, _session, _actor, _state = telemetry_harness

    response = client.get("/v1/telemetry/taxonomy")

    assert response.status_code == 200
    assert response.json()["ingest_path"] == "/v1/telemetry/events"
    names = {event["event_name"] for event in response.json()["events"]}
    assert names == {
        "analytics.plan_viewed",
        "analytics.plan_period_selected",
        "analytics.up_next_opened",
        "analytics.progress_viewed",
        "analytics.insight_viewed",
    }
