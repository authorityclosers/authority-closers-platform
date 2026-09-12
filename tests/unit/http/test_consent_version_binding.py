from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any, cast
from uuid import UUID

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from httpx import Response

import ac_platform.http.auth as auth_module
from ac_platform.application.settings import Settings
from ac_platform.http.auth import install_identity_http
from ac_platform.http.auth_transactions import AuthTransaction
from ac_platform.http.problem import register_problem_handlers
from ac_platform.identity.services import (
    IssuedProviderAuthorization,
    ProviderAuthorizationType,
    build_provider_authorization,
)

CURRENT_VERSION = "unit-reviewed-terms-privacy-v2"
LEARNER_ORIGIN = "https://app.authorityclosers.test"


class _AsyncContext:
    async def __aenter__(self) -> _AsyncContext:
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None

    def begin(self) -> _AsyncContext:
        return _AsyncContext()


def _client(
    monkeypatch: pytest.MonkeyPatch,
    environment: str,
    *,
    configured_version: str | None = CURRENT_VERSION,
) -> tuple[TestClient, list[str], list[str | None]]:
    calls: list[str] = []
    recorded_versions: list[str | None] = []

    def sessions() -> _AsyncContext:
        calls.append("database")
        return _AsyncContext()

    class PasswordService:
        def __init__(self, _database: object, *, token_secret: str) -> None:
            del token_secret

        async def register(self, **values: Any) -> SimpleNamespace:
            calls.append("password_registration")
            recorded_versions.append(values["consent_version"])
            return SimpleNamespace(created=False, challenge=None)

    class IdentityApplication:
        def __init__(self, _database: object, *, token_pepper: str) -> None:
            del token_pepper

        async def begin_provider_authorization(
            self,
            authorization_type: ProviderAuthorizationType,
            audience: str,
            *,
            person_id: UUID | None = None,
        ) -> IssuedProviderAuthorization:
            calls.append("oauth_transaction")
            _, issued = build_provider_authorization(
                authorization_type=authorization_type,
                audience=audience,
                issued_at=datetime.now(UTC),
                expires_in=timedelta(minutes=10),
                person_id=person_id,
            )
            return issued

    class Provider:
        @property
        def audience(self) -> str:
            calls.append("provider_audience")
            return "unit-google-client"

        def authorization_url(
            self,
            transaction: AuthTransaction,
            *,
            redirect_uri: str,
        ) -> str:
            del redirect_uri
            calls.append("provider_authorization")
            recorded_versions.append(transaction.consent_version)
            return "https://accounts.example.test/authorize"

    monkeypatch.setattr(auth_module, "PasswordIdentityService", PasswordService)
    monkeypatch.setattr(auth_module, "AsyncIdentityApplication", IdentityApplication)
    # Exercise the route's environment guard independently of deployment configuration validation.
    settings = Settings(
        _env_file=None,
        environment="test",
        session_token_pepper="unit-consent-session-pepper-long-enough",  # noqa: S106
        oauth_transaction_secret="unit-consent-oauth-secret-long-enough",  # noqa: S106
        email_challenge_secret="unit-consent-email-secret-long-enough",  # noqa: S106
        public_app_url=LEARNER_ORIGIN,
        learner_consent_version=configured_version,
        public_learner_tenant_id="22222222-2222-4222-8222-222222222222",
        operations_tenant_id="33333333-3333-4333-8333-333333333333",
    ).model_copy(update={"environment": environment})
    application = FastAPI()
    register_problem_handlers(application)
    install_identity_http(
        application,
        settings=settings,
        sessions=cast(Any, sessions),
        provider=cast(Any, Provider()),
    )
    return (
        TestClient(application, base_url=LEARNER_ORIGIN, follow_redirects=False),
        calls,
        recorded_versions,
    )


def _register(client: TestClient, method: str, version: str | None) -> Response:
    if method == "password":
        body: dict[str, object] = {
            "first_name": "Synthetic",
            "email": "consent-fixture@example.test",
            "whatsapp_number": "+12025550123",
            "password": "synthetic fixture password",
            "consent": True,
        }
        if version is not None:
            body["consent_version"] = version
        return client.post(
            "/v1/auth/password/register",
            headers={"Origin": LEARNER_ORIGIN},
            json=body,
        )
    params = {"action": "register", "surface": "learner", "consent": "true"}
    if version is not None:
        params["consent_version"] = version
    return client.get("/v1/auth/google/start", params=params)


@pytest.mark.parametrize("method", ["password", "google"])
@pytest.mark.parametrize("environment", ["local", "test", "development", "staging", "production"])
@pytest.mark.parametrize(
    "version", [None, "superseded-v1", CURRENT_VERSION, f" {CURRENT_VERSION} "]
)
def test_registration_binds_current_consent_before_side_effects(
    monkeypatch: pytest.MonkeyPatch,
    method: str,
    environment: str,
    version: str | None,
) -> None:
    client, calls, recorded_versions = _client(monkeypatch, environment)
    response = _register(client, method, version)
    accepted = version == CURRENT_VERSION or (version is None and environment != "production")

    if not accepted:
        assert response.status_code == 400
        assert response.json()["code"] == "learner_consent_required"
        assert "Reload" in response.json()["detail"]
        assert "Terms and Privacy Policy" in response.json()["detail"]
        assert calls == []
        assert recorded_versions == []
        assert "set-cookie" not in response.headers
        return

    assert response.status_code == (202 if method == "password" else 303)
    assert recorded_versions == [CURRENT_VERSION]
    assert calls == (
        ["database", "password_registration"]
        if method == "password"
        else ["provider_audience", "database", "oauth_transaction", "provider_authorization"]
    )


@pytest.mark.parametrize("method", ["password", "google"])
@pytest.mark.parametrize("version", ["", "v" * 65])
def test_client_consent_version_is_bounded_before_side_effects(
    monkeypatch: pytest.MonkeyPatch,
    method: str,
    version: str,
) -> None:
    client, calls, recorded_versions = _client(monkeypatch, "production")
    response = _register(client, method, version)

    assert response.status_code == 422
    assert calls == []
    assert recorded_versions == []
    assert "set-cookie" not in response.headers


@pytest.mark.parametrize("method", ["password", "google"])
def test_missing_server_consent_configuration_stays_unavailable(
    monkeypatch: pytest.MonkeyPatch,
    method: str,
) -> None:
    client, calls, recorded_versions = _client(monkeypatch, "production", configured_version=None)
    response = _register(client, method, CURRENT_VERSION)

    assert response.status_code == 503
    assert response.json()["code"] == "password_registration_unavailable"
    assert calls == []
    assert recorded_versions == []


def test_google_authentication_does_not_require_registration_consent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, calls, recorded_versions = _client(monkeypatch, "production", configured_version=None)
    response = client.get(
        "/v1/auth/google/start", params={"action": "authenticate", "surface": "learner"}
    )

    assert response.status_code == 303
    assert recorded_versions == [None]
    assert calls == ["provider_audience", "database", "oauth_transaction", "provider_authorization"]
