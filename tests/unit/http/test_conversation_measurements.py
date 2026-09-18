"""HTTP scope and response-boundary tests; service authorization has separate DB proof."""

from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import APIRouter, FastAPI, HTTPException
from fastapi.testclient import TestClient

from ac_platform.conversation_intelligence.application import ConversationDenied
from ac_platform.http import conversation_measurements as measurement_http


@pytest.fixture
def surface(monkeypatch):
    actor = object()
    database = object()
    calls = []
    state = {"authenticated": True, "denied": False}

    async def require_actor():
        if not state["authenticated"]:
            raise HTTPException(401, "Sign in required.")
        yield SimpleNamespace(database=database, resolved=SimpleNamespace(actor=actor))

    class Service:
        def __init__(self, application):
            assert application.database is database

        async def get(self, resolved_actor, recording_id):
            assert resolved_actor is actor
            calls.append(recording_id)
            if state["denied"]:
                raise ConversationDenied("Recording access is unavailable.")
            return {"recording_id": str(recording_id), "status": "available"}

    monkeypatch.setattr(measurement_http, "ConversationMeasurements", Service)
    app = FastAPI()
    router = APIRouter(prefix="/v1/conversation")
    measurement_http.install_measurement_routes(router, require_actor)
    app.include_router(router)
    with TestClient(app) as client:
        yield client, calls, state


def test_current_actor_and_exact_recording_reach_the_service_with_private_response(surface):
    client, calls, _ = surface
    recording_id = uuid4()
    response = client.get(f"/v1/conversation/recordings/{recording_id}/measurements")
    assert response.status_code == 200
    assert response.json() == {"recording_id": str(recording_id), "status": "available"}
    assert response.headers["cache-control"] == "private, no-store"
    assert calls == [recording_id]


def test_anonymous_request_never_reads_measurements(surface):
    client, calls, state = surface
    state["authenticated"] = False
    response = client.get(f"/v1/conversation/recordings/{uuid4()}/measurements")
    assert response.status_code == 401
    assert calls == []


@pytest.mark.parametrize("selector", ["tenant_id", "person_id", "checkpoint_id"])
def test_client_scope_selectors_are_refused_before_service_read(surface, selector):
    client, calls, _ = surface
    response = client.get(
        f"/v1/conversation/recordings/{uuid4()}/measurements", params={selector: str(uuid4())}
    )
    assert response.status_code == 422
    assert response.headers["cache-control"] == "private, no-store"
    assert calls == []


def test_denied_recording_returns_no_measurement_body_or_cacheable_response(surface):
    client, _, state = surface
    state["denied"] = True
    response = client.get(f"/v1/conversation/recordings/{uuid4()}/measurements")
    assert response.status_code == 403
    assert response.json() == {"detail": "Recording access is unavailable."}
    assert response.headers["cache-control"] == "private, no-store"


def test_measurement_route_accepts_no_write_method(surface):
    client, calls, _ = surface
    response = client.post(f"/v1/conversation/recordings/{uuid4()}/measurements", json={})
    assert response.status_code == 405
    assert calls == []
