"""Host, session, CSRF, validation and private-header contracts for product routes."""

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from ac_platform.application.settings import Settings
from ac_platform.http.problem import register_problem_handlers
from ac_platform.http.product_updates import install_product_updates_http
from ac_platform.kernel.authz import ActorContext

ORIGIN = "https://sales.authorityclosers.test"
PATHS = [
    "/v1/updates",
    "/v1/notifications",
    "/v1/updates/seen",
    "/v1/notifications/read",
    "/v1/notifications/read-all",
]


class FakeReading:
    calls = []

    def __init__(self, database, actor, **options):
        self.calls.append(("init", actor, options))

    async def updates(self, since):
        self.calls.append(("updates", since))
        return {"updates": [], "unseen_count": 0}

    async def notifications(self):
        self.calls.append(("notifications",))
        return {"notifications": [], "unread_count": 0}

    async def mark_seen(self, keys):
        self.calls.append(("seen", keys))
        return {"unseen_count": 0}

    async def mark_read(self, ids):
        self.calls.append(("read", ids))
        return {"unread_count": 0}

    async def mark_all_read(self):
        self.calls.append(("read-all",))
        return {"unread_count": 0}


def client(monkeypatch, *, host=ORIGIN, signed_in=True, selected_workspace=True, configured=True):
    import ac_platform.http.product_updates as module

    FakeReading.calls = []
    monkeypatch.setattr(module, "ProductUpdatesReading", FakeReading)
    settings = Settings(
        _env_file=None, environment="test", sales_xray_app_url=ORIGIN if configured else None
    )
    actor = ActorContext(uuid4(), uuid4(), uuid4() if selected_workspace else None)

    async def require_actor():
        if not signed_in:
            raise HTTPException(401, "Sign in.")
        return SimpleNamespace(database=object(), resolved=SimpleNamespace(actor=actor))

    app = FastAPI()
    app.state.internal_tester_policy = object()
    register_problem_handlers(app)
    install_product_updates_http(app, settings=settings, require_actor=require_actor)
    return TestClient(app, base_url=host), actor, app


def request(test_client, path, **options):
    if path in PATHS[:2]:
        return test_client.get(path, **options)
    payload = (
        {}
        if path.endswith("read-all")
        else {"keys": ["note"]}
        if path.endswith("seen")
        else {"ids": ["updates:release"]}
    )
    return test_client.post(path, json=payload, **options)


@pytest.mark.parametrize("path", PATHS)
@pytest.mark.parametrize("selected_workspace", [False, True])
async def test_routes_accept_any_signed_in_account_and_are_private(
    monkeypatch, path, selected_workspace
):
    test_client, actor, app = client(monkeypatch, selected_workspace=selected_workspace)
    response = request(test_client, path, headers={"Origin": ORIGIN})
    assert response.status_code == 200
    assert response.headers["cache-control"] == "private, no-store"
    assert FakeReading.calls[0] == (
        "init",
        actor,
        {"environment": "test", "tester_policy": app.state.internal_tester_policy},
    )


@pytest.mark.parametrize("path", PATHS)
def test_no_session_is_refused_with_private_headers(monkeypatch, path):
    test_client, _, _ = client(monkeypatch, signed_in=False)
    response = request(test_client, path, headers={"Origin": ORIGIN})
    assert response.status_code == 401
    assert response.headers["cache-control"] == "private, no-store"
    assert not FakeReading.calls


@pytest.mark.parametrize("path", PATHS)
@pytest.mark.parametrize(
    "host",
    ["http://localhost:3000", "https://admin.authorityclosers.test", "http://127.0.0.1:8000"],
)
def test_other_hosts_are_404_and_forwarded_host_cannot_admit(monkeypatch, path, host):
    test_client, _, _ = client(monkeypatch, host=host)
    response = request(
        test_client,
        path,
        headers={"Origin": ORIGIN, "X-Forwarded-Host": "sales.authorityclosers.test"},
    )
    assert response.status_code == 404
    assert response.headers["cache-control"] == "private, no-store"
    assert not FakeReading.calls


def test_unconfigured_sales_host_is_closed(monkeypatch):
    test_client, _, _ = client(monkeypatch, configured=False)
    assert test_client.get("/v1/updates").status_code == 404


@pytest.mark.parametrize("path", PATHS[2:])
@pytest.mark.parametrize("origin", [None, "https://evil.example", "http://localhost:3000"])
def test_write_requires_safe_origin(monkeypatch, path, origin):
    test_client, _, _ = client(monkeypatch)
    response = request(test_client, path, headers={} if origin is None else {"Origin": origin})
    assert response.status_code == 403
    assert response.headers["cache-control"] == "private, no-store"
    assert not FakeReading.calls


@pytest.mark.parametrize(
    "since", ["bad", "2026-10-05", "2026-10-05T12:00:00", "2026-10-05T12:00:00+01:00"]
)
def test_bad_since_is_422_and_private(monkeypatch, since):
    test_client, _, _ = client(monkeypatch)
    response = test_client.get("/v1/updates", params={"since": since})
    assert response.status_code == 422
    assert response.headers["cache-control"] == "private, no-store"
    assert not FakeReading.calls


@pytest.mark.parametrize("since", ["2026-10-05T12:00:00Z", "2026-10-05T12:00:00+00:00"])
def test_valid_since_reaches_reading_as_utc(monkeypatch, since):
    test_client, _, _ = client(monkeypatch)
    assert test_client.get("/v1/updates", params={"since": since}).status_code == 200
    assert FakeReading.calls[-1] == ("updates", datetime(2026, 10, 5, 12, tzinfo=UTC))


@pytest.mark.parametrize("path,field", [(PATHS[2], "keys"), (PATHS[3], "ids")])
@pytest.mark.parametrize("values", [[], ["x"] * 101, [1], [""], ["x" * 137]])
def test_post_limits_are_422_and_private(monkeypatch, path, field, values):
    test_client, _, _ = client(monkeypatch)
    response = test_client.post(path, json={field: values}, headers={"Origin": ORIGIN})
    assert response.status_code == 422
    assert response.headers["cache-control"] == "private, no-store"
    assert not FakeReading.calls


def test_csrf_guard_runs_before_body_validation(monkeypatch):
    test_client, _, _ = client(monkeypatch)
    assert test_client.post(PATHS[2], json={"keys": []}).status_code == 403


def test_read_all_is_an_explicit_empty_account_command(monkeypatch):
    test_client, _, _ = client(monkeypatch, selected_workspace=False)
    response = test_client.post(PATHS[4], json={}, headers={"Origin": ORIGIN})
    assert response.status_code == 200 and response.json() == {"unread_count": 0}
    assert FakeReading.calls[-1] == ("read-all",)


@pytest.mark.parametrize("body", [None, [], {"person_id": "neighbor"}, {"ids": []}])
def test_read_all_rejects_missing_body_and_recipient_or_id_overrides(monkeypatch, body):
    test_client, _, _ = client(monkeypatch)
    response = test_client.post(PATHS[4], json=body, headers={"Origin": ORIGIN})
    assert response.status_code == 422
    assert response.headers["cache-control"] == "private, no-store"
    assert not FakeReading.calls


def test_read_all_checks_origin_before_body_validation(monkeypatch):
    test_client, _, _ = client(monkeypatch)
    assert test_client.post(PATHS[4], json={"person_id": "neighbor"}).status_code == 403
    assert not FakeReading.calls


def test_application_discovers_the_product_routes():
    from ac_platform.http.app import create_app

    paths = create_app().openapi()["paths"]
    assert all(path in paths for path in PATHS)
