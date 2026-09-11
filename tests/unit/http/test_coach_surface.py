"""The third web host adds a surface, never a new identity or permission."""

from dataclasses import replace
from types import SimpleNamespace
from typing import Any, cast

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from pydantic import ValidationError

import ac_platform.http.auth as auth_module
from ac_platform.application.settings import Settings
from ac_platform.http.auth import AdminSurfaceRequired, require_admin_surface, require_safe_origin
from ac_platform.http.auth_transactions import AuthTransactionCodec
from ac_platform.http.surfaces import CoachSurfaceMiddleware
from tests.unit.application.test_settings import _deployment_values
from tests.unit.http.test_auth_routes import (
    DEPLOYMENT_OAUTH_COOKIE,
    DEPLOYMENT_SESSION_COOKIE,
    _CallbackIdentityApplication,
    _client,
    _request_with_host_and_origin,
    _staging_settings,
    _SuccessfulProvider,
)

COACH_HOST = "coach-staging.authorityclosers.com"
COACH_ORIGIN = f"https://{COACH_HOST}"
RESOURCE = "10000000-0000-4000-8000-000000000001"


@pytest.mark.parametrize("environment", ["staging", "production"])
def test_exact_coach_and_learner_transition_origins(environment: str) -> None:
    values = _deployment_values(environment)
    values.pop("coach_app_url", None)
    prefix = "-staging" if environment == "staging" else ""
    coach = f"https://coach{prefix}.authorityclosers.com"
    # Existing deployment profiles need not contain the new setting yet.
    settings = Settings(environment=environment, _env_file=None, **values)
    assert str(settings.coach_app_url).rstrip("/") == coach
    assert coach in settings.allowed_origins
    assert settings.coach_app_url.host in settings.allowed_hosts
    values.update(public_app_url=f"https://learner{prefix}.authorityclosers.com")
    settings = Settings(environment=environment, _env_file=None, **values)
    assert str(settings.public_app_url).rstrip("/") == values["public_app_url"]
    assert values["public_app_url"] in settings.allowed_origins
    assert ("staging.authorityclosers.com" if prefix else "app.authorityclosers.com") not in (
        settings.allowed_hosts
    )


@pytest.mark.parametrize(
    "value",
    [
        "https://coach.authorityclosers.com",
        f"{COACH_ORIGIN}.attacker.example",
        f"{COACH_ORIGIN}:443",
        f"{COACH_ORIGIN}/v1",
        f"{COACH_ORIGIN}?",
        f"{COACH_ORIGIN}#",
        "https://user@coach-staging.authorityclosers.com",
    ],
)
def test_coach_deployment_origin_rejects_ambiguous_or_other_environment(value: str) -> None:
    with pytest.raises(ValidationError, match="AC_COACH_APP_URL"):
        Settings(environment="staging", **{**_deployment_values("staging"), "coach_app_url": value})


@pytest.mark.parametrize(
    "value",
    [
        "http://localhost:3102",
        "http://coach.localhost:3102/path",
        "http://coach.localhost:3102?",
        "http://user@coach.localhost:3102",
    ],
)
def test_local_coach_origin_is_distinct_and_not_a_url_with_credentials(value: str) -> None:
    with pytest.raises(ValidationError, match="AC_COACH_APP_URL"):
        Settings(_env_file=None, coach_app_url=value)


@pytest.mark.parametrize("environment", ["local", "test", "development"])
@pytest.mark.parametrize("value", ["http://*.localhost:3102", "http://*:3102"])
def test_coach_origin_never_becomes_a_trusted_host_wildcard(environment: str, value: str) -> None:
    with pytest.raises(ValidationError, match="AC_COACH_APP_URL"):
        Settings(_env_file=None, environment=environment, coach_app_url=value)


@pytest.mark.parametrize("environment", ["test", "staging"])
def test_coach_mutations_require_exact_own_origin_even_in_local_bridge(environment: str) -> None:
    settings = _staging_settings().model_copy(update={"environment": environment})
    require_safe_origin(
        _request_with_host_and_origin(host=COACH_HOST, origin=COACH_ORIGIN), settings
    )
    for host, origin in [
        (COACH_HOST, "https://admin-staging.authorityclosers.com"),
        (COACH_HOST, "https://staging.authorityclosers.com"),
        ("admin-staging.authorityclosers.com", COACH_ORIGIN),
        ("api.staging.ac.internal.invalid", COACH_ORIGIN),
    ]:
        with pytest.raises(auth_module.RequestOriginDenied):
            require_safe_origin(_request_with_host_and_origin(host=host, origin=origin), settings)


def test_coach_never_passes_the_platform_admin_host_guard() -> None:
    request = _request_with_host_and_origin(host=COACH_HOST, origin=COACH_ORIGIN)
    with pytest.raises(AdminSurfaceRequired):
        require_admin_surface(request, _staging_settings())


def test_coach_google_callback_uses_signed_surface_and_host_only_cookie(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(auth_module, "AsyncIdentityApplication", _CallbackIdentityApplication)
    settings = _staging_settings()
    provider = _SuccessfulProvider()
    client = _client(settings=settings, provider=provider)
    started = client.get(
        "/v1/auth/google/start",
        params={"action": "authenticate", "surface": "coach", "return_path": "/studio/programs"},
        headers={"host": COACH_HOST},
        follow_redirects=False,
    )
    assert started.status_code == 303
    codec = AuthTransactionCodec(settings.oauth_transaction_secret.get_secret_value())
    encoded = started.cookies[DEPLOYMENT_OAUTH_COOKIE]
    transaction = codec.decode(encoded)
    assert transaction.surface == "coach"
    response = client.get(
        "/v1/auth/google/callback",
        params={
            "state": transaction.state,
            "code": "google-authorization-code",
            "surface": "admin",
        },
        headers={"host": COACH_HOST, "cookie": f"{DEPLOYMENT_OAUTH_COOKIE}={encoded}"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"] == f"{COACH_ORIGIN}/studio/programs"
    assert provider.redirect_uris == [f"{COACH_ORIGIN}/v1/auth/google/callback"]
    session = next(
        item.lower()
        for item in response.headers.get_list("set-cookie")
        if item.startswith(f"{DEPLOYMENT_SESSION_COOKIE}=")
    )
    assert all(value in session for value in ("secure", "httponly", "samesite=lax", "path=/"))
    assert "domain=" not in session
    # The authenticated transaction cannot be relabelled without a new signature.
    forged = codec.encode(replace(transaction, surface="admin")).split(".")[0]
    with pytest.raises(auth_module.InvalidAuthTransaction):
        codec.decode(f"{forged}.{encoded.split('.')[1]}")


@pytest.mark.parametrize(
    "host", ["admin-staging.authorityclosers.com", "staging.authorityclosers.com"]
)
def test_coach_oauth_rejects_cross_host_start_and_callback(
    host: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(auth_module, "AsyncIdentityApplication", _CallbackIdentityApplication)
    settings = _staging_settings()
    client = _client(settings=settings)
    rejected = client.get(
        "/v1/auth/google/start",
        params={"action": "authenticate", "surface": "coach"},
        headers={"host": host, "x-forwarded-host": COACH_HOST},
        follow_redirects=False,
    )
    assert rejected.status_code == 400
    started = client.get(
        "/v1/auth/google/start",
        params={"action": "authenticate", "surface": "coach"},
        headers={"host": COACH_HOST},
        follow_redirects=False,
    )
    encoded = started.cookies[DEPLOYMENT_OAUTH_COOKIE]
    transaction = AuthTransactionCodec(settings.oauth_transaction_secret.get_secret_value()).decode(
        encoded
    )
    callback = client.get(
        "/v1/auth/google/callback",
        params={"state": transaction.state, "code": "unused"},
        headers={
            "host": host,
            "cookie": f"{DEPLOYMENT_OAUTH_COOKIE}={encoded}",
            "x-forwarded-host": COACH_HOST,
        },
        follow_redirects=False,
    )
    assert callback.status_code == 400
    assert "location" not in callback.headers


def test_coach_google_does_not_provision_a_new_learner_or_role() -> None:
    response = _client(settings=_staging_settings()).get(
        "/v1/auth/google/start",
        params={"action": "register", "surface": "coach", "consent": "true"},
        headers={"host": COACH_HOST},
        follow_redirects=False,
    )
    assert response.status_code == 403
    assert "location" not in response.headers


def surface_client() -> tuple[TestClient, list[tuple[str, str]]]:
    app = FastAPI()
    observed: list[tuple[str, str]] = []

    @app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"])
    async def reached(request: Request, path: str) -> dict[str, Any]:
        observed.append((request.method, path))
        return {"reached": True}

    app.add_middleware(CoachSurfaceMiddleware, settings=_staging_settings())
    return TestClient(app, base_url=COACH_ORIGIN), observed


@pytest.mark.parametrize(
    "method,path",
    [
        ("GET", "/health/live"),
        ("GET", "/health/ready"),
        ("GET", "/v1/me"),
        ("GET", "/v1/me/studio-access"),
        ("GET", "/v1/me/workspaces"),
        ("GET", "/v1/context"),
        ("POST", "/v1/context"),
        ("POST", "/v1/auth/password/login"),
        ("POST", "/v1/auth/password/recovery"),
        ("POST", "/v1/auth/password/reset"),
        ("POST", "/v1/auth/logout"),
        ("GET", "/v1/auth/google/start"),
        ("GET", "/v1/auth/google/callback"),
        ("POST", f"/v1/sessions/{RESOURCE}/revoke"),
        ("GET", "/v1/admin/studio/programs"),
        ("POST", "/v1/admin/studio/programs"),
        ("GET", "/v1/admin/studio/readiness"),
        ("GET", f"/v1/admin/studio/programs/{RESOURCE}"),
        ("GET", f"/v1/admin/studio/programs/{RESOURCE}/videos"),
        ("POST", f"/v1/admin/studio/programs/{RESOURCE}/video-uploads"),
        ("GET", f"/v1/admin/studio/programs/{RESOURCE}/video-uploads/{RESOURCE}"),
        ("PUT", f"/v1/admin/studio/programs/{RESOURCE}/video-uploads/{RESOURCE}/bytes"),
        ("POST", f"/v1/admin/studio/programs/{RESOURCE}/video-uploads/{RESOURCE}/complete"),
        ("GET", f"/v1/admin/studio/programs/{RESOURCE}/activities/{RESOURCE}/video"),
        ("POST", f"/v1/admin/studio/programs/{RESOURCE}/activities/{RESOURCE}/video"),
        ("POST", f"/v1/admin/studio/program-versions/{RESOURCE}/revision"),
        ("POST", f"/v1/admin/studio/program-versions/{RESOURCE}/modules"),
        ("PATCH", f"/v1/admin/studio/program-versions/{RESOURCE}/modules/{RESOURCE}"),
        ("POST", f"/v1/admin/studio/program-versions/{RESOURCE}/modules/{RESOURCE}/activities"),
        ("PATCH", f"/v1/admin/studio/program-versions/{RESOURCE}/activities/{RESOURCE}"),
        ("POST", f"/v1/admin/program-versions/{RESOURCE}/publish"),
    ],
)
def test_coach_surface_allows_only_reviewed_method_path_pairs(method: str, path: str) -> None:
    client, observed = surface_client()
    assert client.request(method, path).status_code == 200
    assert observed == [(method, path.lstrip("/"))]


@pytest.mark.parametrize(
    "method,path",
    [
        ("POST", "/v1/auth/password/register"),
        ("POST", "/v1/auth/password/verify"),
        ("GET", "/v1/onboarding"),
        ("GET", "/v1/courses"),
        ("GET", "/v1/practice/progress"),
        ("PUT", "/v1/profile/avatar"),
        ("POST", "/v1/admin/corrections"),
        ("POST", "/v1/admin/enrollments/manual"),
        ("GET", "/v1/admin/operations"),
        ("DELETE", "/v1/admin/studio/programs"),
        ("PUT", "/v1/admin/studio/programs"),
        ("GET", f"/v1/admin/studio/programs/{RESOURCE}/video-uploads"),
        ("POST", f"/v1/admin/studio/programs/{RESOURCE}/videos"),
        ("DELETE", f"/v1/admin/studio/programs/{RESOURCE}/video-uploads/{RESOURCE}"),
        ("PUT", f"/v1/admin/studio/programs/{RESOURCE}/video-uploads/{RESOURCE}/complete"),
        ("GET", f"/v1/admin/studio/programs/{RESOURCE}/video-uploads/{RESOURCE}/bytes"),
        ("POST", f"/v1/admin/studio/programs/{RESOURCE}/video-uploads/{RESOURCE}/bytes"),
        ("PUT", f"/v1/admin/studio/programs/{RESOURCE}/video-uploads/not-a-uuid/bytes"),
        ("PUT", f"/v1/admin/studio/programs/{RESOURCE}/activities/{RESOURCE}/video"),
        ("GET", "/v1/admin/studio/programs/not-a-uuid/videos"),
        ("POST", "/v1/media/upload-intents"),
        ("GET", "/v1/admin/studio/programs/new-operation"),
        ("POST", f"/v1/admin/program-versions/{RESOURCE}/publish/unreviewed"),
        ("GET", f"/v1/admin/studio/program-versions/{RESOURCE}/revision"),
        ("PATCH", f"/v1/admin/studio/program-versions/{RESOURCE}/revision"),
        ("POST", f"/v1/admin/studio/program-versions/{RESOURCE}/revision/unreviewed"),
        ("DELETE", f"/v1/admin/studio/program-versions/{RESOURCE}/modules/{RESOURCE}"),
        ("GET", "/v1/admin/studio/readiness/"),
        ("GET", "/docs"),
    ],
)
def test_coach_surface_denies_unreviewed_routes_before_downstream(method: str, path: str) -> None:
    client, observed = surface_client()
    response = client.request(
        method, path, headers={"x-forwarded-host": "admin-staging.authorityclosers.com"}
    )
    assert response.status_code == 403
    assert response.json()["code"] == "coach_surface_route_denied"
    assert response.headers["cache-control"] == "no-store"
    assert observed == []


def test_coach_guard_does_not_relabel_requests_by_forwarded_host() -> None:
    client, observed = surface_client()
    response = client.get(
        "/unrelated",
        headers={"host": "admin-staging.authorityclosers.com", "x-forwarded-host": COACH_HOST},
    )
    assert response.status_code == 200
    assert observed == [("GET", "unrelated")]


@pytest.mark.parametrize("operation", ["login", "recovery", "reset"])
def test_coach_password_routes_use_existing_identity_service_and_origin_gate(
    monkeypatch: pytest.MonkeyPatch, operation: str
) -> None:
    calls: list[str] = []

    class PasswordService:
        def __init__(self, *_args: Any, **_kwargs: Any) -> None:
            pass

        async def authenticate(self, **_kwargs: Any) -> SimpleNamespace:
            calls.append("authenticate")
            return SimpleNamespace(id=RESOURCE, email="synthetic@example.test", display_name=None)

        async def begin_reset(self, **_kwargs: Any) -> None:
            calls.append("begin_reset")

        async def consume_reset(self, *_args: Any) -> None:
            calls.append("consume_reset")

    class IdentityService(_CallbackIdentityApplication):
        async def issue_authenticated_session(self, *_args: Any, **_kwargs: Any) -> SimpleNamespace:
            calls.append("issue_authenticated_session")
            return SimpleNamespace(token="s" * 43)

    monkeypatch.setattr(auth_module, "PasswordIdentityService", PasswordService)
    monkeypatch.setattr(auth_module, "AsyncIdentityApplication", IdentityService)
    settings = _staging_settings().model_copy(update={"public_learner_tenant_id": None})
    client = _client(settings=settings)
    cast(FastAPI, client.app).add_middleware(CoachSurfaceMiddleware, settings=settings)
    payload = {
        "login": {"email": "synthetic@example.test", "password": "synthetic-test-only"},
        "recovery": {"email": "synthetic@example.test"},
        "reset": {"token": "x" * 43, "new_password": "synthetic-test-only"},
    }[operation]
    path = f"/v1/auth/password/{operation}"
    refused = client.post(
        path,
        json=payload,
        headers={"host": COACH_HOST, "origin": "https://admin-staging.authorityclosers.com"},
    )
    assert refused.status_code == 403
    assert calls == []
    accepted = client.post(path, json=payload, headers={"host": COACH_HOST, "origin": COACH_ORIGIN})
    assert accepted.status_code == 200
    assert (
        calls
        == {
            "login": ["authenticate", "issue_authenticated_session"],
            "recovery": ["begin_reset"],
            "reset": ["consume_reset"],
        }[operation]
    )
    if operation == "login":
        assert set(accepted.json()) == {"authenticated", "person_id", "email", "display_name"}
        assert accepted.json()["person_id"] == RESOURCE
        assert all(
            "domain=" not in value.lower() for value in accepted.headers.get_list("set-cookie")
        )
