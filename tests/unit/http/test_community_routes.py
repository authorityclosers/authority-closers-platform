from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import ac_platform.http.community as community_http
from ac_platform.application.settings import Settings
from ac_platform.community.application import (
    InvalidLeaderboardCursor,
    UsernameReserved,
    UsernameUnavailable,
)
from ac_platform.http.community import install_community_http
from ac_platform.http.problem import register_problem_handlers
from ac_platform.kernel.authz import ActorContext


class FakeCommunityApplication:
    calls: list[tuple[object, ...]] = []

    def __init__(self, _database: object) -> None:
        pass

    async def profile(self, actor: ActorContext) -> dict[str, object]:
        self.calls.append(("profile", actor))
        return {
            "username": "learner_7",
            "leaderboard_opted_in": False,
            "revision": 1,
            "leaderboard_policy": {
                "version": "all_time_practice_xp_v1",
                "period": "all_time",
                "measure": "confirmed_practice_xp",
                "ranking": "competition",
                "privacy": "academy_opt_in",
            },
        }

    async def claim_username(self, actor: ActorContext, username: str) -> dict[str, object]:
        self.calls.append(("claim", actor, username))
        if username == "taken_name":
            raise UsernameUnavailable("That username is unavailable. Choose another.")
        if username == "admin":
            raise UsernameReserved("That username is reserved for account safety.")
        return await self.profile(actor)

    async def set_leaderboard_opt_in(
        self,
        actor: ActorContext,
        *,
        opted_in: bool,
        expected_revision: int,
    ) -> dict[str, object]:
        self.calls.append(("opt-in", actor, opted_in, expected_revision))
        return {
            "username": "learner_7",
            "leaderboard_opted_in": opted_in,
            "revision": expected_revision + 1,
            "leaderboard_policy": {
                "version": "all_time_practice_xp_v1",
                "period": "all_time",
                "measure": "confirmed_practice_xp",
                "ranking": "competition",
                "privacy": "academy_opt_in",
            },
        }

    async def leaderboard(
        self,
        actor: ActorContext,
        *,
        limit: int,
        cursor: str | None,
    ) -> dict[str, object]:
        self.calls.append(("leaderboard", actor, limit, cursor))
        if cursor == "malformed":
            raise InvalidLeaderboardCursor("The leaderboard cursor is not valid.")
        return {
            "policy": {
                "version": "all_time_practice_xp_v1",
                "label": "All-time practice XP",
                "period": "all_time",
                "ranking": "competition",
                "scope": "academy",
            },
            "items": [
                {
                    "rank": 1,
                    "username": "learner_7",
                    "xp_total": 90,
                    "is_current_learner": True,
                }
            ],
            "next_cursor": None,
        }


def settings() -> Settings:
    return Settings(
        environment="test",
        database_url="postgresql+psycopg://unused:unused@localhost/unused",
        database_migrator_url="postgresql+psycopg://unused:unused@localhost/unused",
        session_token_pepper="test-session-token-pepper-that-is-long-enough",  # noqa: S106
        oauth_transaction_secret="test-oauth-secret-that-is-long-enough",  # noqa: S106
        public_app_url="https://app.authorityclosers.test",
        admin_app_url="https://admin.authorityclosers.test",
        api_url="https://api.authorityclosers.test",
    )


def client(
    monkeypatch: pytest.MonkeyPatch,
    *,
    role: str = "learner",
) -> tuple[TestClient, ActorContext]:
    actor = ActorContext(person_id=uuid4(), session_id=uuid4(), tenant_id=uuid4())
    auth = SimpleNamespace(
        resolved=SimpleNamespace(actor=actor, membership_role=role),
        database=object(),
    )

    async def require_actor():  # type: ignore[no-untyped-def]
        return auth

    FakeCommunityApplication.calls = []
    monkeypatch.setattr(community_http, "CommunityApplication", FakeCommunityApplication)
    app = FastAPI()
    register_problem_handlers(app)
    install_community_http(app, settings=settings(), require_actor=require_actor)
    return TestClient(app), actor


def test_profile_is_self_scoped_and_does_not_expose_email(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    test_client, actor = client(monkeypatch)

    response = test_client.get("/v1/community/profile")

    assert response.status_code == 200
    assert response.json()["username"] == "learner_7"
    assert "email" not in response.text
    assert FakeCommunityApplication.calls == [("profile", actor)]


@pytest.mark.parametrize("origin", [None, "https://evil.example"])
def test_username_claim_requires_safe_origin(
    monkeypatch: pytest.MonkeyPatch,
    origin: str | None,
) -> None:
    test_client, _ = client(monkeypatch)
    headers = {} if origin is None else {"Origin": origin}

    response = test_client.put(
        "/v1/community/username",
        headers=headers,
        json={"username": "learner_7"},
    )

    assert response.status_code == 403
    assert FakeCommunityApplication.calls == []


def test_username_claim_defers_normalized_length_to_the_domain(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    test_client, actor = client(monkeypatch)
    username = f"  {'a' * 30}  "

    response = test_client.put(
        "/v1/community/username",
        headers={"Origin": "https://app.authorityclosers.test"},
        json={"username": username},
    )

    assert response.status_code == 200
    assert FakeCommunityApplication.calls == [("claim", actor, username), ("profile", actor)]

    oversized = test_client.put(
        "/v1/community/username",
        headers={"Origin": "https://app.authorityclosers.test"},
        json={"username": "a" * 129},
    )
    assert oversized.status_code == 422
    assert FakeCommunityApplication.calls == [("claim", actor, username), ("profile", actor)]


def test_opt_in_is_explicit_and_revision_guarded(monkeypatch: pytest.MonkeyPatch) -> None:
    test_client, actor = client(monkeypatch)

    response = test_client.put(
        "/v1/community/leaderboard-opt-in",
        headers={"Origin": "https://app.authorityclosers.test"},
        json={"opted_in": True, "expected_revision": 4},
    )

    assert response.status_code == 200
    assert response.json()["leaderboard_opted_in"] is True
    assert FakeCommunityApplication.calls == [("opt-in", actor, True, 4)]


def test_leaderboard_is_learner_tenant_scoped_and_public_fields_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    test_client, actor = client(monkeypatch)

    response = test_client.get("/v1/community/leaderboard?limit=10&cursor=opaque")

    assert response.status_code == 200
    assert FakeCommunityApplication.calls == [("leaderboard", actor, 10, "opaque")]
    assert set(response.json()["items"][0]) == {
        "rank",
        "username",
        "xp_total",
        "is_current_learner",
    }
    assert "email" not in response.text

    denied, _ = client(monkeypatch, role="admin")
    assert denied.get("/v1/community/leaderboard").status_code == 403


def test_malformed_leaderboard_cursor_returns_422(monkeypatch: pytest.MonkeyPatch) -> None:
    test_client, _ = client(monkeypatch)

    response = test_client.get("/v1/community/leaderboard?cursor=malformed")

    assert response.status_code == 422
    assert response.json()["code"] == "leaderboard_cursor_invalid"


@pytest.mark.parametrize(
    ("username", "status", "code"),
    [("taken_name", 409, "username_unavailable"), ("admin", 422, "username_reserved")],
)
def test_username_rejections_use_the_canonical_problem_envelope(
    monkeypatch: pytest.MonkeyPatch, username: str, status: int, code: str
) -> None:
    test_client, _ = client(monkeypatch)
    response = test_client.put(
        "/v1/community/username",
        headers={"Origin": "https://app.authorityclosers.test"},
        json={"username": username},
    )
    assert response.status_code == status
    assert response.headers["content-type"] == "application/problem+json"
    assert response.json()["code"] == code
    assert isinstance(response.json()["detail"], str)


@pytest.mark.parametrize(
    "query", ["tenant_id=untrusted", "limit=10&limit=20", "cursor=one&cursor=two"]
)
def test_leaderboard_rejects_account_or_tenant_query_selectors(
    monkeypatch: pytest.MonkeyPatch,
    query: str,
) -> None:
    test_client, _ = client(monkeypatch)

    response = test_client.get(f"/v1/community/leaderboard?{query}")

    assert response.status_code == 422
    assert FakeCommunityApplication.calls == []
