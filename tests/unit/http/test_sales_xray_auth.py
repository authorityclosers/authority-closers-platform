"""Standalone Sales Xray host admission and canonical Academy authentication."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from urllib.parse import parse_qs, urlsplit
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

import ac_platform.http.auth as auth_module
from ac_platform.application.settings import Settings
from ac_platform.http.auth import RequestOriginDenied
from ac_platform.http.auth_transactions import AuthTransaction, AuthTransactionCodec
from ac_platform.http.conversation import install_conversation_http
from ac_platform.http.problem import register_problem_handlers
from ac_platform.identity.application import ResolvedActorContext
from ac_platform.identity.services import (
    ProviderAuthorizationType,
    ProviderConsentVersionConflictError,
)
from ac_platform.kernel.authz import ActorContext
from tests.unit.application.test_settings import _deployment_values
from tests.unit.http.test_auth_routes import (
    DEPLOYMENT_OAUTH_COOKIE,
    DEPLOYMENT_SESSION_COOKIE,
    SECOND_VALID_SESSION_TOKEN,
    VALID_SESSION_TOKEN,
    _CallbackIdentityApplication,
    _client,
    _IdentityApplication,
    _LearnerProvisioningApplication,
    _RecordingProvider,
    _RejectedProvider,
    _request_with_host_and_origin,
    _settings,
    _staging_settings,
    _SuccessfulProvider,
    _UnavailableProvider,
)

SALES_STAGING_ORIGIN = "https://salesxray-staging.authorityclosers.com"
SALES_PRODUCTION_ORIGIN = "https://salesxray.authorityclosers.com"
SALES_STAGING_HOST = "salesxray-staging.authorityclosers.com"


class _CompletionIdentityApplication(_CallbackIdentityApplication):
    async def resolve_actor(self, token: str) -> ResolvedActorContext:
        session_id = (
            UUID("22222222-2222-4222-8222-222222222222")
            if token == VALID_SESSION_TOKEN
            else UUID("33333333-3333-4333-8333-333333333333")
        )
        return ResolvedActorContext(
            actor=ActorContext(
                person_id=UUID("11111111-1111-4111-8111-111111111111"),
                session_id=session_id,
                tenant_id=None,
            ),
            membership_role=None,
            person_revision=1,
            session_revision=1,
        )


class _ConsentConflictIdentityApplication(_IdentityApplication):
    async def register_verified_provider(self, *_args: Any, **_kwargs: Any) -> Any:
        raise ProviderConsentVersionConflictError("consent projection changed")


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
    return_path: str | None = None,
) -> tuple[Any, str]:
    return_path = return_path or f"/auth/complete?flow={uuid4()}"
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


def _completion_flow_id(transaction: AuthTransaction) -> UUID:
    return UUID(parse_qs(urlsplit(transaction.return_path).query)["flow"][0])


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
            "return_path": f"/auth/complete?flow={uuid4()}",
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

    async def append_audit(_repository, **_kwargs):
        return None

    monkeypatch.setattr(auth_module.AuditRepository, "append", append_audit)
    client = _client(settings=settings, provider=provider)
    started = client.get(
        "/v1/auth/google/start",
        params={
            "action": action,
            "surface": "sales_xray",
            "consent": "true",
            "age_attested": "true",
            "consent_version": settings.learner_consent_version,
            "return_path": f"/auth/complete?flow={uuid4()}",
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
    assert transaction.age_attested is True
    callback = client.get(
        "/v1/auth/google/callback",
        params={"state": transaction.state, "code": "google-authorization-code"},
        headers={"host": SALES_STAGING_HOST, "cookie": f"{DEPLOYMENT_OAUTH_COOKIE}={encoded}"},
        follow_redirects=False,
    )
    assert callback.status_code == 303
    assert callback.headers["location"] == (
        SALES_STAGING_ORIGIN
        + f"/auth/complete?flow={_completion_flow_id(transaction)}&auth_result=success"
    )
    assert selected == [(VALID_SESSION_TOKEN, settings.public_learner_tenant_id)]
    assert len(_IdentityApplication.registered_provider_calls) == 1
    assert _IdentityApplication.registered_provider_calls[0]["allow_consent_supersession"] is True
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


def test_sales_xray_partial_checkbox_cannot_upgrade_or_create_full_learner_consent() -> None:
    settings = _sales_staging_settings()
    client = _client(settings=settings, provider=_RecordingProvider())

    response = client.get(
        "/v1/auth/google/start",
        params={
            "action": "authenticate",
            "surface": "sales_xray",
            "consent": "true",
            "consent_version": settings.learner_consent_version,
            "return_path": f"/auth/complete?flow={uuid4()}",
        },
        headers={"host": SALES_STAGING_HOST},
        follow_redirects=False,
    )

    assert response.status_code == 303
    transaction = AuthTransactionCodec(settings.oauth_transaction_secret.get_secret_value()).decode(
        response.cookies[DEPLOYMENT_OAUTH_COOKIE]
    )
    assert transaction.authorization_type is ProviderAuthorizationType.AUTHENTICATE
    assert transaction.consent_version is None
    assert transaction.age_attested is False


def test_sales_xray_registration_rejects_old_partial_consent_form() -> None:
    settings = _sales_staging_settings()
    client = _client(settings=settings, provider=_RecordingProvider())

    response = client.get(
        "/v1/auth/google/start",
        params={
            "action": "register",
            "surface": "sales_xray",
            "consent": "true",
            "consent_version": settings.learner_consent_version,
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


def test_sales_google_callback_rejects_unsigned_full_ack_before_exchange():
    settings = _sales_staging_settings()
    provider = _SuccessfulProvider()
    transaction = AuthTransaction.issue(
        ProviderAuthorizationType.REGISTER,
        surface="sales_xray",
        return_path=f"/auth/complete?flow={uuid4()}",
        consent_version="staging-test-document-v1",
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
    assert callback.status_code == 303
    assert callback.headers["location"] == (
        SALES_STAGING_ORIGIN
        + f"/auth/complete?flow={_completion_flow_id(transaction)}&auth_result=failed"
    )
    assert provider.redirect_uris == []
    assert DEPLOYMENT_SESSION_COOKIE not in callback.cookies


def test_sales_google_callback_rechecks_full_acknowledgement_version_before_exchange():
    settings = _sales_staging_settings()
    provider = _SuccessfulProvider()
    transaction = AuthTransaction.issue(
        ProviderAuthorizationType.REGISTER,
        surface="sales_xray",
        return_path=f"/auth/complete?flow={uuid4()}",
        consent_version="superseded-version",
        age_attested=True,
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

    assert callback.status_code == 303
    assert callback.headers["location"] == (
        SALES_STAGING_ORIGIN
        + f"/auth/complete?flow={_completion_flow_id(transaction)}&auth_result=review_terms"
    )
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

    if callback_host == SALES_STAGING_HOST:
        assert response.status_code == 303
        assert response.headers["location"] == (
            SALES_STAGING_ORIGIN
            + f"/auth/complete?flow={_completion_flow_id(transaction)}&auth_result=failed"
        )
    else:
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
    assert response.headers["location"] == (
        f"{SALES_STAGING_ORIGIN}/auth/complete?flow={_completion_flow_id(transaction)}"
        "&auth_result=success"
    )
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
    completion_cookie = next(
        value.lower()
        for value in response.headers.get_list("set-cookie")
        if value.lower().startswith(f"{auth_module.SALES_XRAY_COMPLETION_COOKIE_NAME.lower()}=")
    )
    assert all(
        attribute in completion_cookie
        for attribute in ("secure", "httponly", "samesite=lax", "path=/", "max-age=180")
    )
    assert "domain=" not in completion_cookie


def test_sales_xray_completion_requires_the_matching_callback_flow_and_current_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(auth_module, "AsyncIdentityApplication", _CompletionIdentityApplication)
    client = _client(settings=_sales_staging_settings(), provider=_SuccessfulProvider())
    started, transaction = _sales_start(client)
    encoded = started.cookies[DEPLOYMENT_OAUTH_COOKIE]
    callback = client.get(
        "/v1/auth/google/callback",
        params={"state": transaction.state, "code": "google-authorization-code"},
        headers={"host": SALES_STAGING_HOST, "cookie": f"{DEPLOYMENT_OAUTH_COOKIE}={encoded}"},
        follow_redirects=False,
    )
    assert callback.status_code == 303
    receipt_cookie = callback.cookies[auth_module.SALES_XRAY_COMPLETION_COOKIE_NAME]
    matching_cookie_header = (
        f"{DEPLOYMENT_SESSION_COOKIE}={VALID_SESSION_TOKEN}; "
        f"{auth_module.SALES_XRAY_COMPLETION_COOKIE_NAME}={receipt_cookie}"
    )

    matched = client.post(
        "/v1/auth/google/completion",
        json={"flow_id": str(_completion_flow_id(transaction))},
        headers={
            "host": SALES_STAGING_HOST,
            "origin": SALES_STAGING_ORIGIN,
            "cookie": matching_cookie_header,
        },
    )
    other_flow = client.post(
        "/v1/auth/google/completion",
        json={"flow_id": str(uuid4())},
        headers={
            "host": SALES_STAGING_HOST,
            "origin": SALES_STAGING_ORIGIN,
            "cookie": matching_cookie_header,
        },
    )
    other_session = client.post(
        "/v1/auth/google/completion",
        json={"flow_id": str(_completion_flow_id(transaction))},
        headers={
            "host": SALES_STAGING_HOST,
            "origin": SALES_STAGING_ORIGIN,
            "cookie": (
                f"{DEPLOYMENT_SESSION_COOKIE}={SECOND_VALID_SESSION_TOKEN}; "
                f"{auth_module.SALES_XRAY_COMPLETION_COOKIE_NAME}={receipt_cookie}"
            ),
        },
    )

    assert matched.status_code == 200
    assert matched.json() == {"matched": True}
    assert matched.headers["cache-control"] == "private, no-store"
    assert other_flow.json() == {"matched": False}
    assert other_session.json() == {"matched": False}


def test_sales_xray_completion_rejects_missing_or_duplicated_receipt_cookie(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(auth_module, "AsyncIdentityApplication", _CompletionIdentityApplication)
    client = _client(settings=_sales_staging_settings(), provider=_SuccessfulProvider())
    flow_id = uuid4()
    headers = {
        "host": SALES_STAGING_HOST,
        "origin": SALES_STAGING_ORIGIN,
        "cookie": f"{DEPLOYMENT_SESSION_COOKIE}={VALID_SESSION_TOKEN}",
    }

    missing = client.post(
        "/v1/auth/google/completion",
        json={"flow_id": str(flow_id)},
        headers=headers,
    )
    duplicated = client.post(
        "/v1/auth/google/completion",
        json={"flow_id": str(flow_id)},
        headers={
            **headers,
            "cookie": (
                f"{DEPLOYMENT_SESSION_COOKIE}={VALID_SESSION_TOKEN}; "
                f"{auth_module.SALES_XRAY_COMPLETION_COOKIE_NAME}=not-a-receipt; "
                f"{auth_module.SALES_XRAY_COMPLETION_COOKIE_NAME}=not-a-receipt"
            ),
        },
    )

    assert missing.status_code == 200
    assert missing.json() == {"matched": False}
    assert duplicated.status_code == 200
    assert duplicated.json() == {"matched": False}


def test_sales_xray_callback_keeps_account_specific_consent_conflicts_generic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _sales_staging_settings()
    monkeypatch.setattr(
        auth_module, "AsyncIdentityApplication", _ConsentConflictIdentityApplication
    )
    transaction = AuthTransaction.issue(
        ProviderAuthorizationType.REGISTER,
        surface="sales_xray",
        return_path=f"/auth/complete?flow={uuid4()}",
        consent_version=settings.learner_consent_version,
        age_attested=True,
    )
    encoded = AuthTransactionCodec(settings.oauth_transaction_secret.get_secret_value()).encode(
        transaction
    )
    client = _client(settings=settings, provider=_SuccessfulProvider())
    callback = client.get(
        "/v1/auth/google/callback",
        params={"state": transaction.state, "code": "google-authorization-code"},
        headers={"host": SALES_STAGING_HOST, "cookie": f"{DEPLOYMENT_OAUTH_COOKIE}={encoded}"},
        follow_redirects=False,
    )

    assert callback.status_code == 303
    assert callback.headers["location"] == (
        SALES_STAGING_ORIGIN
        + f"/auth/complete?flow={_completion_flow_id(transaction)}&auth_result=failed"
    )
    assert DEPLOYMENT_SESSION_COOKIE not in callback.cookies
    assert auth_module.SALES_XRAY_COMPLETION_COOKIE_NAME not in callback.cookies


@pytest.mark.parametrize(
    ("audit_required", "provisioning_required"),
    [(True, True), (False, False)],
)
def test_email_login_audits_only_full_consent_that_establishes_eligibility(
    monkeypatch: pytest.MonkeyPatch,
    audit_required: bool,
    provisioning_required: bool,
) -> None:
    settings = _sales_staging_settings()
    consented_at = datetime.now(UTC)
    person = SimpleNamespace(
        id=UUID("11111111-1111-4111-8111-111111111111"),
        email="learner@example.test",
        first_name="Learner",
        display_name=None,
        consent_version=settings.learner_consent_version,
        consented_at=consented_at,
        email_verified_at=consented_at,
    )
    verified = SimpleNamespace(
        person=person,
        account_created=provisioning_required,
        learner_provisioning_required=provisioning_required,
        consent_audit_required=audit_required,
        previous_consent_version="older-version" if audit_required else None,
        previous_consented_at=consented_at if audit_required else None,
    )
    appended: list[dict[str, Any]] = []

    class _EmailAuditIdentityApplication(_IdentityApplication):
        async def issue_authenticated_session(self, person_id: UUID, **_kwargs: Any) -> Any:
            assert person_id == person.id
            return SimpleNamespace(
                token=VALID_SESSION_TOKEN,
                metadata=SimpleNamespace(id=UUID("22222222-2222-4222-8222-222222222222")),
            )

    class _EmailService:
        def __init__(self, *_args: Any, **_kwargs: Any) -> None:
            pass

        async def verify(self, **kwargs: Any) -> Any:
            assert kwargs["required_consent_version"] == settings.learner_consent_version
            return verified

    async def profile(_database: Any, *, person_id: UUID) -> Any:
        assert person_id == person.id
        return SimpleNamespace(profile_complete=False)

    async def append_audit(_repository: Any, **kwargs: Any) -> None:
        appended.append(kwargs)

    monkeypatch.setattr(auth_module, "AsyncIdentityApplication", _EmailAuditIdentityApplication)
    monkeypatch.setattr(auth_module, "EmailLoginCodeService", _EmailService)
    monkeypatch.setattr(auth_module, "get_sales_xray_profile", profile)
    monkeypatch.setattr(auth_module.AuditRepository, "append", append_audit)
    response = _client(settings=settings, provider=_SuccessfulProvider()).post(
        "/v1/auth/email-code/verify",
        headers={"host": SALES_STAGING_HOST, "origin": SALES_STAGING_ORIGIN},
        json={"email": "learner@example.test", "code": "123456", "surface": "sales_xray"},
    )

    assert response.status_code == 200
    assert response.json()["profile_complete"] is False
    if audit_required:
        assert len(appended) == 1
        assert appended[0]["payload"] == {
            "consent_version": settings.learner_consent_version,
            "previous_consent_version": "older-version",
            "previous_consented_at": consented_at.isoformat(),
            "explicit_acceptance": True,
            "age_attestation": "18_plus_learner_declaration",
            "accepted_via": "email_otp",
            "terms_path": "/terms",
            "privacy_path": "/privacy",
        }
        assert appended[0]["now"] == consented_at
    else:
        assert appended == []


@pytest.mark.parametrize(
    ("provider_factory", "expected_result"),
    [
        (_RejectedProvider, "failed"),
        (_UnavailableProvider, "unavailable"),
    ],
)
def test_sales_xray_google_callback_returns_only_bounded_provider_result(
    provider_factory,
    expected_result: str,
) -> None:
    settings = _sales_staging_settings()
    client = _client(settings=settings, provider=provider_factory())
    started, transaction = _sales_start(client)
    encoded = started.cookies[DEPLOYMENT_OAUTH_COOKIE]

    response = client.get(
        "/v1/auth/google/callback",
        params={"state": transaction.state, "code": "google-authorization-code"},
        headers={"host": SALES_STAGING_HOST, "cookie": f"{DEPLOYMENT_OAUTH_COOKIE}={encoded}"},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == (
        f"{SALES_STAGING_ORIGIN}/auth/complete?flow={_completion_flow_id(transaction)}"
        f"&auth_result={expected_result}"
    )
    assert DEPLOYMENT_SESSION_COOKIE not in response.cookies
    assert any(
        header.lower().startswith(f'{DEPLOYMENT_OAUTH_COOKIE.lower()}=""')
        for header in response.headers.get_list("set-cookie")
    )


def test_sales_xray_duplicate_callback_state_fails_without_clearing_other_tab_cookies() -> None:
    client = _client(settings=_sales_staging_settings(), provider=_SuccessfulProvider())
    started, transaction = _sales_start(client)
    encoded = started.cookies[DEPLOYMENT_OAUTH_COOKIE]

    response = client.get(
        "/v1/auth/google/callback",
        params=[
            ("state", transaction.state),
            ("state", "s" * 43),
            ("code", "google-authorization-code"),
        ],
        headers={"host": SALES_STAGING_HOST, "cookie": f"{DEPLOYMENT_OAUTH_COOKIE}={encoded}"},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == (
        SALES_STAGING_ORIGIN + "/auth/complete?auth_result=failed"
    )
    assert all(
        not header.lower().startswith(
            (DEPLOYMENT_OAUTH_COOKIE.lower(), "__host-ac_oauth_transaction.")
        )
        for header in response.headers.get_list("set-cookie")
    )


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
