from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, cast
from urllib.parse import urlencode, urlsplit

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import ac_platform.http.auth as auth_module
from ac_platform.application.settings import Settings
from ac_platform.http.auth import install_identity_http
from ac_platform.http.auth_transactions import AuthTransaction, AuthTransactionCodec
from ac_platform.http.problem import register_problem_handlers
from ac_platform.identity.services import (
    IssuedProviderAuthorization,
    ProviderAuthorizationType,
    VerifiedProviderAssertion,
    build_provider_authorization,
)

TEST_TRANSACTION_KEY = "test-route-transaction-signing-key-long-enough"  # noqa: S105


class _AsyncContext:
    async def __aenter__(self) -> _AsyncContext:
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None

    def begin(self) -> _AsyncContext:
        return _AsyncContext()


def _sessions() -> _AsyncContext:
    return _AsyncContext()


class _IdentityApplication:
    def __init__(self, _database: object, *, token_pepper: str) -> None:
        del token_pepper

    async def begin_provider_authorization(
        self,
        authorization_type: ProviderAuthorizationType,
        audience: str,
        *,
        person_id: object | None = None,
    ) -> IssuedProviderAuthorization:
        _, issued = build_provider_authorization(
            authorization_type=authorization_type,
            audience=audience,
            issued_at=datetime.now(UTC),
            expires_in=timedelta(minutes=10),
            person_id=cast(Any, person_id),
        )
        return issued


@pytest.fixture(autouse=True)
def _replace_identity_application(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(auth_module, "AsyncIdentityApplication", _IdentityApplication)


class _RecordingProvider:
    audience = "test-google-client-id"

    def authorization_url(
        self,
        transaction: AuthTransaction,
        *,
        redirect_uri: str,
    ) -> str:
        return "https://accounts.example.test/authorize?" + urlencode(
            {
                "state": transaction.state,
                "nonce": transaction.nonce,
                "code_challenge": transaction.pkce_challenge,
                "redirect_uri": redirect_uri,
            }
        )

    async def exchange_code(
        self,
        code: str,
        transaction: AuthTransaction,
        *,
        callback_state: str,
        redirect_uri: str,
    ) -> VerifiedProviderAssertion:
        raise AssertionError(
            f"callback not expected: {code} {transaction} {callback_state} {redirect_uri}"
        )


def _settings() -> Settings:
    return Settings(
        environment="test",
        database_url="postgresql+psycopg://unused:unused@localhost/unused",
        database_migrator_url="postgresql+psycopg://unused:unused@localhost/unused",
        session_token_pepper="test-session-token-pepper-that-is-long-enough",  # noqa: S106
        oauth_transaction_secret=TEST_TRANSACTION_KEY,
        public_app_url="https://app.authorityclosers.test",
        admin_app_url="https://admin.authorityclosers.test",
        api_url="https://api.authorityclosers.test",
    )


def _staging_settings() -> Settings:
    return Settings(
        environment="staging",
        release_id="a" * 40,
        database_url=(
            "postgresql+psycopg://ac_runtime:staging-runtime-password@postgres/ac_platform"
        ),
        database_migrator_url=(
            "postgresql+psycopg://ac_migrator:staging-migrator-password@postgres/ac_platform"
        ),
        session_token_pepper="staging-session-token-pepper-that-is-long-enough",  # noqa: S106
        oauth_transaction_secret="staging-oauth-transaction-secret-that-is-long-enough",  # noqa: S106
        public_app_url="https://staging.authorityclosers.com",
        admin_app_url="https://admin-staging.authorityclosers.com",
        api_url="https://api-staging.authorityclosers.com",
    )


def _client(*, configured: bool = True, settings: Settings | None = None) -> TestClient:
    application = FastAPI()
    register_problem_handlers(application)
    install_identity_http(
        application,
        settings=settings or _settings(),
        sessions=cast(Any, _sessions),
        provider=_RecordingProvider() if configured else None,
    )
    return TestClient(application)


def test_auth_start_binds_state_nonce_pkce_and_safe_return_in_signed_cookie() -> None:
    response = _client().get(
        "/v1/auth/google/start",
        params={
            "action": "authenticate",
            "surface": "admin",
            "return_path": "/people?filter=active",
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    cookie = response.cookies["ac_oauth_transaction"]
    transaction = AuthTransactionCodec(TEST_TRANSACTION_KEY).decode(cookie)
    assert transaction.surface == "admin"
    assert transaction.return_path == "/people?filter=active"
    assert transaction.pkce_verifier not in response.headers["location"]
    location = urlsplit(response.headers["location"])
    assert location.hostname == "accounts.example.test"
    assert "state=" in location.query
    assert "nonce=" in location.query
    assert "code_challenge=" in location.query
    set_cookie = response.headers["set-cookie"].lower()
    assert "httponly" in set_cookie
    assert "samesite=lax" in set_cookie
    assert "path=/v1/auth/google/callback" in set_cookie
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.parametrize(
    ("surface", "host"),
    [
        ("learner", "api-staging.authorityclosers.com"),
        ("learner", "admin-staging.authorityclosers.com"),
        ("admin", "staging.authorityclosers.com"),
        ("admin", "api-staging.authorityclosers.com"),
    ],
)
def test_staging_auth_start_rejects_a_host_outside_the_selected_surface(
    surface: str,
    host: str,
) -> None:
    response = _client(settings=_staging_settings()).get(
        "/v1/auth/google/start",
        params={"action": "authenticate", "surface": surface},
        headers={"host": host},
        follow_redirects=False,
    )

    assert response.status_code == 400
    assert response.json()["code"] == "invalid_auth_transaction"
    assert "location" not in response.headers


@pytest.mark.parametrize(
    ("surface", "host"),
    [
        ("learner", "staging.authorityclosers.com"),
        ("admin", "admin-staging.authorityclosers.com"),
    ],
)
def test_staging_auth_start_accepts_only_the_selected_surface_host(
    surface: str,
    host: str,
) -> None:
    response = _client(settings=_staging_settings()).get(
        "/v1/auth/google/start",
        params={"action": "authenticate", "surface": surface},
        headers={"host": host},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert urlsplit(response.headers["location"]).hostname == "accounts.example.test"


def test_staging_callback_rejects_cross_surface_host_before_provider_exchange() -> None:
    client = _client(settings=_staging_settings())
    started = client.get(
        "/v1/auth/google/start",
        params={"action": "authenticate", "surface": "admin"},
        headers={"host": "admin-staging.authorityclosers.com"},
        follow_redirects=False,
    )
    encoded = started.cookies["ac_oauth_transaction"]
    transaction = AuthTransactionCodec(
        "staging-oauth-transaction-secret-that-is-long-enough"
    ).decode(encoded)

    response = client.get(
        "/v1/auth/google/callback",
        params={"state": transaction.state, "code": "unused-code"},
        headers={
            "host": "staging.authorityclosers.com",
            "cookie": f"ac_oauth_transaction={encoded}",
        },
        follow_redirects=False,
    )

    assert response.status_code == 400
    assert response.json()["code"] == "invalid_auth_transaction"


def test_external_return_url_is_rejected_without_contacting_provider() -> None:
    response = _client().get(
        "/v1/auth/google/start",
        params={"action": "register", "return_path": "https://evil.example/steal"},
        follow_redirects=False,
    )

    assert response.status_code == 400
    assert response.json()["code"] == "invalid_auth_transaction"
    assert "location" not in response.headers


def test_link_start_requires_an_existing_authority_closers_session() -> None:
    response = _client().get(
        "/v1/auth/google/start",
        params={"action": "link"},
        follow_redirects=False,
    )

    assert response.status_code == 401
    assert response.json()["code"] == "authentication_required"


def test_unconfigured_provider_fails_closed() -> None:
    response = _client(configured=False).get(
        "/v1/auth/google/start",
        params={"action": "authenticate"},
        follow_redirects=False,
    )

    assert response.status_code == 503
    assert response.json()["code"] == "identity_provider_unavailable"
    assert "location" not in response.headers


def test_callback_rejects_state_mismatch_before_code_exchange_or_database_access() -> None:
    client = _client()
    started = client.get(
        "/v1/auth/google/start",
        params={"action": "authenticate"},
        follow_redirects=False,
    )
    transaction = AuthTransactionCodec(TEST_TRANSACTION_KEY).decode(
        started.cookies["ac_oauth_transaction"]
    )

    response = client.get(
        "/v1/auth/google/callback",
        params={"state": "x" * len(transaction.state), "code": "unused-code"},
        follow_redirects=False,
    )

    assert response.status_code == 400
    assert response.json()["code"] == "invalid_auth_transaction"
