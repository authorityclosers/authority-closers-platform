"""Standalone Sales Xray host admission and canonical Academy authentication."""

from __future__ import annotations

from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from pydantic import ValidationError

import ac_platform.http.auth as auth_module
from ac_platform.application.settings import Settings
from ac_platform.http.auth import RequestOriginDenied
from ac_platform.http.auth_transactions import AuthTransaction, AuthTransactionCodec
from ac_platform.http.conversation import install_conversation_http
from ac_platform.http.problem import register_problem_handlers
from ac_platform.identity.services import ProviderAuthorizationType
from tests.unit.application.test_settings import _deployment_values
from tests.unit.http.test_auth_routes import (
    DEPLOYMENT_OAUTH_COOKIE,
    DEPLOYMENT_SESSION_COOKIE,
    VALID_SESSION_TOKEN,
    _CallbackIdentityApplication,
    _client,
    _IdentityApplication,
    _LearnerProvisioningApplication,
    _RecordingProvider,
    _request_with_host_and_origin,
    _settings,
    _staging_settings,
    _SuccessfulProvider,
)

SALES_STAGING_ORIGIN = "https://salesxray-staging.authorityclosers.com"
SALES_PRODUCTION_ORIGIN = "https://salesxray.authorityclosers.com"
SALES_STAGING_HOST = "salesxray-staging.authorityclosers.com"


@pytest.fixture(autouse=True)
def _replace_identity_application(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep these route tests on the same disposable identity adapter as auth route tests."""

    monkeypatch.setattr(auth_module, "AsyncIdentityApplication", _IdentityApplication)
    monkeypatch.setattr(
        auth_module,
        "AsyncLearnerProvisioningApplication",
        _LearnerProvisioningApplication,
    )


def _sales_staging_settings() -> Settings:
    values = _deployment_values("staging")
    values.update(
        {
            "sales_xray_app_url": SALES_STAGING_ORIGIN,
            "learner_consent_version": "staging-test-document-v1",
            "public_learner_tenant_id": "22222222-2222-4222-8222-222222222222",
            "operations_tenant_id": "33333333-3333-4333-8333-333333333333",
        }
    )
    return Settings(environment="staging", _env_file=None, **values)  # type: ignore[arg-type]


def _workspace_client(settings: Settings) -> TestClient:
    application = FastAPI()
    register_problem_handlers(application)
    install_conversation_http(application, settings=settings)
    return TestClient(application)


def _sales_start(
    client: TestClient,
    *,
    return_path: str = "/sales-xray",
) -> tuple[Any, str]:
    response = client.get(
        "/v1/auth/google/start",
        params={
            "action": "authenticate",
            "surface": "sales_xray",
            "return_path": return_path,
        },
        headers={"host": SALES_STAGING_HOST},
        follow_redirects=False,
    )
    settings = _sales_staging_settings()
    transaction = AuthTransactionCodec(settings.oauth_transaction_secret.get_secret_value()).decode(
        response.cookies[DEPLOYMENT_OAUTH_COOKIE]
    )
    return response, transaction


@pytest.mark.parametrize(
    ("environment", "expected_origin"),
    [
        ("staging", SALES_STAGING_ORIGIN),
        ("production", SALES_PRODUCTION_ORIGIN),
    ],
)
def test_deployment_accepts_only_the_reviewed_sales_xray_origin(
    environment: str,
    expected_origin: str,
) -> None:
    values = _deployment_values(environment)
    values["sales_xray_app_url"] = expected_origin

    settings = Settings(environment=environment, _env_file=None, **values)  # type: ignore[arg-type]

    assert str(settings.sales_xray_app_url).rstrip("/") == expected_origin
    assert settings.sales_xray_app_url.host in settings.allowed_hosts
    assert expected_origin in settings.allowed_origins


@pytest.mark.parametrize(
    "value",
    [
        "http://salesxray-staging.authorityclosers.com",
        "https://salesxray.authorityclosers.com",
        "https://salesxray-staging.authorityclosers.com/v1",
        "https://salesxray-staging.authorityclosers.com?surface=learner",
        "https://salesxray-staging.authorityclosers.com#home",
        "https://user@salesxray-staging.authorityclosers.com",
        "https://user:password@salesxray-staging.authorityclosers.com",
        "https://salesxray-staging.authorityclosers.com:443",
        " https://salesxray-staging.authorityclosers.com",
    ],
)
def test_staging_rejects_unreviewed_sales_xray_origin(value: str) -> None:
    values = _deployment_values("staging")
    values["sales_xray_app_url"] = value

    with pytest.raises(ValidationError):
        Settings(environment="staging", _env_file=None, **values)  # type: ignore[arg-type]


def test_sales_xray_origin_is_optional_and_only_trusted_when_configured() -> None:
    unconfigured = Settings(_env_file=None)

    assert unconfigured.sales_xray_app_url is None
    assert SALES_STAGING_HOST not in unconfigured.allowed_hosts
    assert SALES_STAGING_ORIGIN not in unconfigured.allowed_origins

    configured = _sales_staging_settings()
    assert SALES_STAGING_HOST in configured.allowed_hosts
    assert SALES_STAGING_ORIGIN in configured.allowed_origins


@pytest.mark.parametrize(
    "existing_field", ["public_app_url", "admin_app_url", "coach_app_url", "api_url"]
)
def test_sales_xray_host_must_be_distinct_from_existing_surfaces(existing_field: str) -> None:
    base = _settings()
    values = base.model_dump()
    values["sales_xray_app_url"] = str(getattr(base, existing_field))

    with pytest.raises(ValidationError):
        Settings(_env_file=None, **values)


def test_sales_xray_google_start_issues_an_existing_account_transaction_for_its_host() -> None:
    settings = _sales_staging_settings()
    client = _client(settings=settings, provider=_RecordingProvider())

    response = client.get(
        "/v1/auth/google/start",
        params={
            "action": "authenticate",
            "surface": "sales_xray",
            "return_path": "/sales-xray",
        },
        headers={"host": SALES_STAGING_HOST},
        follow_redirects=False,
    )

    assert response.status_code == 303
    transaction = AuthTransactionCodec(settings.oauth_transaction_secret.get_secret_value()).decode(
        response.cookies[DEPLOYMENT_OAUTH_COOKIE]
    )
    assert transaction.surface == "sales_xray"
    assert transaction.authorization_type is ProviderAuthorizationType.AUTHENTICATE
    provider_query = parse_qs(urlsplit(response.headers["location"]).query)
    assert provider_query["redirect_uri"] == [f"{SALES_STAGING_ORIGIN}/v1/auth/google/callback"]
    assert all(
        attribute in cookie.lower()
        for cookie in response.headers.get_list("set-cookie")
        if cookie.lower().startswith(
            (DEPLOYMENT_OAUTH_COOKIE.lower(), "__host-ac_oauth_transaction.")
        )
        for attribute in ("secure", "httponly", "samesite=lax", "path=/")
    )
    assert all(
        "domain=" not in cookie.lower()
        for cookie in response.headers.get_list("set-cookie")
        if cookie.lower().startswith(
            (DEPLOYMENT_OAUTH_COOKIE.lower(), "__host-ac_oauth_transaction.")
        )
    )


class _TrackingIdentityApplication(_IdentityApplication):
    begin_calls = 0

    async def begin_provider_authorization(self, *args: Any, **kwargs: Any) -> Any:
        type(self).begin_calls += 1
        return await super().begin_provider_authorization(*args, **kwargs)


def test_sales_xray_google_start_rejects_link_before_state_creation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _TrackingIdentityApplication.begin_calls = 0
    monkeypatch.setattr(auth_module, "AsyncIdentityApplication", _TrackingIdentityApplication)
    client = _client(settings=_sales_staging_settings(), provider=_RecordingProvider())

    response = client.get(
        "/v1/auth/google/start",
        params={"action": "link", "surface": "sales_xray"},
        headers={"host": SALES_STAGING_HOST},
        follow_redirects=False,
    )

    assert response.status_code == 400
    assert response.json()["code"] == "invalid_auth_transaction"
    assert "location" not in response.headers
    assert not response.headers.get_list("set-cookie")
    assert _TrackingIdentityApplication.begin_calls == 0


@pytest.mark.parametrize("action", ["register", "authenticate"])
def test_sales_google_consent_aware_entry_registers_in_the_same_academy(
    action: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    provider = _SuccessfulProvider()
    settings = _sales_staging_settings()
    _IdentityApplication.reset_registered_provider_calls()
    selected = []

    async def select_tenant(_identity, token, tenant_id):
        selected.append((token, tenant_id))

    monkeypatch.setattr(_IdentityApplication, "select_tenant", select_tenant)
    client = _client(settings=settings, provider=provider)
    started = client.get(
        "/v1/auth/google/start",
        params={
            "action": action,
            "surface": "sales_xray",
            "consent": "true",
            "consent_version": settings.learner_consent_version,
            "return_path": "/?report=owned-report&continue=claim",
        },
        headers={"host": SALES_STAGING_HOST},
        follow_redirects=False,
    )
    assert started.status_code == 303
    encoded = started.cookies[DEPLOYMENT_OAUTH_COOKIE]
    transaction = AuthTransactionCodec(settings.oauth_transaction_secret.get_secret_value()).decode(
        encoded
    )
    assert transaction.authorization_type is ProviderAuthorizationType.REGISTER
    assert transaction.consent_version == settings.learner_consent_version
    callback = client.get(
        "/v1/auth/google/callback",
        params={"state": transaction.state, "code": "google-authorization-code"},
        headers={"host": SALES_STAGING_HOST, "cookie": f"{DEPLOYMENT_OAUTH_COOKIE}={encoded}"},
        follow_redirects=False,
    )
    assert callback.status_code == 303
    assert (
        callback.headers["location"]
        == SALES_STAGING_ORIGIN + "/?report=owned-report&continue=claim"
    )
    assert selected == [(VALID_SESSION_TOKEN, settings.public_learner_tenant_id)]
    assert len(_IdentityApplication.registered_provider_calls) == 1
    assert callback.cookies[DEPLOYMENT_SESSION_COOKIE] == VALID_SESSION_TOKEN
    assert provider.redirect_uris == [SALES_STAGING_ORIGIN + "/v1/auth/google/callback"]


@pytest.mark.parametrize("consent", [None, "false"])
def test_sales_google_registration_requires_current_consent(consent) -> None:
    client = _client(settings=_sales_staging_settings(), provider=_RecordingProvider())
    response = client.get(
        "/v1/auth/google/start",
        params={
            "action": "register",
            "surface": "sales_xray",
            **({"consent": consent} if consent else {}),
        },
        headers={"host": SALES_STAGING_HOST},
        follow_redirects=False,
    )
    assert response.status_code == 400
    assert response.json()["code"] == "learner_consent_required"
    assert not response.headers.get_list("set-cookie")


@pytest.mark.parametrize("version", [None, "superseded-version"])
def test_sales_google_registration_rejects_missing_or_superseded_version(version) -> None:
    client = _client(settings=_sales_staging_settings(), provider=_RecordingProvider())
    response = client.get(
        "/v1/auth/google/start",
        params={
            "action": "register",
            "surface": "sales_xray",
            "consent": "true",
            **({"consent_version": version} if version else {}),
        },
        headers={"host": SALES_STAGING_HOST},
        follow_redirects=False,
    )
    assert response.status_code == 400
    assert not response.headers.get_list("set-cookie")


@pytest.mark.parametrize("consent_version", [None, "superseded-version"])
def test_sales_google_callback_rechecks_registration_consent_before_exchange(consent_version):
    settings = _sales_staging_settings()
    provider = _SuccessfulProvider()
    transaction = AuthTransaction.issue(
        ProviderAuthorizationType.REGISTER,
        surface="sales_xray",
        return_path="/?report=owned-report",
        consent_version=consent_version,
    )
    encoded = AuthTransactionCodec(settings.oauth_transaction_secret.get_secret_value()).encode(
        transaction
    )
    client = _client(settings=settings, provider=provider)
    callback = client.get(
        "/v1/auth/google/callback",
        params={"state": transaction.state, "code": "must-not-exchange"},
        headers={"host": SALES_STAGING_HOST, "cookie": f"{DEPLOYMENT_OAUTH_COOKIE}={encoded}"},
        follow_redirects=False,
    )
    assert callback.status_code == 503
    assert provider.redirect_uris == []
    assert DEPLOYMENT_SESSION_COOKIE not in callback.cookies


@pytest.mark.parametrize(
    ("callback_host", "callback_state"),
    [
        ("staging.authorityclosers.com", None),
        (SALES_STAGING_HOST, "s" * 32),
    ],
)
def test_sales_xray_google_callback_rejects_cross_surface_host_or_state(
    callback_host: str,
    callback_state: str | None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(auth_module, "AsyncIdentityApplication", _CallbackIdentityApplication)
    provider = _SuccessfulProvider()
    settings = _sales_staging_settings()
    client = _client(settings=settings, provider=provider)
    started, transaction = _sales_start(client)
    encoded = started.cookies[DEPLOYMENT_OAUTH_COOKIE]

    response = client.get(
        "/v1/auth/google/callback",
        params={
            "state": callback_state or transaction.state,
            "code": "google-authorization-code",
        },
        headers={
            "host": callback_host,
            "cookie": f"{DEPLOYMENT_OAUTH_COOKIE}={encoded}",
        },
        follow_redirects=False,
    )

    assert response.status_code == 400
    assert "location" not in response.headers
    assert provider.redirect_uris == []


def test_sales_xray_google_callback_redirects_to_its_host_and_sets_host_only_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(auth_module, "AsyncIdentityApplication", _CallbackIdentityApplication)
    provider = _SuccessfulProvider()
    settings = _sales_staging_settings()
    client = _client(settings=settings, provider=provider)
    started, transaction = _sales_start(client)
    encoded = started.cookies[DEPLOYMENT_OAUTH_COOKIE]

    response = client.get(
        "/v1/auth/google/callback",
        params={"state": transaction.state, "code": "google-authorization-code"},
        headers={
            "host": SALES_STAGING_HOST,
            "cookie": f"{DEPLOYMENT_OAUTH_COOKIE}={encoded}",
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == f"{SALES_STAGING_ORIGIN}/sales-xray"
    assert provider.redirect_uris == [f"{SALES_STAGING_ORIGIN}/v1/auth/google/callback"]
    session_cookie = next(
        value.lower()
        for value in response.headers.get_list("set-cookie")
        if value.lower().startswith(f"{DEPLOYMENT_SESSION_COOKIE.lower()}=")
    )
    assert f"{DEPLOYMENT_SESSION_COOKIE.lower()}={VALID_SESSION_TOKEN}" in session_cookie
    assert all(
        attribute in session_cookie
        for attribute in ("secure", "httponly", "samesite=lax", "path=/")
    )
    assert "domain=" not in session_cookie


@pytest.mark.parametrize(
    ("host", "origin"),
    [
        (SALES_STAGING_HOST, "https://staging.authorityclosers.com"),
        ("staging.authorityclosers.com", SALES_STAGING_ORIGIN),
        (SALES_STAGING_HOST, "https://unknown.example.test"),
    ],
)
def test_sales_xray_cookie_mutation_rejects_cross_surface_or_unknown_origin(
    host: str,
    origin: str,
) -> None:
    client = _client(settings=_sales_staging_settings())

    response = client.post(
        "/v1/auth/logout",
        headers={"host": host, "origin": origin},
    )

    assert response.status_code == 403
    assert response.json()["code"] == "request_origin_denied"


def test_sales_xray_cookie_mutation_accepts_its_own_origin() -> None:
    client = _client(settings=_sales_staging_settings())

    response = client.post(
        "/v1/auth/logout",
        headers={"host": SALES_STAGING_HOST, "origin": SALES_STAGING_ORIGIN},
    )

    assert response.status_code == 204
    assert f'{DEPLOYMENT_SESSION_COOKIE}=""' in response.headers["set-cookie"]


def test_sales_xray_workspace_uses_configured_host_for_sign_in() -> None:
    response = _workspace_client(_sales_staging_settings()).get(
        "/v1/conversation/workspace",
        headers={"host": SALES_STAGING_HOST},
    )

    assert response.status_code == 200
    assert response.json()["sign_in_url"] == f"{SALES_STAGING_ORIGIN}/login"


def test_workspace_keeps_existing_learner_sign_in_when_sales_host_is_unconfigured() -> None:
    settings = _staging_settings()
    response = _workspace_client(settings).get("/v1/conversation/workspace")

    assert response.status_code == 200
    assert response.json()["sign_in_url"] == (
        "https://staging.authorityclosers.com/login?next=/sales-xray"
    )


def test_same_surface_origin_helper_accepts_sales_xray_and_rejects_learner_bridge() -> None:
    settings = _sales_staging_settings()
    auth_module.require_safe_origin(
        _request_with_host_and_origin(
            host=SALES_STAGING_HOST,
            origin=SALES_STAGING_ORIGIN,
        ),
        settings,
    )

    with pytest.raises(RequestOriginDenied):
        auth_module.require_safe_origin(
            _request_with_host_and_origin(
                host=SALES_STAGING_HOST,
                origin="https://staging.authorityclosers.com",
            ),
            settings,
        )


def test_missing_origin_is_opt_in_for_sales_xray_acquisition_only() -> None:
    settings = _sales_staging_settings()
    request = Request(
        {
            "type": "http",
            "method": "POST",
            "scheme": "https",
            "path": "/v1/conversation/acquisition/session",
            "headers": [(b"host", SALES_STAGING_HOST.encode("ascii"))],
            "query_string": b"",
            "server": (SALES_STAGING_HOST, 443),
            "client": ("127.0.0.1", 1),
        }
    )

    with pytest.raises(RequestOriginDenied):
        auth_module.require_safe_origin(request, settings)

    auth_module.require_safe_origin(
        request,
        settings,
        allow_missing_sales_xray_origin=True,
    )

    with pytest.raises(RequestOriginDenied):
        auth_module.require_safe_origin(
            Request(
                {
                    "type": "http",
                    "method": "POST",
                    "scheme": "https",
                    "path": "/v1/conversation/acquisition/session",
                    "headers": [(b"host", b"staging.authorityclosers.com")],
                    "query_string": b"",
                    "server": ("staging.authorityclosers.com", 443),
                    "client": ("127.0.0.1", 1),
                }
            ),
            settings,
            allow_missing_sales_xray_origin=True,
        )
