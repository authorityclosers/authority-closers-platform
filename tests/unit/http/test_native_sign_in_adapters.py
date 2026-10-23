"""Sign-in inside the Android app (owner, 23 Oct 2026): the tokens the phone's own
Google account sheet and the Facebook SDK hand over are checked like the web flow's."""

from __future__ import annotations

import hashlib
import hmac
from collections.abc import Callable, Mapping
from typing import Any
from urllib.parse import parse_qs

import httpx
import pytest

from ac_platform.http.identity_provider import (
    GoogleOIDCProvider,
    IdentityProviderEmailMissing,
    IdentityProviderRejected,
    IdentityProviderUnavailable,
)
from ac_platform.http.identity_provider_facebook import FACEBOOK_ISSUER
from tests.unit.http.test_sign_in_provider_adapters import (
    FACEBOOK_APP_ID,
    FACEBOOK_SECRET,
    _facebook,
    _run,
    _transaction,
)

GOOGLE_CLIENT_ID = "1234567890-native.apps.googleusercontent.com"
FACEBOOK_TOKEN = "EAAG-native-user-token"  # noqa: S105
PERSON = "10229876543210"


def _google(
    claims: Mapping[str, Any] | Exception, seen: list[tuple[str, str]] | None = None
) -> GoogleOIDCProvider:
    def verifier(token: str, audience: str) -> Mapping[str, Any]:
        if seen is not None:
            seen.append((token, audience))
        if isinstance(claims, Exception):
            raise claims
        return claims

    return GoogleOIDCProvider(
        client_id=GOOGLE_CLIENT_ID,
        client_secret="google-secret-for-tests",  # noqa: S106
        token_verifier=verifier,
    )


def _claims(nonce: str, /, **overrides: Any) -> dict[str, Any]:
    claims: dict[str, Any] = {
        "iss": "https://accounts.google.com",
        "sub": "google-native-subject",
        "aud": GOOGLE_CLIENT_ID,
        # Credential Manager tokens name the Android client as the party they went to.
        "azp": "1234567890-android.apps.googleusercontent.com",
        "nonce": nonce,
        "email": "asha@example.com",
        "email_verified": True,
        "name": "Asha Rao",
    }
    claims.update(overrides)
    return claims


def test_a_google_id_token_from_the_phone_is_verified_for_our_web_client_and_nonce() -> None:
    transaction = _transaction("google")
    seen: list[tuple[str, str]] = []
    assertion = _run(
        _google(_claims(transaction.nonce), seen).verify_native_token(
            "header.payload.signature", transaction, callback_state=transaction.state
        )
    )
    assert seen == [("header.payload.signature", GOOGLE_CLIENT_ID)]
    assert (assertion.issuer, assertion.subject) == (
        "https://accounts.google.com",
        "google-native-subject",
    )
    assert assertion.audience == GOOGLE_CLIENT_ID
    assert assertion.nonce == transaction.nonce
    assert assertion.email == "asha@example.com"
    assert assertion.email_verified is True
    assert assertion.authorization_type is transaction.authorization_type


@pytest.mark.parametrize(
    "overrides",
    [
        {"nonce": "a-nonce-from-another-sign-in"},
        {"aud": "someone-else.apps.googleusercontent.com"},
        {"iss": "https://evil.example.test"},
        {"email_verified": False},
        {"email": ""},
    ],
)
def test_a_google_token_with_the_wrong_nonce_audience_issuer_or_email_is_refused(
    overrides: dict[str, Any],
) -> None:
    transaction = _transaction("google")
    with pytest.raises(IdentityProviderRejected):
        _run(
            _google(_claims(transaction.nonce, **overrides)).verify_native_token(
                "header.payload.signature", transaction, callback_state=transaction.state
            )
        )


def test_a_google_token_is_refused_for_another_state_or_when_malformed_or_unsigned() -> None:
    transaction = _transaction("google")
    google = _google(_claims(transaction.nonce))
    for token, state in (
        ("header.payload.signature", "another-state-value-that-is-long-enough-000"),
        ("", transaction.state),
        ("x" * 16_385, transaction.state),
        ("héader.payload.signature", transaction.state),
    ):
        with pytest.raises(IdentityProviderRejected):
            _run(google.verify_native_token(token, transaction, callback_state=state))
    with pytest.raises(IdentityProviderRejected):
        _run(
            _google(ValueError("bad signature")).verify_native_token(
                "header.payload.signature", transaction, callback_state=transaction.state
            )
        )


def _facebook_native_graph(
    *,
    debug: dict[str, Any] | None = None,
    debug_status: int = 200,
    me: dict[str, Any] | None = None,
    seen: list[httpx.Request] | None = None,
) -> Callable[[httpx.Request], httpx.Response]:
    token_data = (
        debug
        if debug is not None
        else {"app_id": FACEBOOK_APP_ID, "type": "USER", "is_valid": True, "user_id": PERSON}
    )
    profile = (
        me if me is not None else {"id": PERSON, "name": "Asha Rao", "email": "asha@example.com"}
    )

    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        if request.url.path.endswith("/debug_token"):
            return httpx.Response(debug_status, json={"data": token_data})
        if request.url.path.endswith("/me"):
            return httpx.Response(200, json=profile)
        return httpx.Response(404)

    return handler


def test_a_facebook_token_counts_only_after_facebook_says_it_is_ours() -> None:
    transaction = _transaction("facebook")
    seen: list[httpx.Request] = []
    assertion = _run(
        _facebook(_facebook_native_graph(seen=seen)).verify_native_token(
            FACEBOOK_TOKEN, transaction, callback_state=transaction.state
        )
    )
    debug_query = parse_qs(seen[0].url.query.decode())
    assert seen[0].url.path == "/v23.0/debug_token"
    assert debug_query["input_token"] == [FACEBOOK_TOKEN]
    assert debug_query["access_token"] == [f"{FACEBOOK_APP_ID}|{FACEBOOK_SECRET}"]
    me_query = parse_qs(seen[1].url.query.decode())
    assert me_query["appsecret_proof"] == [
        hmac.new(FACEBOOK_SECRET.encode(), FACEBOOK_TOKEN.encode(), hashlib.sha256).hexdigest()
    ]
    assert (assertion.issuer, assertion.subject) == (FACEBOOK_ISSUER, PERSON)
    assert assertion.audience == FACEBOOK_APP_ID
    assert assertion.email == "asha@example.com"
    assert assertion.nonce == transaction.nonce


@pytest.mark.parametrize(
    "debug",
    [
        {"app_id": "999999999999", "type": "USER", "is_valid": True, "user_id": PERSON},
        {"app_id": FACEBOOK_APP_ID, "type": "USER", "is_valid": False, "user_id": PERSON},
        {"app_id": FACEBOOK_APP_ID, "type": "PAGE", "is_valid": True, "user_id": PERSON},
        {"app_id": FACEBOOK_APP_ID, "type": "USER", "is_valid": True},
    ],
)
def test_a_facebook_token_for_another_app_expired_or_not_a_person_is_refused_before_reading(
    debug: dict[str, Any],
) -> None:
    transaction = _transaction("facebook")
    seen: list[httpx.Request] = []
    with pytest.raises(IdentityProviderRejected):
        _run(
            _facebook(_facebook_native_graph(debug=debug, seen=seen)).verify_native_token(
                FACEBOOK_TOKEN, transaction, callback_state=transaction.state
            )
        )
    assert [request.url.path for request in seen] == ["/v23.0/debug_token"]


def test_a_facebook_token_whose_profile_is_someone_else_or_has_no_email_is_refused() -> None:
    transaction = _transaction("facebook")
    with pytest.raises(IdentityProviderRejected):
        _run(
            _facebook(
                _facebook_native_graph(me={"id": "777", "email": "x@example.com"})
            ).verify_native_token(FACEBOOK_TOKEN, transaction, callback_state=transaction.state)
        )
    with pytest.raises(IdentityProviderEmailMissing):
        _run(
            _facebook(_facebook_native_graph(me={"id": PERSON})).verify_native_token(
                FACEBOOK_TOKEN, transaction, callback_state=transaction.state
            )
        )


def test_facebook_token_check_errors_and_a_foreign_state() -> None:
    transaction = _transaction("facebook")
    with pytest.raises(IdentityProviderUnavailable):
        _run(
            _facebook(_facebook_native_graph(debug_status=503)).verify_native_token(
                FACEBOOK_TOKEN, transaction, callback_state=transaction.state
            )
        )
    with pytest.raises(IdentityProviderRejected):
        _run(
            _facebook(_facebook_native_graph(debug_status=400)).verify_native_token(
                FACEBOOK_TOKEN, transaction, callback_state=transaction.state
            )
        )
    seen: list[httpx.Request] = []
    with pytest.raises(IdentityProviderRejected):
        _run(
            _facebook(_facebook_native_graph(seen=seen)).verify_native_token(
                FACEBOOK_TOKEN,
                transaction,
                callback_state="another-state-value-that-is-long-enough-000",
            )
        )
    assert seen == []
