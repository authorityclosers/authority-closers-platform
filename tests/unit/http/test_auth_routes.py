from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any, cast
from urllib.parse import parse_qs, urlencode, urlsplit
from uuid import UUID

import pytest
from fastapi import FastAPI, Request, Response
from fastapi.testclient import TestClient
from pydantic import AnyHttpUrl, SecretStr
from sqlalchemy.exc import SQLAlchemyError

import ac_platform.http.auth as auth_module
from ac_platform.application.settings import Settings
from ac_platform.http.auth import install_identity_http, require_safe_origin
from ac_platform.http.auth_transactions import (
    AUTH_TRANSACTION_MAX_AGE_SECONDS,
    AuthTransaction,
    AuthTransactionCodec,
)
from ac_platform.http.identity_provider import (
    IdentityProviderRejected,
    IdentityProviderUnavailable,
)
from ac_platform.http.problem import register_problem_handlers
from ac_platform.identity.services import (
    ConflictingProviderIdentityError,
    IdentityResolutionError,
    IssuedProviderAuthorization,
    ProviderAuthorizationType,
    ProviderIdentityNotLinkedError,
    VerifiedProviderAssertion,
    build_provider_authorization,
)

TEST_TRANSACTION_KEY = "test-route-transaction-signing-key-long-enough"  # noqa: S105
VALID_SESSION_TOKEN = "s" * 43  # noqa: S105
SECOND_VALID_SESSION_TOKEN = "t" * 43  # noqa: S105
DEPLOYMENT_SESSION_COOKIE = "__Host-ac_session"
DEPLOYMENT_OAUTH_COOKIE = "__Host-ac_oauth_transaction"


class _AsyncContext:
    async def __aenter__(self) -> _AsyncContext:
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None

    def begin(self) -> _AsyncContext:
        return _AsyncContext()

    async def scalar(self, _statement: object) -> object | None:
        return None


def _sessions() -> _AsyncContext:
    return _AsyncContext()


class _IdentityApplication:
    registered_provider_calls: list[dict[str, object]] = []

    @classmethod
    def reset_registered_provider_calls(cls) -> None:
        cls.registered_provider_calls = []

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

    async def select_tenant(self, token: str, tenant_id: UUID) -> object:
        del token, tenant_id
        return object()

    async def register_verified_provider(
        self,
        transaction_id: UUID,
        assertion: VerifiedProviderAssertion,
        *,
        pkce_verifier: str,
        consent_version: str,
        display_name: str | None = None,
        user_agent: str | None = None,
    ) -> SimpleNamespace:
        type(self).registered_provider_calls.append(
            {
                "transaction_id": transaction_id,
                "assertion": assertion,
                "pkce_verifier": pkce_verifier,
                "consent_version": consent_version,
                "display_name": display_name,
                "user_agent": user_agent,
            }
        )
        return SimpleNamespace(
            person=SimpleNamespace(
                id=UUID("11111111-1111-4111-8111-111111111111"),
            ),
            session=SimpleNamespace(token=VALID_SESSION_TOKEN),
        )


class _LearnerProvisioningApplication:
    def __init__(self, _database: object) -> None:
        pass

    async def ensure(
        self,
        *,
        person_id: UUID,
        tenant_id: UUID,
        required_consent_version: str,
    ) -> object:
        del person_id, tenant_id, required_consent_version
        return object()


@pytest.fixture(autouse=True)
def _replace_identity_application(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(auth_module, "AsyncIdentityApplication", _IdentityApplication)
    monkeypatch.setattr(
        auth_module,
        "AsyncLearnerProvisioningApplication",
        _LearnerProvisioningApplication,
    )


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


class _SuccessfulProvider(_RecordingProvider):
    def __init__(self) -> None:
        self.redirect_uris: list[str] = []

    async def exchange_code(
        self,
        code: str,
        transaction: AuthTransaction,
        *,
        callback_state: str,
        redirect_uri: str,
    ) -> VerifiedProviderAssertion:
        assert code == "google-authorization-code"
        self.redirect_uris.append(redirect_uri)
        return VerifiedProviderAssertion(
            issuer="https://accounts.google.com",
            subject="google-subject",
            audience=self.audience,
            state=callback_state,
            nonce=transaction.nonce,
            authorization_type=transaction.authorization_type,
            email="person@authorityclosers.com",
            email_verified=True,
        )


class _RejectedProvider(_RecordingProvider):
    async def exchange_code(
        self,
        code: str,
        transaction: AuthTransaction,
        *,
        callback_state: str,
        redirect_uri: str,
    ) -> VerifiedProviderAssertion:
        del code, transaction, callback_state, redirect_uri
        raise IdentityProviderRejected("provider rejected the controlled callback")


class _UnavailableProvider(_RecordingProvider):
    async def exchange_code(
        self,
        code: str,
        transaction: AuthTransaction,
        *,
        callback_state: str,
        redirect_uri: str,
    ) -> VerifiedProviderAssertion:
        del code, transaction, callback_state, redirect_uri
        raise IdentityProviderUnavailable("provider is unavailable")


class _CallbackIdentityApplication(_IdentityApplication):
    async def authenticate_provider(
        self,
        transaction_id: object,
        assertion: VerifiedProviderAssertion,
        *,
        pkce_verifier: str,
        user_agent: str | None = None,
    ) -> SimpleNamespace:
        del transaction_id, assertion, pkce_verifier, user_agent
        return SimpleNamespace(
            token=VALID_SESSION_TOKEN,
            metadata=SimpleNamespace(person_id=UUID("11111111-1111-4111-8111-111111111111")),
        )


class _UnknownProviderIdentityApplication(_IdentityApplication):
    async def authenticate_provider(
        self,
        transaction_id: object,
        assertion: VerifiedProviderAssertion,
        *,
        pkce_verifier: str,
        user_agent: str | None = None,
    ) -> SimpleNamespace:
        del transaction_id, assertion, pkce_verifier, user_agent
        raise ProviderIdentityNotLinkedError("provider identity is not linked to a person")


class _CorruptProviderIdentityApplication(_IdentityApplication):
    async def authenticate_provider(
        self,
        transaction_id: object,
        assertion: VerifiedProviderAssertion,
        *,
        pkce_verifier: str,
        user_agent: str | None = None,
    ) -> SimpleNamespace:
        del transaction_id, assertion, pkce_verifier, user_agent
        raise IdentityResolutionError("provider identity points to a missing person")


class _ProviderCollisionIdentityApplication(_IdentityApplication):
    async def register_verified_provider(
        self,
        transaction_id: object,
        assertion: VerifiedProviderAssertion,
        *,
        pkce_verifier: str,
        consent_version: str,
        display_name: str | None,
        user_agent: str | None = None,
    ) -> SimpleNamespace:
        del (
            transaction_id,
            assertion,
            pkce_verifier,
            consent_version,
            display_name,
            user_agent,
        )
        raise ConflictingProviderIdentityError("provider key is already linked to another person")


class _ForbiddenActorResolutionApplication(_IdentityApplication):
    actor_resolution_calls = 0

    async def resolve_actor(self, _token: str) -> object:
        type(self).actor_resolution_calls += 1
        raise AssertionError("actor resolution must not run for a rejected raw cookie")


class _LogoutIdentityApplication(_IdentityApplication):
    revoke_calls: list[tuple[str, UUID, str]] = []
    reject_resolution = False
    reject_revocation_with_database_error = False

    @classmethod
    def reset(cls) -> None:
        cls.revoke_calls = []
        cls.reject_resolution = False
        cls.reject_revocation_with_database_error = False

    async def resolve_actor(self, token: str) -> SimpleNamespace:
        if type(self).reject_resolution:
            raise IdentityResolutionError("the session is expired or revoked")
        assert token == VALID_SESSION_TOKEN
        return SimpleNamespace(
            actor=SimpleNamespace(
                session_id=UUID("44444444-4444-4444-8444-444444444444"),
            )
        )

    async def revoke_self(
        self,
        token: str,
        session_id: UUID,
        *,
        reason: str,
    ) -> object:
        if type(self).reject_revocation_with_database_error:
            raise SQLAlchemyError("controlled database outage")
        type(self).revoke_calls.append((token, session_id, reason))
        return object()


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
        learner_consent_version="staging-test-document-v1",
        public_learner_tenant_id="22222222-2222-4222-8222-222222222222",
        operations_tenant_id="33333333-3333-4333-8333-333333333333",
    )


def _settings_without_registration_config() -> Settings:
    return Settings(
        environment="test",
        database_url="postgresql+psycopg://unused:unused@localhost/unused",
        database_migrator_url="postgresql+psycopg://unused:unused@localhost/unused",
        session_token_pepper="test-session-token-pepper-that-is-long-enough",  # noqa: S106
        oauth_transaction_secret=TEST_TRANSACTION_KEY,
        public_app_url="https://app.authorityclosers.test",
        admin_app_url="https://admin.authorityclosers.test",
        api_url="https://api.authorityclosers.test",
        learner_consent_version=None,
        public_learner_tenant_id=None,
        operations_tenant_id="33333333-3333-4333-8333-333333333333",
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
        email_challenge_secret="staging-email-challenge-secret-that-is-long-enough",  # noqa: S106
        google_oauth_client_id="123.apps.googleusercontent.com",
        google_oauth_client_secret="test-google-client-secret",  # noqa: S106
        public_app_url="https://staging.authorityclosers.com",
        admin_app_url="https://admin-staging.authorityclosers.com",
        api_url="https://api-staging.authorityclosers.com",
        internal_api_host="api.staging.ac.internal.invalid",
        session_cookie_name=DEPLOYMENT_SESSION_COOKIE,
        oauth_transaction_cookie_name=DEPLOYMENT_OAUTH_COOKIE,
        trusted_proxy_addresses="172.18.0.2",
        learner_consent_version="staging-test-document-v1",
        public_learner_tenant_id="22222222-2222-4222-8222-222222222222",
        operations_tenant_id="33333333-3333-4333-8333-333333333333",
    )


def _client(
    *,
    configured: bool = True,
    settings: Settings | None = None,
    provider: object | None = None,
) -> TestClient:
    _IdentityApplication.reset_registered_provider_calls()
    application = FastAPI()
    register_problem_handlers(application)
    install_identity_http(
        application,
        settings=settings or _settings(),
        sessions=cast(Any, _sessions),
        provider=provider
        if provider is not None
        else (_RecordingProvider() if configured else None),
    )
    return TestClient(application)


def _request_with_raw_cookie_headers(*cookie_headers: str) -> Request:
    return Request(
        {
            "type": "http",
            "method": "GET",
            "scheme": "https",
            "path": "/v1/context",
            "headers": [
                (b"host", b"api.staging.ac.internal.invalid"),
                *((b"cookie", value.encode("latin-1")) for value in cookie_headers),
            ],
            "query_string": b"",
            "server": ("api.staging.ac.internal.invalid", 8000),
            "client": ("127.0.0.1", 1),
        }
    )


def test_password_registration_is_fail_closed_without_reviewed_consent_version() -> None:
    settings = _settings().model_copy(update={"learner_consent_version": None})
    response = _client(settings=settings).post(
        "/v1/auth/password/register",
        headers={"Origin": "https://app.authorityclosers.test"},
        json={
            "first_name": "Learner",
            "email": "learner@example.com",
            "whatsapp_number": "+12025550123",
            "password": "a sufficiently long password",
            "consent": True,
        },
    )

    assert response.status_code == 503
    assert response.json()["code"] == "password_registration_unavailable"


def test_password_auth_contract_uses_json_body_for_one_time_tokens() -> None:
    schema = _client().get("/openapi.json").json()
    paths = schema["paths"]

    assert {
        "/v1/auth/password/register",
        "/v1/auth/password/login",
        "/v1/auth/password/recovery",
        "/v1/auth/password/resend-verification",
        "/v1/auth/password/verify",
        "/v1/auth/password/reset",
    } <= set(paths)
    assert {"/v1/onboarding"} <= set(paths)
    verification = paths["/v1/auth/password/verify"]["post"]
    assert "requestBody" in verification
    assert not any(
        parameter.get("name") == "token" for parameter in verification.get("parameters", [])
    )


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
    assert "path=/" in set_cookie
    assert response.headers["cache-control"] == "no-store"


def test_admin_google_self_registration_is_explicitly_unavailable() -> None:
    response = _client().get(
        "/v1/auth/google/start",
        params={"action": "register", "surface": "admin"},
        follow_redirects=False,
    )

    assert response.status_code == 403
    assert response.json()["code"] == "admin_registration_unavailable"
    assert "location" not in response.headers


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
    settings = _staging_settings()
    response = _client(settings=settings).get(
        "/v1/auth/google/start",
        params={"action": "authenticate", "surface": surface},
        headers={"host": host},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert urlsplit(response.headers["location"]).hostname == "accounts.example.test"
    transaction = AuthTransactionCodec(
        "staging-oauth-transaction-secret-that-is-long-enough"
    ).decode(response.cookies[DEPLOYMENT_OAUTH_COOKIE])
    state_cookie_name = auth_module._oauth_transaction_cookie_name(  # noqa: SLF001
        settings,
        transaction.state,
    )
    set_cookie_headers = [value.lower() for value in response.headers.get_list("set-cookie")]
    transaction_cookies = [
        value
        for value in set_cookie_headers
        if value.startswith(f"{DEPLOYMENT_OAUTH_COOKIE.lower()}=")
        or value.startswith(f"{state_cookie_name.lower()}=")
    ]
    assert len(transaction_cookies) == 2
    for set_cookie in transaction_cookies:
        assert f"max-age={AUTH_TRANSACTION_MAX_AGE_SECONDS}" in set_cookie
        assert "secure" in set_cookie
        assert "httponly" in set_cookie
        assert "samesite=lax" in set_cookie
        assert "path=/" in set_cookie
        assert "domain=" not in set_cookie


def test_staging_callback_rejects_cross_surface_host_before_provider_exchange() -> None:
    client = _client(settings=_staging_settings())
    started = client.get(
        "/v1/auth/google/start",
        params={"action": "authenticate", "surface": "admin"},
        headers={"host": "admin-staging.authorityclosers.com"},
        follow_redirects=False,
    )
    encoded = started.cookies[DEPLOYMENT_OAUTH_COOKIE]
    transaction = AuthTransactionCodec(
        "staging-oauth-transaction-secret-that-is-long-enough"
    ).decode(encoded)

    response = client.get(
        "/v1/auth/google/callback",
        params={"state": transaction.state, "code": "unused-code"},
        headers={
            "host": "staging.authorityclosers.com",
            "cookie": f"{DEPLOYMENT_OAUTH_COOKIE}={encoded}",
        },
        follow_redirects=False,
    )

    assert response.status_code == 400
    assert response.json()["code"] == "invalid_auth_transaction"
    deleted_cookies = response.headers.get_list("set-cookie")
    assert any(value.startswith(f'{DEPLOYMENT_OAUTH_COOKIE}=""') for value in deleted_cookies)
    assert response.headers["cache-control"] == "no-store"


def test_staging_callback_uses_exact_surface_uri_and_issues_host_only_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(auth_module, "AsyncIdentityApplication", _CallbackIdentityApplication)
    provider = _SuccessfulProvider()
    client = _client(settings=_staging_settings(), provider=provider)
    started = client.get(
        "/v1/auth/google/start",
        params={
            "action": "authenticate",
            "surface": "learner",
            "return_path": "/home?from=google",
        },
        headers={"host": "staging.authorityclosers.com"},
        follow_redirects=False,
    )
    encoded = started.cookies[DEPLOYMENT_OAUTH_COOKIE]
    transaction = AuthTransactionCodec(
        "staging-oauth-transaction-secret-that-is-long-enough"
    ).decode(encoded)

    response = client.get(
        "/v1/auth/google/callback",
        params={"state": transaction.state, "code": "google-authorization-code"},
        headers={
            "host": "staging.authorityclosers.com",
            "cookie": f"{DEPLOYMENT_OAUTH_COOKIE}={encoded}",
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == ("https://staging.authorityclosers.com/home?from=google")
    assert provider.redirect_uris == [
        "https://staging.authorityclosers.com/v1/auth/google/callback"
    ]
    set_cookie_headers = [value.lower() for value in response.headers.get_list("set-cookie")]
    session_cookie = next(
        value
        for value in set_cookie_headers
        if value.startswith(f"{DEPLOYMENT_SESSION_COOKIE.lower()}=")
    )
    transaction_delete = next(
        value
        for value in set_cookie_headers
        if value.startswith(f"{DEPLOYMENT_OAUTH_COOKIE.lower()}=")
    )
    assert f"{DEPLOYMENT_SESSION_COOKIE.lower()}={VALID_SESSION_TOKEN}" in session_cookie
    for value in (session_cookie, transaction_delete):
        assert "secure" in value
        assert "httponly" in value
        assert "samesite=lax" in value
        assert "path=/" in value
        assert "domain=" not in value


@pytest.mark.parametrize(
    ("provider", "result"),
    [
        (_RejectedProvider(), "provider_rejected"),
        (_UnavailableProvider(), "provider_unavailable"),
    ],
)
def test_learner_callback_turns_provider_failure_into_safe_recovery_redirect(
    provider: object,
    result: str,
) -> None:
    client = _client(provider=provider)
    started = client.get(
        "/v1/auth/google/start",
        params={"action": "authenticate", "surface": "learner"},
        follow_redirects=False,
    )
    transaction = AuthTransactionCodec(TEST_TRANSACTION_KEY).decode(
        started.cookies["ac_oauth_transaction"]
    )
    state_cookie_name = auth_module._oauth_transaction_cookie_name(  # noqa: SLF001
        _settings(),
        transaction.state,
    )

    response = client.get(
        "/v1/auth/google/callback",
        params={"state": transaction.state, "code": "google-authorization-code"},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == (
        f"https://app.authorityclosers.test/auth/callback?result={result}"
    )
    deleted_cookies = response.headers.get_list("set-cookie")
    assert any(value.startswith('ac_oauth_transaction=""') for value in deleted_cookies)
    assert any(value.startswith(f'{state_cookie_name}=""') for value in deleted_cookies)
    assert response.headers["cache-control"] == "no-store"


def test_learner_callback_handles_provider_cancellation_and_clears_transaction_cookies() -> None:
    client = _client(provider=_SuccessfulProvider())
    started = client.get(
        "/v1/auth/google/start",
        params={"action": "authenticate", "surface": "learner"},
        follow_redirects=False,
    )
    transaction = AuthTransactionCodec(TEST_TRANSACTION_KEY).decode(
        started.cookies["ac_oauth_transaction"]
    )
    state_cookie_name = auth_module._oauth_transaction_cookie_name(  # noqa: SLF001
        _settings(),
        transaction.state,
    )

    response = client.get(
        "/v1/auth/google/callback",
        params={"state": transaction.state, "error": "access_denied"},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == (
        "https://app.authorityclosers.test/auth/callback?result=provider_rejected"
    )
    deleted_cookies = response.headers.get_list("set-cookie")
    assert any(value.startswith('ac_oauth_transaction=""') for value in deleted_cookies)
    assert any(value.startswith(f'{state_cookie_name}=""') for value in deleted_cookies)
    assert response.headers["cache-control"] == "no-store"


def test_google_callback_without_code_or_provider_error_clears_transaction_cookies() -> None:
    client = _client(provider=_SuccessfulProvider())
    started = client.get(
        "/v1/auth/google/start",
        params={"action": "authenticate", "surface": "learner"},
        follow_redirects=False,
    )
    transaction = AuthTransactionCodec(TEST_TRANSACTION_KEY).decode(
        started.cookies["ac_oauth_transaction"]
    )

    response = client.get(
        "/v1/auth/google/callback",
        params={"state": transaction.state},
        follow_redirects=False,
    )

    assert response.status_code == 400
    assert response.json()["code"] == "invalid_auth_transaction"
    assert 'ac_oauth_transaction=""' in response.headers["set-cookie"]


def test_unknown_learner_google_identity_is_sent_to_explicit_registration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        auth_module,
        "AsyncIdentityApplication",
        _UnknownProviderIdentityApplication,
    )
    client = _client(provider=_SuccessfulProvider())
    started = client.get(
        "/v1/auth/google/start",
        params={"action": "authenticate", "surface": "learner"},
        follow_redirects=False,
    )
    transaction = AuthTransactionCodec(TEST_TRANSACTION_KEY).decode(
        started.cookies["ac_oauth_transaction"]
    )

    response = client.get(
        "/v1/auth/google/callback",
        params={"state": transaction.state, "code": "google-authorization-code"},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == (
        "https://app.authorityclosers.test/auth/callback?result=registration_required"
    )
    assert 'ac_oauth_transaction=""' in response.headers["set-cookie"]
    assert "ac_session" not in response.cookies
    assert _IdentityApplication.registered_provider_calls == []


@pytest.mark.parametrize(
    ("return_path", "preserves_course"),
    [
        ("/home?course=authority-closers-free-course", True),
        ("/onboarding?course=authority-closers-free-course", True),
        ("/settings?course=authority-closers-free-course", False),
        ("/home?course=other-course", False),
        ("/home?course=authority-closers-free-course&course=other", False),
        ("/home?course=authority-closers-free-course&extra=true", False),
        ("/home?course=authority%2Dclosers-free-course", False),
    ],
)
def test_google_recovery_preserves_only_signed_allowlisted_course_context(
    return_path: str,
    preserves_course: bool,
) -> None:
    client = _client(provider=_SuccessfulProvider())
    started = client.get(
        "/v1/auth/google/start",
        params={"action": "authenticate", "surface": "learner", "return_path": return_path},
        follow_redirects=False,
    )
    assert started.status_code == 303
    transaction = AuthTransactionCodec(TEST_TRANSACTION_KEY).decode(
        started.cookies["ac_oauth_transaction"]
    )
    response = client.get(
        "/v1/auth/google/callback",
        params={
            "state": transaction.state,
            "error": "access_denied",
            "course": "other-course",
            "return_path": "/settings",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    location = urlsplit(response.headers["location"])
    assert location.scheme == "https"
    assert location.netloc == "app.authorityclosers.test"
    assert location.path == "/auth/callback"
    expected = {"result": ["provider_rejected"]}
    if preserves_course:
        expected["course"] = ["authority-closers-free-course"]
    assert parse_qs(location.query) == expected
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["pragma"] == "no-cache"
    assert 'ac_oauth_transaction=""' in response.headers["set-cookie"]
    assert "ac_session" not in response.cookies


@pytest.mark.parametrize(
    ("return_path", "expected_context"),
    [
        (
            "/onboarding?activity=86f7efee-f504-4d6f-b4bc-9b3cb84ba2be",
            {"activity": ["86f7efee-f504-4d6f-b4bc-9b3cb84ba2be"]},
        ),
        (
            "/onboarding?course=authority-closers-free-course"
            "&activity=86f7efee-f504-4d6f-b4bc-9b3cb84ba2be",
            {
                "course": ["authority-closers-free-course"],
                "activity": ["86f7efee-f504-4d6f-b4bc-9b3cb84ba2be"],
            },
        ),
        ("/onboarding?activity=https%3A%2F%2Foutside.example", {}),
        ("/settings?activity=86f7efee-f504-4d6f-b4bc-9b3cb84ba2be", {}),
        ("/onboarding?activity=86f7efee-f504-4d6f-b4bc-9b3cb84ba2be&activity=other", {}),
        ("/onboarding?activity=86f7efee-f504-4d6f-b4bc-9b3cb84ba2be&extra=true", {}),
        ("/onboarding?activity=86f7efee%2Df504-4d6f-b4bc-9b3cb84ba2be", {}),
        ("/onboarding?course=other&activity=86f7efee-f504-4d6f-b4bc-9b3cb84ba2be", {}),
    ],
)
def test_google_activity_recovery_uses_only_bounded_signed_navigation(
    return_path: str,
    expected_context: dict[str, list[str]],
) -> None:
    client = _client(provider=_SuccessfulProvider())
    started = client.get(
        "/v1/auth/google/start",
        params={"action": "authenticate", "surface": "learner", "return_path": return_path},
        follow_redirects=False,
    )
    assert started.status_code == 303
    transaction = AuthTransactionCodec(TEST_TRANSACTION_KEY).decode(
        started.cookies["ac_oauth_transaction"]
    )
    response = client.get(
        "/v1/auth/google/callback",
        params={
            "state": transaction.state,
            "error": "access_denied",
            "activity": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
            "return_path": "/settings",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    location = urlsplit(response.headers["location"])
    assert (location.scheme, location.netloc, location.path) == (
        "https",
        "app.authorityclosers.test",
        "/auth/callback",
    )
    assert parse_qs(location.query) == {"result": ["provider_rejected"], **expected_context}
    assert response.headers["cache-control"] == "no-store"
    assert 'ac_oauth_transaction=""' in response.headers["set-cookie"]
    assert "ac_session" not in response.cookies
    assert _IdentityApplication.registered_provider_calls == []


def test_course_return_keeps_unknown_google_identity_behind_explicit_registration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        auth_module, "AsyncIdentityApplication", _UnknownProviderIdentityApplication
    )
    client = _client(provider=_SuccessfulProvider())
    started = client.get(
        "/v1/auth/google/start",
        params={
            "action": "authenticate",
            "surface": "learner",
            "return_path": "/home?course=authority-closers-free-course",
        },
        follow_redirects=False,
    )
    transaction = AuthTransactionCodec(TEST_TRANSACTION_KEY).decode(
        started.cookies["ac_oauth_transaction"]
    )
    response = client.get(
        "/v1/auth/google/callback",
        params={"state": transaction.state, "code": "google-authorization-code"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert parse_qs(urlsplit(response.headers["location"]).query) == {
        "result": ["registration_required"],
        "course": ["authority-closers-free-course"],
    }
    assert "ac_session" not in response.cookies
    assert _IdentityApplication.registered_provider_calls == []


@pytest.mark.parametrize(
    "return_path",
    [
        None,
        "/home?course=authority-closers-free-course",
        "/onboarding?activity=86f7efee-f504-4d6f-b4bc-9b3cb84ba2be",
        "/onboarding?course=authority-closers-free-course"
        "&activity=86f7efee-f504-4d6f-b4bc-9b3cb84ba2be",
    ],
)
def test_google_authenticate_callback_uses_signed_action_not_callback_query(
    monkeypatch: pytest.MonkeyPatch,
    return_path: str | None,
) -> None:
    monkeypatch.setattr(auth_module, "AsyncIdentityApplication", _CallbackIdentityApplication)
    client = _client(provider=_SuccessfulProvider())
    started = client.get(
        "/v1/auth/google/start",
        params={
            "action": "authenticate",
            "surface": "learner",
            **({"return_path": return_path} if return_path else {}),
        },
        follow_redirects=False,
    )
    transaction = AuthTransactionCodec(TEST_TRANSACTION_KEY).decode(
        started.cookies["ac_oauth_transaction"]
    )

    response = client.get(
        "/v1/auth/google/callback",
        params={
            "state": transaction.state,
            "code": "google-authorization-code",
            "action": "register",
            "consent": "true",
            "course": "other-course",
            "return_path": "/settings",
        },
        follow_redirects=False,
    )

    assert transaction.authorization_type is ProviderAuthorizationType.AUTHENTICATE
    assert response.status_code == 303
    assert transaction.return_path == (return_path or "/home")
    assert response.headers["location"] == "https://app.authorityclosers.test" + (
        return_path or "/home"
    )
    assert response.cookies["ac_session"] == VALID_SESSION_TOKEN
    assert _IdentityApplication.registered_provider_calls == []


@pytest.mark.parametrize("surface", ["learner", "admin", "coach"])
@pytest.mark.parametrize("has_existing_membership", [True, False])
def test_google_login_selects_only_existing_public_learner_context(
    monkeypatch: pytest.MonkeyPatch,
    surface: str,
    has_existing_membership: bool,
) -> None:
    selections: list[tuple[str, UUID]] = []
    queries: list[object] = []

    class ExistingMembershipDatabase(_AsyncContext):
        async def scalar(self, statement: object) -> object | None:
            queries.append(statement)
            return object() if has_existing_membership else None

    class SelectingIdentity(_CallbackIdentityApplication):
        async def select_tenant(self, token: str, tenant_id: UUID) -> object:
            selections.append((token, tenant_id))
            return object()

    database = ExistingMembershipDatabase()
    monkeypatch.setitem(globals(), "_sessions", lambda: database)
    monkeypatch.setattr(auth_module, "AsyncIdentityApplication", SelectingIdentity)
    client = _client(
        provider=_SuccessfulProvider(),
        settings=_settings().model_copy(
            update={"coach_app_url": AnyHttpUrl("https://coach.authorityclosers.test")}
        ),
    )
    origin = "https://coach.authorityclosers.test" if surface == "coach" else "http://testserver"
    started = client.get(
        origin + "/v1/auth/google/start",
        params={"action": "authenticate", "surface": surface},
        follow_redirects=False,
    )
    transaction = AuthTransactionCodec(TEST_TRANSACTION_KEY).decode(
        started.cookies["ac_oauth_transaction"]
    )
    response = client.get(
        origin + "/v1/auth/google/callback",
        params={"state": transaction.state, "code": "google-authorization-code"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.cookies["ac_session"] == VALID_SESSION_TOKEN
    expected_tenant = _settings().public_learner_tenant_id
    assert selections == (
        [(VALID_SESSION_TOKEN, expected_tenant)]
        if surface == "learner" and has_existing_membership
        else []
    )
    assert len(queries) == (1 if surface == "learner" else 0)
    if queries:
        parameters = cast(Any, queries[0]).compile().params
        assert set(parameters.values()) == {
            expected_tenant,
            UUID("11111111-1111-4111-8111-111111111111"),
            "learner",
            "active",
        }
    assert _IdentityApplication.registered_provider_calls == []


def test_dangling_provider_identity_remains_a_fail_closed_integrity_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        auth_module,
        "AsyncIdentityApplication",
        _CorruptProviderIdentityApplication,
    )
    client = _client(provider=_SuccessfulProvider())
    started = client.get(
        "/v1/auth/google/start",
        params={"action": "authenticate", "surface": "learner"},
        follow_redirects=False,
    )
    transaction = AuthTransactionCodec(TEST_TRANSACTION_KEY).decode(
        started.cookies["ac_oauth_transaction"]
    )

    response = client.get(
        "/v1/auth/google/callback",
        params={"state": transaction.state, "code": "google-authorization-code"},
        follow_redirects=False,
    )

    assert response.status_code == 401
    assert response.json()["code"] == "authentication_rejected"
    assert "location" not in response.headers
    cleared = "\n".join(response.headers.get_list("set-cookie")).lower()
    assert "ac_oauth_transaction=" in cleared
    assert "max-age=0" in cleared


def test_provider_key_collision_remains_fail_closed_during_registration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        auth_module,
        "AsyncIdentityApplication",
        _ProviderCollisionIdentityApplication,
    )
    client = _client(provider=_SuccessfulProvider())
    started = client.get(
        "/v1/auth/google/start",
        params={
            "action": "register",
            "surface": "learner",
            "consent": "true",
        },
        follow_redirects=False,
    )
    transaction = AuthTransactionCodec(TEST_TRANSACTION_KEY).decode(
        started.cookies["ac_oauth_transaction"]
    )

    response = client.get(
        "/v1/auth/google/callback",
        params={"state": transaction.state, "code": "google-authorization-code"},
        follow_redirects=False,
    )

    assert response.status_code == 401
    assert response.json()["code"] == "authentication_rejected"
    assert "location" not in response.headers
    cleared = "\n".join(response.headers.get_list("set-cookie")).lower()
    assert "ac_oauth_transaction=" in cleared
    assert "max-age=0" in cleared


def test_deployment_session_cookie_rejects_raw_duplicate_fields_before_actor_resolution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _ForbiddenActorResolutionApplication.actor_resolution_calls = 0
    monkeypatch.setattr(
        auth_module,
        "AsyncIdentityApplication",
        _ForbiddenActorResolutionApplication,
    )
    client = _client(settings=_staging_settings())

    response = client.get(
        "/v1/context",
        headers=[
            ("host", "api.staging.ac.internal.invalid"),
            ("cookie", f"{DEPLOYMENT_SESSION_COOKIE}={VALID_SESSION_TOKEN}"),
            ("cookie", f"{DEPLOYMENT_SESSION_COOKIE}={SECOND_VALID_SESSION_TOKEN}"),
        ],
    )

    assert response.status_code == 401
    assert response.json()["code"] == "authentication_required"
    assert _ForbiddenActorResolutionApplication.actor_resolution_calls == 0


@pytest.mark.parametrize(
    "cookie_headers",
    [
        (
            f"{DEPLOYMENT_SESSION_COOKIE}={VALID_SESSION_TOKEN}",
            f"{DEPLOYMENT_SESSION_COOKIE}={SECOND_VALID_SESSION_TOKEN}",
        ),
        (
            f"{DEPLOYMENT_SESSION_COOKIE}={VALID_SESSION_TOKEN}; "
            f"{DEPLOYMENT_SESSION_COOKIE}={SECOND_VALID_SESSION_TOKEN}",
        ),
        (f"{DEPLOYMENT_SESSION_COOKIE}=too-short",),
        (f"{DEPLOYMENT_SESSION_COOKIE}={VALID_SESSION_TOKEN},second",),
    ],
)
def test_deployment_session_cookie_raw_parser_rejects_duplicates_and_malformed_values(
    cookie_headers: tuple[str, ...],
) -> None:
    with pytest.raises(auth_module.AuthenticationRequired):
        auth_module._session_cookie(  # noqa: SLF001 - security boundary unit test
            _request_with_raw_cookie_headers(*cookie_headers),
            _staging_settings(),
        )


def test_deployment_session_cookie_raw_parser_accepts_one_value_across_split_headers() -> None:
    token = auth_module._session_cookie(  # noqa: SLF001 - security boundary unit test
        _request_with_raw_cookie_headers(
            "unrelated=value",
            f"{DEPLOYMENT_SESSION_COOKIE}={VALID_SESSION_TOKEN}; another=value",
        ),
        _staging_settings(),
    )

    assert token == VALID_SESSION_TOKEN


def test_deployment_oauth_cookie_rejects_raw_duplicate_fields_before_callback_exchange() -> None:
    provider = _SuccessfulProvider()
    client = _client(settings=_staging_settings(), provider=provider)
    started = client.get(
        "/v1/auth/google/start",
        params={"action": "authenticate", "surface": "learner"},
        headers={"host": "staging.authorityclosers.com"},
        follow_redirects=False,
    )
    encoded = started.cookies[DEPLOYMENT_OAUTH_COOKIE]
    transaction = AuthTransactionCodec(
        "staging-oauth-transaction-secret-that-is-long-enough"
    ).decode(encoded)
    client.cookies.clear()

    response = client.get(
        "/v1/auth/google/callback",
        params={"state": transaction.state, "code": "google-authorization-code"},
        headers=[
            ("host", "staging.authorityclosers.com"),
            ("cookie", f"{DEPLOYMENT_OAUTH_COOKIE}={encoded}"),
            ("cookie", f"{DEPLOYMENT_OAUTH_COOKIE}={encoded}"),
        ],
        follow_redirects=False,
    )

    assert response.status_code == 400
    assert response.json()["code"] == "invalid_auth_transaction"
    assert provider.redirect_uris == []


def test_deployment_oauth_cookie_raw_parser_rejects_malformed_value() -> None:
    request = _request_with_raw_cookie_headers(f"{DEPLOYMENT_OAUTH_COOKIE}=not.valid")

    with pytest.raises(auth_module.InvalidAuthTransaction):
        auth_module._oauth_transaction_cookie(  # noqa: SLF001 - security boundary unit test
            request,
            _staging_settings(),
        )


def test_deployment_session_cookie_delete_keeps_host_prefix_attributes() -> None:
    response = Response()

    auth_module._delete_session_cookie(  # noqa: SLF001 - cookie attribute regression test
        response,
        _staging_settings(),
    )

    set_cookie = response.headers["set-cookie"].lower()
    assert set_cookie.startswith(f"{DEPLOYMENT_SESSION_COOKIE.lower()}=")
    assert "secure" in set_cookie
    assert "httponly" in set_cookie
    assert "samesite=lax" in set_cookie
    assert "path=/" in set_cookie
    assert "domain=" not in set_cookie


@pytest.mark.parametrize("cookie", [None, "malformed"])
def test_logout_clears_missing_or_malformed_session_cookie_idempotently(
    monkeypatch: pytest.MonkeyPatch,
    cookie: str | None,
) -> None:
    _LogoutIdentityApplication.reset()
    monkeypatch.setattr(auth_module, "AsyncIdentityApplication", _LogoutIdentityApplication)
    headers = {"Origin": "https://app.authorityclosers.test"}
    if cookie is not None:
        headers["Cookie"] = f"ac_session={cookie}"

    response = _client().post("/v1/auth/logout", headers=headers)

    assert response.status_code == 204
    assert _LogoutIdentityApplication.revoke_calls == []
    assert 'ac_session=""' in response.headers["set-cookie"]


def test_logout_revokes_a_live_session_and_remains_idempotent_for_an_expired_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _LogoutIdentityApplication.reset()
    monkeypatch.setattr(auth_module, "AsyncIdentityApplication", _LogoutIdentityApplication)
    headers = {
        "Origin": "https://app.authorityclosers.test",
        "Cookie": f"ac_session={VALID_SESSION_TOKEN}",
    }

    live = _client().post("/v1/auth/logout", headers=headers)

    assert live.status_code == 204
    assert _LogoutIdentityApplication.revoke_calls == [
        (
            VALID_SESSION_TOKEN,
            UUID("44444444-4444-4444-8444-444444444444"),
            "user_logout",
        )
    ]
    assert 'ac_session=""' in live.headers["set-cookie"]

    _LogoutIdentityApplication.reset()
    _LogoutIdentityApplication.reject_resolution = True
    expired = _client().post("/v1/auth/logout", headers=headers)

    assert expired.status_code == 204
    assert _LogoutIdentityApplication.revoke_calls == []
    assert 'ac_session=""' in expired.headers["set-cookie"]


def test_logout_clears_browser_cookie_when_server_revocation_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _LogoutIdentityApplication.reset()
    _LogoutIdentityApplication.reject_revocation_with_database_error = True
    monkeypatch.setattr(auth_module, "AsyncIdentityApplication", _LogoutIdentityApplication)

    response = _client().post(
        "/v1/auth/logout",
        headers={
            "Origin": "https://app.authorityclosers.test",
            "Cookie": f"ac_session={VALID_SESSION_TOKEN}",
        },
    )

    assert response.status_code == 503
    assert response.json()["code"] == "logout_revocation_unavailable"
    assert "retry" not in response.json()["detail"].lower()
    assert "this browser is signed out" in response.json()["detail"].lower()
    assert response.headers["cache-control"] == "no-store"
    assert 'ac_session=""' in response.headers["set-cookie"]
    assert _LogoutIdentityApplication.revoke_calls == []


def _request_with_host_and_origin(*, host: str, origin: str) -> Request:
    return Request(
        {
            "type": "http",
            "method": "POST",
            "scheme": "https",
            "path": "/v1/auth/logout",
            "headers": [
                (b"host", host.encode("ascii")),
                (b"origin", origin.encode("ascii")),
            ],
            "query_string": b"",
            "server": (host, 443),
            "client": ("127.0.0.1", 1),
        }
    )


def test_staging_cookie_mutations_require_the_request_surface_origin() -> None:
    settings = _staging_settings()

    require_safe_origin(
        _request_with_host_and_origin(
            host="admin-staging.authorityclosers.com",
            origin="https://admin-staging.authorityclosers.com",
        ),
        settings,
    )

    with pytest.raises(auth_module.RequestOriginDenied):
        require_safe_origin(
            _request_with_host_and_origin(
                host="admin-staging.authorityclosers.com",
                origin="https://staging.authorityclosers.com",
            ),
            settings,
        )


def test_sales_xray_same_origin_put_without_origin_is_allowed() -> None:
    settings = _staging_settings().model_copy(
        update={"sales_xray_app_url": AnyHttpUrl("https://salesxray-staging.authorityclosers.com")}
    )
    submission_path = (
        "/v1/conversation/acquisition/submissions/00000000-0000-4000-8000-000000000000/source"
    )

    request = Request(
        {
            "type": "http",
            "method": "PUT",
            "scheme": "https",
            "path": submission_path,
            "headers": [(b"host", b"salesxray-staging.authorityclosers.com")],
            "query_string": b"",
            "server": ("salesxray-staging.authorityclosers.com", 443),
            "client": ("127.0.0.1", 1),
        }
    )

    require_safe_origin(request, settings)

    request = Request(
        {
            "type": "http",
            "method": "PUT",
            "scheme": "https",
            "path": submission_path,
            "headers": [
                (b"host", b"salesxray-staging.authorityclosers.com"),
                (b"origin", b"https://attacker.example"),
            ],
            "query_string": b"",
            "server": ("salesxray-staging.authorityclosers.com", 443),
            "client": ("127.0.0.1", 1),
        }
    )
    with pytest.raises(auth_module.RequestOriginDenied):
        require_safe_origin(request, settings)


def test_external_return_url_is_rejected_without_contacting_provider() -> None:
    response = _client().get(
        "/v1/auth/google/start",
        params={"action": "register", "return_path": "https://evil.example/steal"},
        follow_redirects=False,
    )

    assert response.status_code == 400
    assert response.json()["code"] == "invalid_auth_transaction"
    assert "location" not in response.headers


def test_learner_google_registration_requires_explicit_browser_consent() -> None:
    response = _client().get(
        "/v1/auth/google/start",
        params={"action": "register", "surface": "learner"},
        follow_redirects=False,
    )

    assert response.status_code == 400
    assert response.json()["code"] == "learner_consent_required"
    assert "location" not in response.headers


@pytest.mark.parametrize(
    ("learner_consent_version", "public_learner_tenant_id"),
    [
        (None, UUID("22222222-2222-4222-8222-222222222222")),
        ("staging-test-document-v1", None),
    ],
)
def test_learner_google_registration_requires_reviewed_consent_and_public_tenant_config(
    learner_consent_version: str | None,
    public_learner_tenant_id: UUID | None,
) -> None:
    settings = _settings().model_copy(
        update={
            "learner_consent_version": learner_consent_version,
            "public_learner_tenant_id": public_learner_tenant_id,
        }
    )

    response = _client(settings=settings).get(
        "/v1/auth/google/start",
        params={
            "action": "register",
            "surface": "learner",
            "consent": "true",
        },
        follow_redirects=False,
    )

    assert response.status_code == 503
    assert response.json()["code"] == "password_registration_unavailable"
    assert "location" not in response.headers


def test_existing_google_authentication_does_not_require_registration_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(auth_module, "AsyncIdentityApplication", _CallbackIdentityApplication)
    client = _client(
        settings=_settings_without_registration_config(),
        provider=_SuccessfulProvider(),
    )

    started = client.get(
        "/v1/auth/google/start",
        params={
            "action": "authenticate",
            "surface": "learner",
            "return_path": "/home",
        },
        follow_redirects=False,
    )

    assert started.status_code == 303
    transaction = AuthTransactionCodec(TEST_TRANSACTION_KEY).decode(
        started.cookies["ac_oauth_transaction"]
    )
    assert transaction.authorization_type is ProviderAuthorizationType.AUTHENTICATE
    assert transaction.consent_version is None

    callback = client.get(
        "/v1/auth/google/callback",
        params={"state": transaction.state, "code": "google-authorization-code"},
        follow_redirects=False,
    )

    assert callback.status_code == 303
    assert callback.headers["location"] == "https://app.authorityclosers.test/home"
    assert callback.cookies["ac_session"] == VALID_SESSION_TOKEN
    assert _IdentityApplication.registered_provider_calls == []


@pytest.mark.parametrize("callback_order", [(0, 1), (1, 0)])
def test_two_google_starts_can_callback_in_either_order_without_cookie_overwrite(
    monkeypatch: pytest.MonkeyPatch,
    callback_order: tuple[int, int],
) -> None:
    monkeypatch.setattr(auth_module, "AsyncIdentityApplication", _CallbackIdentityApplication)
    provider = _SuccessfulProvider()
    client = _client(provider=provider)
    transactions: list[AuthTransaction] = []
    encoded_transactions: list[str] = []
    cookie_names: list[str] = []

    for position in range(2):
        started = client.get(
            "/v1/auth/google/start",
            params={
                "action": "authenticate",
                "surface": "learner",
                "return_path": f"/home?flow={position + 1}",
            },
            follow_redirects=False,
        )
        encoded = started.cookies["ac_oauth_transaction"]
        transaction = AuthTransactionCodec(TEST_TRANSACTION_KEY).decode(encoded)
        cookie_name = auth_module._oauth_transaction_cookie_name(  # noqa: SLF001
            _settings(),
            transaction.state,
        )

        assert started.status_code == 303
        assert started.cookies[cookie_name] == encoded
        state_cookie_header = next(
            value.lower()
            for value in started.headers.get_list("set-cookie")
            if value.startswith(f"{cookie_name}=")
        )
        assert f"max-age={AUTH_TRANSACTION_MAX_AGE_SECONDS}" in state_cookie_header
        assert "httponly" in state_cookie_header
        assert "samesite=lax" in state_cookie_header
        assert "path=/" in state_cookie_header

        transactions.append(transaction)
        encoded_transactions.append(encoded)
        cookie_names.append(cookie_name)

    assert client.cookies.get(cookie_names[0]) == encoded_transactions[0]
    assert client.cookies.get(cookie_names[1]) == encoded_transactions[1]
    assert client.cookies.get("ac_oauth_transaction") == encoded_transactions[1]

    first, second = callback_order
    first_callback = client.get(
        "/v1/auth/google/callback",
        params={
            "state": transactions[first].state,
            "code": "google-authorization-code",
        },
        follow_redirects=False,
    )

    assert first_callback.status_code == 303
    assert first_callback.headers["location"] == (
        f"https://app.authorityclosers.test/home?flow={first + 1}"
    )
    assert client.cookies.get(cookie_names[first]) is None
    assert client.cookies.get(cookie_names[second]) == encoded_transactions[second]
    if first == 0:
        assert client.cookies.get("ac_oauth_transaction") == encoded_transactions[1]
    else:
        assert client.cookies.get("ac_oauth_transaction") is None

    second_callback = client.get(
        "/v1/auth/google/callback",
        params={
            "state": transactions[second].state,
            "code": "google-authorization-code",
        },
        follow_redirects=False,
    )

    assert second_callback.status_code == 303
    assert second_callback.headers["location"] == (
        f"https://app.authorityclosers.test/home?flow={second + 1}"
    )
    assert client.cookies.get(cookie_names[second]) is None
    assert client.cookies.get("ac_oauth_transaction") is None
    assert len(provider.redirect_uris) == 2


def test_parallel_register_and_authenticate_callbacks_remain_action_bound(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(auth_module, "AsyncIdentityApplication", _CallbackIdentityApplication)
    client = _client(provider=_SuccessfulProvider())
    register_start = client.get(
        "/v1/auth/google/start",
        params={
            "action": "register",
            "surface": "learner",
            "return_path": "/welcome",
            "consent": "true",
        },
        follow_redirects=False,
    )
    register_encoded = register_start.cookies["ac_oauth_transaction"]
    register_transaction = AuthTransactionCodec(TEST_TRANSACTION_KEY).decode(register_encoded)
    register_cookie_name = auth_module._oauth_transaction_cookie_name(  # noqa: SLF001
        _settings(),
        register_transaction.state,
    )
    authenticate_start = client.get(
        "/v1/auth/google/start",
        params={
            "action": "authenticate",
            "surface": "learner",
            "return_path": "/home",
        },
        follow_redirects=False,
    )
    authenticate_encoded = authenticate_start.cookies["ac_oauth_transaction"]
    authenticate_transaction = AuthTransactionCodec(TEST_TRANSACTION_KEY).decode(
        authenticate_encoded
    )
    authenticate_cookie_name = auth_module._oauth_transaction_cookie_name(  # noqa: SLF001
        _settings(),
        authenticate_transaction.state,
    )

    register_callback = client.get(
        "/v1/auth/google/callback",
        params={
            "state": register_transaction.state,
            "code": "google-authorization-code",
            "action": "authenticate",
        },
        follow_redirects=False,
    )

    assert register_transaction.authorization_type is ProviderAuthorizationType.REGISTER
    assert register_callback.status_code == 303
    assert register_callback.headers["location"] == "https://app.authorityclosers.test/welcome"
    assert len(_IdentityApplication.registered_provider_calls) == 1
    assert _IdentityApplication.registered_provider_calls[0]["transaction_id"] == (
        register_transaction.transaction_id
    )
    assert _IdentityApplication.registered_provider_calls[0]["consent_version"] == (
        "staging-test-document-v1"
    )
    assert client.cookies.get(register_cookie_name) is None
    assert client.cookies.get(authenticate_cookie_name) == authenticate_encoded
    assert client.cookies.get("ac_oauth_transaction") == authenticate_encoded

    authenticate_callback = client.get(
        "/v1/auth/google/callback",
        params={
            "state": authenticate_transaction.state,
            "code": "google-authorization-code",
            "action": "register",
            "consent": "true",
        },
        follow_redirects=False,
    )

    assert authenticate_transaction.authorization_type is ProviderAuthorizationType.AUTHENTICATE
    assert authenticate_callback.status_code == 303
    assert authenticate_callback.headers["location"] == "https://app.authorityclosers.test/home"
    assert len(_IdentityApplication.registered_provider_calls) == 1
    assert client.cookies.get(authenticate_cookie_name) is None
    assert client.cookies.get("ac_oauth_transaction") is None


def test_oauth_start_bounds_pending_state_keyed_cookies_and_prunes_stale_state() -> None:
    provider = _SuccessfulProvider()
    client = _client(provider=provider)
    transactions: list[AuthTransaction] = []
    cookie_names: list[str] = []

    for position in range(auth_module.OAUTH_TRANSACTION_MAX_PENDING + 1):
        started = client.get(
            "/v1/auth/google/start",
            params={
                "action": "authenticate",
                "surface": "learner",
                "return_path": f"/home?flow={position}",
            },
            follow_redirects=False,
        )
        transaction = AuthTransactionCodec(TEST_TRANSACTION_KEY).decode(
            started.cookies["ac_oauth_transaction"]
        )
        transactions.append(transaction)
        cookie_names.append(
            auth_module._oauth_transaction_cookie_name(  # noqa: SLF001
                _settings(),
                transaction.state,
            )
        )

    pending_names = {
        cookie.name
        for cookie in client.cookies.jar
        if cookie.name.startswith("ac_oauth_transaction.")
    }
    transaction_cookies = [
        cookie
        for cookie in client.cookies.jar
        if cookie.name == "ac_oauth_transaction" or cookie.name.startswith("ac_oauth_transaction.")
    ]
    pruned_names = set(cookie_names) - pending_names

    assert len(pending_names) == auth_module.OAUTH_TRANSACTION_MAX_PENDING
    assert len(transaction_cookies) == auth_module.OAUTH_TRANSACTION_MAX_PENDING + 1
    assert all(len(cookie.value) <= 4000 for cookie in transaction_cookies)
    assert len(pruned_names) == 1
    assert cookie_names[-1] in pending_names
    assert client.cookies.get("ac_oauth_transaction") is not None

    pruned_index = cookie_names.index(pruned_names.pop())
    stale_callback = client.get(
        "/v1/auth/google/callback",
        params={
            "state": transactions[pruned_index].state,
            "code": "must-not-be-exchanged",
        },
        follow_redirects=False,
    )

    assert stale_callback.status_code == 400
    assert stale_callback.json()["code"] == "invalid_auth_transaction"
    assert provider.redirect_uris == []


def test_oauth_callback_rejects_missing_transaction_cookie_before_exchange() -> None:
    provider = _SuccessfulProvider()
    response = _client(provider=provider).get(
        "/v1/auth/google/callback",
        params={"state": "s" * 43, "code": "must-not-be-exchanged"},
        follow_redirects=False,
    )

    assert response.status_code == 400
    assert response.json()["code"] == "invalid_auth_transaction"
    assert provider.redirect_uris == []


def test_oauth_callback_rejects_tampered_state_keyed_cookie_before_exchange() -> None:
    provider = _SuccessfulProvider()
    client = _client(provider=provider)
    started = client.get(
        "/v1/auth/google/start",
        params={"action": "authenticate", "surface": "learner"},
        follow_redirects=False,
    )
    transaction = AuthTransactionCodec(TEST_TRANSACTION_KEY).decode(
        started.cookies["ac_oauth_transaction"]
    )
    cookie_name = auth_module._oauth_transaction_cookie_name(  # noqa: SLF001
        _settings(),
        transaction.state,
    )
    client.cookies.clear()

    response = client.get(
        "/v1/auth/google/callback",
        params={"state": transaction.state, "code": "must-not-be-exchanged"},
        headers={"cookie": f"{cookie_name}=A.{('B' * 43)}"},
        follow_redirects=False,
    )

    assert response.status_code == 400
    assert response.json()["code"] == "invalid_auth_transaction"
    assert provider.redirect_uris == []


def test_oauth_callback_rejects_expired_state_keyed_cookie_before_exchange() -> None:
    provider = _SuccessfulProvider()
    client = _client(provider=provider)
    transaction = AuthTransaction.issue(
        ProviderAuthorizationType.AUTHENTICATE,
        surface="learner",
        return_path="/home",
        now=int(datetime.now(UTC).timestamp()) - AUTH_TRANSACTION_MAX_AGE_SECONDS - 1,
    )
    cookie_name = auth_module._oauth_transaction_cookie_name(  # noqa: SLF001
        _settings(),
        transaction.state,
    )

    response = client.get(
        "/v1/auth/google/callback",
        params={"state": transaction.state, "code": "must-not-be-exchanged"},
        headers={
            "cookie": (
                f"{cookie_name}={AuthTransactionCodec(TEST_TRANSACTION_KEY).encode(transaction)}"
            )
        },
        follow_redirects=False,
    )

    assert response.status_code == 400
    assert response.json()["code"] == "invalid_auth_transaction"
    assert provider.redirect_uris == []


def test_oauth_transaction_secret_rotation_requires_pending_callbacks_to_restart() -> None:
    provider = _SuccessfulProvider()
    rotated_settings = _settings().model_copy(
        update={
            "oauth_transaction_secret": SecretStr(
                "rotated-test-route-transaction-signing-key-long-enough"
            )
        }
    )
    client = _client(settings=rotated_settings, provider=provider)
    transaction = AuthTransaction.issue(
        ProviderAuthorizationType.AUTHENTICATE,
        surface="learner",
        return_path="/home",
    )
    cookie_name = auth_module._oauth_transaction_cookie_name(  # noqa: SLF001
        rotated_settings,
        transaction.state,
    )

    response = client.get(
        "/v1/auth/google/callback",
        params={"state": transaction.state, "code": "must-not-be-exchanged"},
        headers={
            "cookie": (
                f"{cookie_name}={AuthTransactionCodec(TEST_TRANSACTION_KEY).encode(transaction)}"
            )
        },
        follow_redirects=False,
    )

    assert response.status_code == 400
    assert response.json()["code"] == "invalid_auth_transaction"
    assert provider.redirect_uris == []


@pytest.mark.parametrize(
    "return_path",
    [
        None,
        "/onboarding?course=authority-closers-free-course",
        "/onboarding?activity=86f7efee-f504-4d6f-b4bc-9b3cb84ba2be",
        "/onboarding?course=authority-closers-free-course"
        "&activity=86f7efee-f504-4d6f-b4bc-9b3cb84ba2be",
    ],
)
def test_learner_google_registration_binds_consent_and_selects_public_tenant(
    return_path: str | None,
) -> None:
    provider = _SuccessfulProvider()
    client = _client(provider=provider)
    started = client.get(
        "/v1/auth/google/start",
        params={
            "action": "register",
            "surface": "learner",
            "consent": "true",
            **({"return_path": return_path} if return_path else {}),
        },
        follow_redirects=False,
    )

    assert started.status_code == 303
    transaction = AuthTransactionCodec(TEST_TRANSACTION_KEY).decode(
        started.cookies["ac_oauth_transaction"]
    )
    assert transaction.consent_version == "staging-test-document-v1"

    callback = client.get(
        "/v1/auth/google/callback",
        params={"state": transaction.state, "code": "google-authorization-code"},
        follow_redirects=False,
    )

    assert callback.status_code == 303
    assert transaction.return_path == (return_path or "/home")
    assert transaction.authorization_type is ProviderAuthorizationType.REGISTER
    assert callback.headers["location"] == "https://app.authorityclosers.test" + (
        return_path or "/home"
    )
    assert len(_IdentityApplication.registered_provider_calls) == 1
    assert _IdentityApplication.registered_provider_calls[0]["consent_version"] == (
        "staging-test-document-v1"
    )
    assert provider.redirect_uris == ["https://app.authorityclosers.test/v1/auth/google/callback"]


def test_stale_learner_google_registration_callback_is_rejected_before_exchange() -> None:
    client = _client()
    transaction = AuthTransaction.issue(
        ProviderAuthorizationType.REGISTER,
        surface="learner",
        return_path="/home",
    )
    client.cookies.set(
        "ac_oauth_transaction",
        AuthTransactionCodec(TEST_TRANSACTION_KEY).encode(transaction),
    )

    response = client.get(
        "/v1/auth/google/callback",
        params={"state": transaction.state, "code": "must-not-be-exchanged"},
        follow_redirects=False,
    )

    assert response.status_code == 503
    assert response.json()["code"] == "password_registration_unavailable"


def test_learner_google_registration_rejects_a_superseded_consent_version() -> None:
    provider = _RecordingProvider()
    client = _client(provider=provider)
    transaction = AuthTransaction.issue(
        ProviderAuthorizationType.REGISTER,
        surface="learner",
        return_path="/home",
        consent_version="superseded-consent-v1",
    )
    client.cookies.set(
        "ac_oauth_transaction",
        AuthTransactionCodec(TEST_TRANSACTION_KEY).encode(transaction),
    )

    response = client.get(
        "/v1/auth/google/callback",
        params={"state": transaction.state, "code": "must-not-be-exchanged"},
        follow_redirects=False,
    )

    assert response.status_code == 503
    assert response.json()["code"] == "password_registration_unavailable"


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
