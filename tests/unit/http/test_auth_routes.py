from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any, cast
from urllib.parse import urlencode, urlsplit
from uuid import UUID

import pytest
from fastapi import FastAPI, Request, Response
from fastapi.testclient import TestClient

import ac_platform.http.auth as auth_module
from ac_platform.application.settings import Settings
from ac_platform.http.auth import install_identity_http, require_safe_origin
from ac_platform.http.auth_transactions import AuthTransaction, AuthTransactionCodec
from ac_platform.http.problem import register_problem_handlers
from ac_platform.identity.services import (
    IssuedProviderAuthorization,
    ProviderAuthorizationType,
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

    async def select_tenant(self, token: str, tenant_id: UUID) -> object:
        del token, tenant_id
        return object()


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


class _ForbiddenActorResolutionApplication(_IdentityApplication):
    actor_resolution_calls = 0

    async def resolve_actor(self, _token: str) -> object:
        type(self).actor_resolution_calls += 1
        raise AssertionError("actor resolution must not run for a rejected raw cookie")


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
    set_cookie = response.headers["set-cookie"].lower()
    assert f"{DEPLOYMENT_OAUTH_COOKIE.lower()}=" in set_cookie
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


def test_external_return_url_is_rejected_without_contacting_provider() -> None:
    response = _client().get(
        "/v1/auth/google/start",
        params={"action": "register", "return_path": "https://evil.example/steal"},
        follow_redirects=False,
    )

    assert response.status_code == 400
    assert response.json()["code"] == "invalid_auth_transaction"
    assert "location" not in response.headers


def test_learner_google_registration_is_disabled_until_signed_consent_exists() -> None:
    response = _client().get(
        "/v1/auth/google/start",
        params={"action": "register", "surface": "learner"},
        follow_redirects=False,
    )

    assert response.status_code == 503
    assert response.json()["code"] == "password_registration_unavailable"
    assert "location" not in response.headers


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
