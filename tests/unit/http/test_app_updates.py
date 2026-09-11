from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

import ac_platform.http.app_updates as app_updates_http
from ac_platform.app_updates.application import AppUpdateUnavailable
from ac_platform.application.settings import Settings
from ac_platform.http.app_updates import AppUpdateItemResponse, install_app_updates_http
from ac_platform.http.problem import register_problem_handlers
from ac_platform.kernel.authz import ActorContext

RELEASE_ID = "app-updates-v0-2-alpha"
PUBLIC_ORIGIN = "https://app.authorityclosers.test"


class FakeAppUpdatesApplication:
    calls: list[tuple[object, ...]] = []

    def __init__(self, _database: object) -> None:
        pass

    @staticmethod
    def response(actor: ActorContext, *, read: bool) -> dict[str, object]:
        assert actor.tenant_id is not None
        return {
            "person_id": actor.person_id,
            "tenant_id": actor.tenant_id,
            "items": [
                {
                    "id": RELEASE_ID,
                    "title": "A home for app updates",
                    "message": "Factual learner-app release notes.",
                    "version": "v0.2 Alpha",
                    "highlights": ["Read state is saved to your learner account."],
                    "target_href": "/notifications",
                    "created_at": datetime(2026, 9, 10, tzinfo=UTC),
                    "read": read,
                }
            ],
            "unread_count": 0 if read else 1,
        }

    async def list_updates(self, actor: ActorContext) -> dict[str, object]:
        self.calls.append(("list", actor))
        return self.response(actor, read=False)

    async def mark_read(self, actor: ActorContext, release_id: str) -> dict[str, object]:
        self.calls.append(("read", actor, release_id))
        if release_id == "unknown-release":
            raise AppUpdateUnavailable("The requested app update is unavailable.")
        return self.response(actor, read=True)


def settings() -> Settings:
    return Settings(
        environment="test",
        database_url="postgresql+psycopg://unused:unused@localhost/unused",
        database_migrator_url="postgresql+psycopg://unused:unused@localhost/unused",
        session_token_pepper="test-session-token-pepper-that-is-long-enough",  # noqa: S106
        oauth_transaction_secret="test-oauth-secret-that-is-long-enough",  # noqa: S106
        public_app_url=PUBLIC_ORIGIN,
        admin_app_url="https://admin.authorityclosers.test",
        api_url="https://api.authorityclosers.test",
    )


def client(
    monkeypatch: pytest.MonkeyPatch,
    *,
    role: str | None = "learner",
    selected_academy: bool = True,
    base_url: str = PUBLIC_ORIGIN,
) -> tuple[TestClient, ActorContext]:
    actor = ActorContext(
        person_id=uuid4(),
        session_id=uuid4(),
        tenant_id=uuid4() if selected_academy else None,
    )
    auth = SimpleNamespace(
        resolved=SimpleNamespace(actor=actor, membership_role=role),
        database=object(),
    )

    async def require_actor():  # type: ignore[no-untyped-def]
        return auth

    FakeAppUpdatesApplication.calls = []
    monkeypatch.setattr(
        app_updates_http,
        "AppUpdatesApplication",
        FakeAppUpdatesApplication,
    )
    app = FastAPI()
    register_problem_handlers(app)
    install_app_updates_http(app, settings=settings(), require_actor=require_actor)
    return TestClient(app, base_url=base_url), actor


def test_get_is_authenticated_actor_scoped_and_private(monkeypatch: pytest.MonkeyPatch) -> None:
    test_client, actor = client(monkeypatch)

    response = test_client.get("/v1/me/app-updates")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "private, no-store"
    assert response.headers["pragma"] == "no-cache"
    assert response.json()["person_id"] == str(actor.person_id)
    assert response.json()["tenant_id"] == str(actor.tenant_id)
    assert response.json()["unread_count"] == 1
    assert set(response.json()["items"][0]) == {
        "id",
        "title",
        "message",
        "version",
        "highlights",
        "target_href",
        "created_at",
        "read",
    }
    assert "email" not in response.text
    assert FakeAppUpdatesApplication.calls == [("list", actor)]


@pytest.mark.parametrize(
    ("role", "selected_academy"),
    [("admin", True), (None, True), ("learner", False)],
)
def test_get_requires_a_selected_learner_membership_and_keeps_denials_private(
    monkeypatch: pytest.MonkeyPatch,
    role: str | None,
    selected_academy: bool,
) -> None:
    test_client, _ = client(
        monkeypatch,
        role=role,
        selected_academy=selected_academy,
    )

    response = test_client.get("/v1/me/app-updates")

    assert response.status_code == 403
    assert response.headers["cache-control"] == "private, no-store"
    assert FakeAppUpdatesApplication.calls == []


def test_get_requires_the_configured_learner_surface(monkeypatch: pytest.MonkeyPatch) -> None:
    test_client, _ = client(
        monkeypatch,
        base_url="https://admin.authorityclosers.test",
    )

    response = test_client.get("/v1/me/app-updates")

    assert response.status_code == 403
    assert response.headers["cache-control"] == "private, no-store"
    assert FakeAppUpdatesApplication.calls == []


def test_get_uses_the_preserved_host_not_forwarded_authority(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    test_client, actor = client(
        monkeypatch,
        base_url="http://127.0.0.1:8000",
    )

    response = test_client.get(
        "/v1/me/app-updates",
        headers={
            "Host": "app.authorityclosers.test",
            "Forwarded": "host=admin.authorityclosers.test;proto=https",
            "X-Forwarded-Host": "admin.authorityclosers.test",
            "X-Forwarded-Proto": "https",
        },
    )

    assert response.status_code == 200
    assert FakeAppUpdatesApplication.calls == [("list", actor)]


def test_get_does_not_trust_forwarded_learner_authority(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    test_client, _ = client(
        monkeypatch,
        base_url="http://127.0.0.1:8000",
    )

    response = test_client.get(
        "/v1/me/app-updates",
        headers={
            "X-Forwarded-Host": "app.authorityclosers.test",
            "X-Forwarded-Proto": "https",
        },
    )

    assert response.status_code == 403
    assert FakeAppUpdatesApplication.calls == []


def test_get_rejects_account_and_tenant_selectors(monkeypatch: pytest.MonkeyPatch) -> None:
    test_client, _ = client(monkeypatch)

    response = test_client.get("/v1/me/app-updates?person_id=untrusted")

    assert response.status_code == 422
    assert response.headers["cache-control"] == "private, no-store"
    assert FakeAppUpdatesApplication.calls == []


@pytest.mark.parametrize("origin", [None, "https://evil.example"])
def test_mark_read_requires_safe_origin_and_keeps_denials_private(
    monkeypatch: pytest.MonkeyPatch,
    origin: str | None,
) -> None:
    test_client, _ = client(monkeypatch)
    headers = {} if origin is None else {"Origin": origin}

    response = test_client.post(
        f"/v1/me/app-updates/{RELEASE_ID}/read",
        headers=headers,
    )

    assert response.status_code == 403
    assert response.headers["cache-control"] == "private, no-store"
    assert FakeAppUpdatesApplication.calls == []


def test_mark_read_accepts_no_person_or_tenant_body(monkeypatch: pytest.MonkeyPatch) -> None:
    test_client, actor = client(monkeypatch)

    response = test_client.post(
        f"/v1/me/app-updates/{RELEASE_ID}/read",
        headers={"Origin": PUBLIC_ORIGIN},
        json={"person_id": str(actor.person_id)},
    )

    assert response.status_code == 422
    assert response.headers["cache-control"] == "private, no-store"
    assert FakeAppUpdatesApplication.calls == []


def test_csrf_rejection_precedes_untrusted_body_validation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    test_client, actor = client(monkeypatch)

    response = test_client.post(
        f"/v1/me/app-updates/{RELEASE_ID}/read",
        headers={"Origin": "https://evil.example"},
        json={"person_id": str(actor.person_id)},
    )

    assert response.status_code == 403
    assert response.headers["cache-control"] == "private, no-store"
    assert FakeAppUpdatesApplication.calls == []


def test_mark_read_returns_the_self_scoped_updated_resource(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    test_client, actor = client(monkeypatch)

    response = test_client.post(
        f"/v1/me/app-updates/{RELEASE_ID}/read",
        headers={"Origin": PUBLIC_ORIGIN},
    )

    assert response.status_code == 200
    assert response.json()["items"][0]["read"] is True
    assert response.json()["unread_count"] == 0
    assert FakeAppUpdatesApplication.calls == [("read", actor, RELEASE_ID)]


def test_unknown_release_uses_one_private_canonical_rejection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    test_client, _ = client(monkeypatch)

    response = test_client.post(
        "/v1/me/app-updates/unknown-release/read",
        headers={"Origin": PUBLIC_ORIGIN},
    )

    assert response.status_code == 404
    assert response.headers["cache-control"] == "private, no-store"
    assert response.headers["content-type"] == "application/problem+json"
    assert response.json()["code"] == "app_update_unavailable"


def test_path_validation_errors_are_private(monkeypatch: pytest.MonkeyPatch) -> None:
    test_client, _ = client(monkeypatch)

    response = test_client.post(
        "/v1/me/app-updates/INVALID/read",
        headers={"Origin": PUBLIC_ORIGIN},
    )

    assert response.status_code == 422
    assert response.headers["cache-control"] == "private, no-store"
    assert FakeAppUpdatesApplication.calls == []


def test_response_schema_rejects_an_unsafe_feature_target() -> None:
    with pytest.raises(ValidationError, match="release targets"):
        AppUpdateItemResponse(
            id=RELEASE_ID,
            title="A home for app updates",
            message="Factual learner-app release notes.",
            version="v0.2 Alpha",
            highlights=["Read state is saved to your learner account."],
            target_href="/%2f/evil.example",
            created_at=datetime(2026, 9, 10, tzinfo=UTC),
            read=False,
        )
