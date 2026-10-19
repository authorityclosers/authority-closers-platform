"""Sales Xray sign-in with Facebook and Apple next to Google: routes, binding and outcomes."""

from __future__ import annotations

from typing import Any, cast
from urllib.parse import parse_qs, urlencode, urlsplit
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import ac_platform.http.auth as auth_module
from ac_platform.application.settings import Settings
from ac_platform.http.auth import install_identity_http
from ac_platform.http.auth_transactions import AuthTransaction, AuthTransactionCodec
from ac_platform.http.identity_provider import IdentityProviderEmailMissing
from ac_platform.http.problem import register_problem_handlers
from ac_platform.identity.application import ProviderEmailInUseError
from ac_platform.identity.services import VerifiedProviderAssertion
from tests.unit.http.test_auth_routes import (
    DEPLOYMENT_OAUTH_COOKIE,
    DEPLOYMENT_SESSION_COOKIE,
    _IdentityApplication,
    _LearnerProvisioningApplication,
    _RecordingProvider,
    _sessions,
    _SuccessfulProvider,
)
from tests.unit.http.test_sales_xray_auth import (
    SALES_STAGING_HOST,
    SALES_STAGING_ORIGIN,
    _completion_flow_id,
    _sales_staging_settings,
)

ISSUERS = {
    "google": "https://accounts.google.com",
    "facebook": "https://www.facebook.com",
    "apple": "https://appleid.apple.com",
}


class _Provider(_RecordingProvider):
    """A provider double that records what it was asked and returns one assertion."""

    def __init__(self, name: str, *, email: str = "person@example.com") -> None:
        self.name = name
        self.audience = f"{name}-client-id"
        self.email = email
        self.exchanges: list[dict[str, str]] = []

    async def exchange_code(
        self,
        code: str,
        transaction: AuthTransaction,
        *,
        callback_state: str,
        redirect_uri: str,
    ) -> VerifiedProviderAssertion:
        self.exchanges.append({"code": code, "redirect_uri": redirect_uri})
        return VerifiedProviderAssertion(
            issuer=ISSUERS[self.name],
            subject=f"{self.name}-subject",
            audience=self.audience,
            state=callback_state,
            nonce=transaction.nonce,
            authorization_type=transaction.authorization_type,
            email=self.email,
            email_verified=True,
        )


class _NoEmailProvider(_Provider):
    async def exchange_code(self, *args: Any, **kwargs: Any) -> VerifiedProviderAssertion:
        raise IdentityProviderEmailMissing("no email shared")


class _EmailInUseIdentityApplication(_IdentityApplication):
    async def register_verified_provider(self, *_args: Any, **_kwargs: Any) -> Any:
        raise ProviderEmailInUseError("the email belongs to an account it may not join")


@pytest.fixture(autouse=True)
def _quiet_side_effects(monkeypatch: pytest.MonkeyPatch) -> None:
    async def select_tenant(_identity: object, _token: str, _tenant_id: object) -> None:
        return None

    async def append_audit(_repository: object, **_kwargs: object) -> None:
        return None

    monkeypatch.setattr(auth_module, "AsyncIdentityApplication", _IdentityApplication)
    monkeypatch.setattr(
        auth_module, "AsyncLearnerProvisioningApplication", _LearnerProvisioningApplication
    )
    monkeypatch.setattr(_IdentityApplication, "select_tenant", select_tenant)
    monkeypatch.setattr(auth_module.AuditRepository, "append", append_audit)


def _client(
    *,
    google: object | None = None,
    extra: dict[str, object] | None = None,
    settings: Settings | None = None,
) -> TestClient:
    _IdentityApplication.reset_registered_provider_calls()
    application = FastAPI()
    register_problem_handlers(application)
    install_identity_http(
        application,
        settings=settings or _sales_staging_settings(),
        sessions=cast(Any, _sessions),
        provider=cast(Any, google if google is not None else _SuccessfulProvider()),
        extra_providers=cast(Any, extra or {}),
    )
    return TestClient(application)


def _start(client: TestClient, provider: str, **extra: str) -> Any:
    settings = _sales_staging_settings()
    return client.get(
        f"/v1/auth/{provider}/start",
        params={
            "action": "authenticate",
            "surface": "sales_xray",
            "consent": "true",
            "age_attested": "true",
            "consent_version": settings.learner_consent_version or "",
            "return_path": f"/auth/complete?flow={uuid4()}",
            **extra,
        },
        headers={"host": SALES_STAGING_HOST},
        follow_redirects=False,
    )


def _transaction(response: Any) -> tuple[AuthTransaction, str]:
    encoded = response.cookies[DEPLOYMENT_OAUTH_COOKIE]
    secret = _sales_staging_settings().oauth_transaction_secret.get_secret_value()
    return AuthTransactionCodec(secret).decode(encoded), encoded


def _callback(
    client: TestClient,
    provider: str,
    transaction: AuthTransaction,
    encoded: str,
    *,
    code: str = "provider-code",
) -> Any:
    return client.get(
        f"/v1/auth/{provider}/callback",
        params={"state": transaction.state, "code": code},
        headers={"host": SALES_STAGING_HOST, "cookie": f"{DEPLOYMENT_OAUTH_COOKIE}={encoded}"},
        follow_redirects=False,
    )


def _result(response: Any) -> str:
    assert response.status_code == 303
    return parse_qs(urlsplit(response.headers["location"]).query)["auth_result"][0]


def test_config_offers_each_provider_only_once_its_settings_exist() -> None:
    def flags(client: TestClient, surface: str = "sales_xray") -> tuple[bool, bool, bool]:
        body = client.get(
            "/v1/auth/email-code/config",
            params={"surface": surface},
            headers={"host": SALES_STAGING_HOST},
        ).json()
        return body["google_enabled"], body["apple_enabled"], body["facebook_enabled"]

    assert flags(_client()) == (True, False, False)
    both = _client(extra={"facebook": _Provider("facebook"), "apple": _Provider("apple")})
    assert flags(both) == (True, True, True)
    assert flags(_client(extra={"apple": _Provider("apple")})) == (True, True, False)


@pytest.mark.parametrize("provider", ["facebook", "apple"])
def test_start_is_unavailable_until_the_provider_is_configured(provider: str) -> None:
    response = _start(_client(), provider)
    assert response.status_code == 503
    assert DEPLOYMENT_OAUTH_COOKIE not in response.cookies


@pytest.mark.parametrize("provider", ["facebook", "apple"])
def test_start_binds_the_transaction_to_its_provider_and_own_callback(provider: str) -> None:
    double = _Provider(provider)
    response = _start(_client(extra={provider: double}), provider)
    assert response.status_code == 303
    location = parse_qs(urlsplit(response.headers["location"]).query)
    assert location["redirect_uri"] == [f"{SALES_STAGING_ORIGIN}/v1/auth/{provider}/callback"]
    transaction, _ = _transaction(response)
    assert transaction.provider == provider
    assert transaction.surface == "sales_xray"


@pytest.mark.parametrize("provider", ["facebook", "apple"])
def test_facebook_and_apple_are_sales_xray_only(provider: str) -> None:
    client = _client(extra={provider: _Provider(provider)})
    response = client.get(
        f"/v1/auth/{provider}/start",
        params={"action": "authenticate", "surface": "learner", "return_path": "/home"},
        headers={"host": SALES_STAGING_HOST},
        follow_redirects=False,
    )
    assert response.status_code == 422
    assert client.get("/v1/auth/twitter/start", follow_redirects=False).status_code in {404, 422}


def test_a_google_transaction_is_refused_at_the_facebook_callback() -> None:
    facebook = _Provider("facebook")
    client = _client(extra={"facebook": facebook})
    transaction, encoded = _transaction(_start(client, "google"))
    callback = _callback(client, "facebook", transaction, encoded)
    assert _result(callback) == "failed"
    assert facebook.exchanges == []
    assert _IdentityApplication.registered_provider_calls == []


@pytest.mark.parametrize(
    ("provider", "links_by_email"),
    [("google", True), ("apple", True), ("facebook", False)],
)
def test_only_providers_that_verify_email_may_link_an_existing_account(
    provider: str, links_by_email: bool
) -> None:
    double = _Provider(provider)
    client = _client(
        google=double if provider == "google" else None,
        extra={} if provider == "google" else {provider: double},
    )
    transaction, encoded = _transaction(_start(client, provider))
    if provider == "apple":
        callback = _apple_round_trip(client, transaction, encoded, code="provider-code")
    else:
        callback = _callback(client, provider, transaction, encoded)
    assert callback.headers["location"] == (
        SALES_STAGING_ORIGIN
        + f"/auth/complete?flow={_completion_flow_id(transaction)}&auth_result=success"
    )
    assert callback.cookies[DEPLOYMENT_SESSION_COOKIE]
    [call] = _IdentityApplication.registered_provider_calls
    assert call["link_existing_email"] is links_by_email
    assert double.exchanges == [
        {
            "code": "provider-code",
            "redirect_uri": f"{SALES_STAGING_ORIGIN}/v1/auth/{provider}/callback",
        }
    ]


def test_a_provider_without_an_email_reports_no_email() -> None:
    client = _client(extra={"facebook": _NoEmailProvider("facebook")})
    transaction, encoded = _transaction(_start(client, "facebook"))
    assert _result(_callback(client, "facebook", transaction, encoded)) == "no_email"


def test_an_email_that_may_not_be_linked_reports_account_exists(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(auth_module, "AsyncIdentityApplication", _EmailInUseIdentityApplication)
    client = _client(extra={"facebook": _Provider("facebook")})
    transaction, encoded = _transaction(_start(client, "facebook"))
    callback = _callback(client, "facebook", transaction, encoded)
    assert _result(callback) == "account_exists"
    assert DEPLOYMENT_SESSION_COOKIE not in callback.cookies


def test_facebook_cancel_is_a_plain_failure() -> None:
    facebook = _Provider("facebook")
    client = _client(extra={"facebook": facebook})
    transaction, encoded = _transaction(_start(client, "facebook"))
    callback = client.get(
        "/v1/auth/facebook/callback",
        params={
            "state": transaction.state,
            "error": "access_denied",
            "error_reason": "user_denied",
        },
        headers={"host": SALES_STAGING_HOST, "cookie": f"{DEPLOYMENT_OAUTH_COOKIE}={encoded}"},
        follow_redirects=False,
    )
    assert _result(callback) == "failed"
    assert facebook.exchanges == []


# ----- Apple form_post -----------------------------------------------------------


def _apple_post(client: TestClient, fields: dict[str, str]) -> Any:
    return client.post(
        "/v1/auth/apple/callback",
        content=urlencode(fields),
        headers={
            "host": SALES_STAGING_HOST,
            "content-type": "application/x-www-form-urlencoded",
            "origin": "https://appleid.apple.com",
        },
        follow_redirects=False,
    )


def _apple_round_trip(
    client: TestClient,
    transaction: AuthTransaction,
    encoded: str,
    *,
    code: str | None = None,
    error: str | None = None,
    user: str | None = None,
) -> Any:
    fields = {"state": transaction.state}
    if code is not None:
        fields["code"] = code
        fields["id_token"] = "header.claims.signature"  # noqa: S105 - ignored by the server
    if error is not None:
        fields["error"] = error
    if user is not None:
        fields["user"] = user
    posted = _apple_post(client, fields)
    assert posted.status_code == 303
    assert posted.headers["location"] == (
        f"{SALES_STAGING_ORIGIN}/v1/auth/apple/callback?" + urlencode({"state": transaction.state})
    )
    [(name, value)] = [
        (cookie_name, cookie_value)
        for cookie_name, cookie_value in posted.cookies.items()
        if "_apple." in cookie_name
    ]
    assert name.startswith(f"{DEPLOYMENT_OAUTH_COOKIE}_apple.")
    set_cookie = posted.headers["set-cookie"]
    assert "HttpOnly" in set_cookie and "Path=/" in set_cookie and "Max-Age=120" in set_cookie
    if code is not None:
        assert code not in value
    return client.get(
        "/v1/auth/apple/callback",
        params={"state": transaction.state},
        headers={
            "host": SALES_STAGING_HOST,
            "cookie": f"{DEPLOYMENT_OAUTH_COOKIE}={encoded}; {name}={value}",
        },
        follow_redirects=False,
    )


def test_apple_form_post_is_sealed_then_finished_by_the_same_site_get(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prefilled: list[str] = []

    async def empty_profile(_database: object, *, person_id: object) -> Any:
        del person_id
        return type("Profile", (), {"name": None, "phone_number_e164": None, "revision": 0})()

    async def save_profile(_database: object, **values: Any) -> None:
        prefilled.append(values["full_name"])

    monkeypatch.setattr(auth_module, "get_sales_xray_profile", empty_profile)
    monkeypatch.setattr(auth_module, "update_sales_xray_profile", save_profile)
    apple = _Provider("apple", email="x7k2@privaterelay.appleid.com")
    client = _client(extra={"apple": apple})
    transaction, encoded = _transaction(_start(client, "apple"))
    callback = _apple_round_trip(
        client,
        transaction,
        encoded,
        code="provider-code",
        user='{"name":{"firstName":"Asha","lastName":"Rao"},"email":"x7k2@privaterelay.appleid.com"}',
    )
    assert _result(callback) == "success"
    [call] = _IdentityApplication.registered_provider_calls
    assertion = cast(VerifiedProviderAssertion, call["assertion"])
    assert assertion.display_name == "Asha Rao"
    assert (assertion.given_name, assertion.family_name) == ("Asha", "Rao")
    assert assertion.email == "x7k2@privaterelay.appleid.com"
    # Apple's one-time name fills an empty Sales Xray profile name.
    assert prefilled == ["Asha Rao"]
    assert any(
        "_apple." in header and "Max-Age=0" in header
        for header in callback.headers.get_list("set-cookie")
    )


def test_apple_get_ignores_a_code_in_the_query_without_its_sealed_post() -> None:
    apple = _Provider("apple")
    client = _client(extra={"apple": apple})
    transaction, encoded = _transaction(_start(client, "apple"))
    callback = _callback(client, "apple", transaction, encoded, code="provider-code")
    assert _result(callback) == "failed"
    assert apple.exchanges == []


def test_apple_cancel_and_malformed_posts_fail_closed() -> None:
    apple = _Provider("apple")
    client = _client(extra={"apple": apple})
    transaction, encoded = _transaction(_start(client, "apple"))
    cancelled = _apple_round_trip(client, transaction, encoded, error="user_cancelled_authorize")
    assert _result(cancelled) == "failed"
    assert apple.exchanges == []
    for fields in (
        {"state": "short", "code": "c"},
        {"state": transaction.state},
        {"state": transaction.state, "code": "c", "error": "e"},
        {"state": transaction.state, "code": "c", "surprise": "x"},
    ):
        response = _apple_post(client, fields)
        assert _result(response) == "failed"
        assert not any("_apple." in name for name in response.cookies)
