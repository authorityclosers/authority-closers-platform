"""Continue with Facebook and Sign in with Apple adapters, against recorded provider shapes."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import time
from collections.abc import Callable
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec, rsa
from google.auth import crypt as google_crypt
from google.auth import jwt as google_jwt

from ac_platform.http.auth_transactions import (
    AppleFormPostCodec,
    AuthTransaction,
    AuthTransactionCodec,
    InvalidAuthTransaction,
)
from ac_platform.http.identity_provider import (
    IdentityProviderEmailMissing,
    IdentityProviderRejected,
    IdentityProviderUnavailable,
)
from ac_platform.http.identity_provider_apple import (
    APPLE_ISSUER,
    AppleSignInProvider,
    apple_user_name,
    normalize_apple_private_key,
)
from ac_platform.http.identity_provider_facebook import FACEBOOK_ISSUER, FacebookLoginProvider
from ac_platform.identity.services import ProviderAuthorizationType

TRANSACTION_SECRET = "provider-adapter-test-transaction-secret-long-enough"  # noqa: S105
FACEBOOK_APP_ID = "1092841566696886"
FACEBOOK_SECRET = "facebook-app-secret-for-tests"  # noqa: S105
APPLE_SERVICE_ID = "com.example.salesxray.web"
APPLE_TEAM_ID = "ABCDE12345"
APPLE_KEY_ID = "KEY1234567"
REDIRECT = "https://salesxray.example.test/v1/auth/{provider}/callback"
NOW = 1_800_000_000
# google-auth checks identity-token times against the real clock.
TOKEN_NOW = int(time.time())


def _run[T](coroutine: Any) -> T:
    return asyncio.run(coroutine)


def _transaction(provider: str = "google") -> AuthTransaction:
    return AuthTransaction.issue(
        ProviderAuthorizationType.REGISTER,
        surface="sales_xray",
        return_path="/auth/complete?flow=7f2b0c1e-3a4d-4e5f-8a9b-0c1d2e3f4a5b",
        consent_version="test-consent-v1",
        age_attested=True,
        provider=provider,
    )


# ----- provider-bound transactions -----------------------------------------------


def test_transactions_carry_their_provider_and_google_keeps_its_exact_shape() -> None:
    codec = AuthTransactionCodec(TRANSACTION_SECRET)
    google = _transaction("google")
    encoded_google = codec.encode(google)
    payload = json.loads(base64.urlsafe_b64decode(encoded_google.split(".")[0] + "=="))
    assert "provider" not in payload
    assert codec.decode(encoded_google).provider == "google"
    for provider in ("facebook", "apple"):
        decoded = codec.decode(codec.encode(_transaction(provider)))
        assert decoded.provider == provider


def test_only_sales_xray_may_issue_facebook_or_apple_transactions() -> None:
    with pytest.raises(InvalidAuthTransaction):
        AuthTransaction.issue(
            ProviderAuthorizationType.AUTHENTICATE,
            surface="learner",
            return_path="/home",
            provider="facebook",
        )
    with pytest.raises(InvalidAuthTransaction):
        AuthTransaction.issue(
            ProviderAuthorizationType.AUTHENTICATE,
            surface="sales_xray",
            return_path="/auth/complete?flow=7f2b0c1e-3a4d-4e5f-8a9b-0c1d2e3f4a5b",
            provider="twitter",
        )


def test_apple_form_post_seal_is_private_bounded_and_expires() -> None:
    codec = AppleFormPostCodec(TRANSACTION_SECRET)
    sealed = codec.encode(
        state="s" * 43,
        code="apple-code",
        error=None,
        first_name="Asha",
        last_name="Rao",
        now=NOW,
    )
    assert "apple-code" not in sealed and "Asha" not in sealed
    opened = codec.decode(sealed, now=NOW + 60)
    assert (opened.state, opened.code, opened.first_name, opened.last_name) == (
        "s" * 43,
        "apple-code",
        "Asha",
        "Rao",
    )
    with pytest.raises(InvalidAuthTransaction):
        codec.decode(sealed, now=NOW + 121)
    with pytest.raises(InvalidAuthTransaction):
        AppleFormPostCodec("another-secret-that-is-also-long-enough-xx").decode(sealed, now=NOW)
    tampered = sealed[:-2] + ("A" if sealed[-2] != "A" else "B") + sealed[-1]
    with pytest.raises(InvalidAuthTransaction):
        codec.decode(tampered, now=NOW)


def test_apple_user_name_reads_only_the_first_sign_in_name() -> None:
    raw = json.dumps({"name": {"firstName": " Asha ", "lastName": "Rao"}, "email": "x@y.z"})
    assert apple_user_name(raw) == ("Asha", "Rao")
    assert apple_user_name(None) == (None, None)
    assert apple_user_name("not json") == (None, None)
    assert apple_user_name(json.dumps({"name": "Asha"})) == (None, None)
    assert apple_user_name("x" * 5000) == (None, None)


# ----- Facebook -----------------------------------------------------------------


def _facebook(handler: Callable[[httpx.Request], httpx.Response]) -> FacebookLoginProvider:
    return FacebookLoginProvider(
        app_id=FACEBOOK_APP_ID,
        app_secret=FACEBOOK_SECRET,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )


def _facebook_graph(
    *,
    token_status: int = 200,
    me_status: int = 200,
    me: dict[str, Any] | None = None,
    seen: list[httpx.Request] | None = None,
) -> Callable[[httpx.Request], httpx.Response]:
    profile = (
        me
        if me is not None
        else {
            "id": "10229876543210",
            "name": "Asha Rao",
            "first_name": "Asha",
            "last_name": "Rao",
            "email": "asha@example.com",
        }
    )

    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        if request.url.path.endswith("/oauth/access_token"):
            return httpx.Response(
                token_status,
                json={"access_token": "EAAG-test-token", "token_type": "bearer"},
            )
        if request.url.path.endswith("/me"):
            return httpx.Response(me_status, json=profile)
        return httpx.Response(404)

    return handler


def test_facebook_authorization_is_a_plain_redirect_with_pkce_and_email_scope() -> None:
    transaction = _transaction("facebook")
    url = _facebook(_facebook_graph()).authorization_url(
        transaction, redirect_uri=REDIRECT.format(provider="facebook")
    )
    parts = urlsplit(url)
    query = {key: values[0] for key, values in parse_qs(parts.query).items()}
    assert parts.netloc == "www.facebook.com"
    assert parts.path == "/v23.0/dialog/oauth"
    assert query["client_id"] == FACEBOOK_APP_ID
    assert query["scope"] == "public_profile,email"
    assert query["response_type"] == "code"
    assert query["state"] == transaction.state
    assert query["code_challenge"] == transaction.pkce_challenge
    assert query["code_challenge_method"] == "S256"
    assert query["redirect_uri"] == REDIRECT.format(provider="facebook")


def test_facebook_exchange_uses_the_secret_verifier_and_appsecret_proof() -> None:
    transaction = _transaction("facebook")
    seen: list[httpx.Request] = []
    assertion = _run(
        _facebook(_facebook_graph(seen=seen)).exchange_code(
            "facebook-code",
            transaction,
            callback_state=transaction.state,
            redirect_uri=REDIRECT.format(provider="facebook"),
        )
    )
    token_query = parse_qs(seen[0].url.query.decode())
    assert token_query["code_verifier"] == [transaction.pkce_verifier]
    assert token_query["client_secret"] == [FACEBOOK_SECRET]
    assert token_query["redirect_uri"] == [REDIRECT.format(provider="facebook")]
    me_query = parse_qs(seen[1].url.query.decode())
    expected_proof = hmac.new(
        FACEBOOK_SECRET.encode(), b"EAAG-test-token", hashlib.sha256
    ).hexdigest()
    assert me_query["appsecret_proof"] == [expected_proof]
    assert assertion.issuer == FACEBOOK_ISSUER
    assert assertion.subject == "10229876543210"
    assert assertion.audience == FACEBOOK_APP_ID
    assert assertion.email == "asha@example.com"
    assert assertion.display_name == "Asha Rao"
    assert (assertion.given_name, assertion.family_name) == ("Asha", "Rao")
    assert assertion.nonce == transaction.nonce


@pytest.mark.parametrize(
    "profile",
    [
        {"id": "10229876543210", "name": "Phone Only"},
        {"id": "10229876543210", "email": ""},
        {"id": "10229876543210", "email": "not-an-email"},
    ],
)
def test_facebook_without_an_email_is_a_distinct_rejection(profile: dict[str, Any]) -> None:
    transaction = _transaction("facebook")
    with pytest.raises(IdentityProviderEmailMissing):
        _run(
            _facebook(_facebook_graph(me=profile)).exchange_code(
                "facebook-code",
                transaction,
                callback_state=transaction.state,
                redirect_uri=REDIRECT.format(provider="facebook"),
            )
        )


@pytest.mark.parametrize(
    ("token_status", "me_status", "expected"),
    [
        (400, 200, IdentityProviderRejected),
        (503, 200, IdentityProviderUnavailable),
        (200, 401, IdentityProviderRejected),
        (200, 500, IdentityProviderUnavailable),
    ],
)
def test_facebook_errors_are_rejected_or_unavailable(
    token_status: int, me_status: int, expected: type[Exception]
) -> None:
    transaction = _transaction("facebook")
    with pytest.raises(expected):
        _run(
            _facebook(
                _facebook_graph(token_status=token_status, me_status=me_status)
            ).exchange_code(
                "facebook-code",
                transaction,
                callback_state=transaction.state,
                redirect_uri=REDIRECT.format(provider="facebook"),
            )
        )


def test_facebook_refuses_a_foreign_state_or_bad_person_id_before_trusting_anything() -> None:
    transaction = _transaction("facebook")
    seen: list[httpx.Request] = []
    with pytest.raises(IdentityProviderRejected):
        _run(
            _facebook(_facebook_graph(seen=seen)).exchange_code(
                "facebook-code",
                transaction,
                callback_state="x" * 43,
                redirect_uri=REDIRECT.format(provider="facebook"),
            )
        )
    assert seen == []
    with pytest.raises(IdentityProviderRejected):
        _run(
            _facebook(
                _facebook_graph(me={"id": "../me", "email": "asha@example.com"})
            ).exchange_code(
                "facebook-code",
                transaction,
                callback_state=transaction.state,
                redirect_uri=REDIRECT.format(provider="facebook"),
            )
        )


def test_facebook_settings_are_checked() -> None:
    with pytest.raises(ValueError):
        FacebookLoginProvider(app_id="not-numeric", app_secret=FACEBOOK_SECRET)
    with pytest.raises(ValueError):
        FacebookLoginProvider(app_id=FACEBOOK_APP_ID, app_secret="")
    with pytest.raises(ValueError):
        FacebookLoginProvider(
            app_id=FACEBOOK_APP_ID, app_secret=FACEBOOK_SECRET, graph_version="latest"
        )


# ----- Apple --------------------------------------------------------------------


def _ec_pem() -> str:
    key = ec.generate_private_key(ec.SECP256R1())
    return key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode("ascii")


EC_PEM = _ec_pem()
APPLE_RSA = rsa.generate_private_key(public_exponent=65537, key_size=2048)
APPLE_RSA_PEM = APPLE_RSA.private_bytes(
    serialization.Encoding.PEM,
    serialization.PrivateFormat.PKCS8,
    serialization.NoEncryption(),
).decode("ascii")
APPLE_KID = "apple-test-kid"


def _b64(value: int) -> str:
    raw = value.to_bytes((value.bit_length() + 7) // 8, "big")
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _jwks() -> dict[str, Any]:
    numbers = APPLE_RSA.public_key().public_numbers()
    return {
        "keys": [
            {
                "kty": "RSA",
                "kid": APPLE_KID,
                "use": "sig",
                "alg": "RS256",
                "n": _b64(numbers.n),
                "e": _b64(numbers.e),
            }
        ]
    }


def _id_token(transaction: AuthTransaction, **overrides: Any) -> str:
    claims: dict[str, Any] = {
        "iss": APPLE_ISSUER,
        "aud": APPLE_SERVICE_ID,
        "sub": "001234.abcdef0123456789.0123",
        "iat": TOKEN_NOW,
        "exp": TOKEN_NOW + 600,
        "nonce": transaction.nonce,
        "nonce_supported": True,
        "email": "x7k2@privaterelay.appleid.com",
        "email_verified": "true",
        "is_private_email": "true",
    }
    claims.update(overrides)
    for key in [name for name, value in claims.items() if value is None]:
        del claims[key]
    signer = google_crypt.RSASigner.from_string(APPLE_RSA_PEM, APPLE_KID)
    token = google_jwt.encode(signer, claims, key_id=APPLE_KID)  # type: ignore[no-untyped-call]
    return token.decode("ascii") if isinstance(token, bytes) else str(token)


def _apple(
    handler: Callable[[httpx.Request], httpx.Response],
    *,
    now: float = NOW + 5,
) -> AppleSignInProvider:
    return AppleSignInProvider(
        service_id=APPLE_SERVICE_ID,
        team_id=APPLE_TEAM_ID,
        key_id=APPLE_KEY_ID,
        private_key=EC_PEM,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        clock=lambda: now,
    )


def _apple_endpoints(
    id_token: str | None,
    *,
    token_status: int = 200,
    seen: list[httpx.Request] | None = None,
) -> Callable[[httpx.Request], httpx.Response]:
    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        if request.url.path == "/auth/keys":
            return httpx.Response(200, json=_jwks())
        if request.url.path == "/auth/token":
            body = {"access_token": "a", "token_type": "Bearer", "id_token": id_token}
            return httpx.Response(token_status, json=body)
        return httpx.Response(404)

    return handler


def test_apple_authorization_asks_for_name_and_email_by_form_post() -> None:
    transaction = _transaction("apple")
    url = _apple(_apple_endpoints(None)).authorization_url(
        transaction, redirect_uri=REDIRECT.format(provider="apple")
    )
    parts = urlsplit(url)
    query = {key: values[0] for key, values in parse_qs(parts.query).items()}
    assert parts.netloc == "appleid.apple.com" and parts.path == "/auth/authorize"
    assert query["response_mode"] == "form_post"
    assert query["scope"] == "name email"
    assert query["client_id"] == APPLE_SERVICE_ID
    assert query["state"] == transaction.state
    assert query["nonce"] == transaction.nonce


def test_apple_client_secret_is_a_short_es256_token_for_this_services_id() -> None:
    provider = _apple(_apple_endpoints(None))
    secret = provider.client_secret()
    header = google_jwt.decode_header(secret)  # type: ignore[no-untyped-call]
    assert header["alg"] == "ES256" and header["kid"] == APPLE_KEY_ID
    public_pem = (
        serialization.load_pem_private_key(EC_PEM.encode(), password=None)
        .public_key()
        .public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
        .decode("ascii")
    )
    claims = google_jwt.decode(  # type: ignore[no-untyped-call]
        secret, certs=public_pem, audience=APPLE_ISSUER, verify=False
    )
    assert claims["iss"] == APPLE_TEAM_ID
    assert claims["sub"] == APPLE_SERVICE_ID
    assert claims["exp"] - claims["iat"] == 300
    signature_ok = google_crypt.es256.ES256Verifier.from_string(public_pem).verify(
        secret.rsplit(".", 1)[0].encode(),
        base64.urlsafe_b64decode(secret.rsplit(".", 1)[1] + "=="),
    )
    assert signature_ok


def test_apple_exchange_verifies_the_identity_token_and_accepts_a_private_relay_email() -> None:
    transaction = _transaction("apple")
    seen: list[httpx.Request] = []
    assertion = _run(
        _apple(_apple_endpoints(_id_token(transaction), seen=seen)).exchange_code(
            "apple-code",
            transaction,
            callback_state=transaction.state,
            redirect_uri=REDIRECT.format(provider="apple"),
        )
    )
    token_form = parse_qs(seen[0].content.decode())
    assert token_form["grant_type"] == ["authorization_code"]
    assert token_form["redirect_uri"] == [REDIRECT.format(provider="apple")]
    assert token_form["client_id"] == [APPLE_SERVICE_ID]
    assert assertion.issuer == APPLE_ISSUER
    assert assertion.subject == "001234.abcdef0123456789.0123"
    assert assertion.email == "x7k2@privaterelay.appleid.com"
    assert assertion.email_verified is True


@pytest.mark.parametrize(
    "overrides",
    [
        {"aud": "com.someone.else"},
        {"iss": "https://appleid.example.test"},
        {"nonce": "n" * 43},
        {"nonce": None},
        {"exp": TOKEN_NOW - 120, "iat": TOKEN_NOW - 900},
    ],
)
def test_apple_refuses_a_token_for_another_audience_issuer_nonce_or_time(
    overrides: dict[str, Any],
) -> None:
    transaction = _transaction("apple")
    with pytest.raises(IdentityProviderRejected):
        _run(
            _apple(_apple_endpoints(_id_token(transaction, **overrides))).exchange_code(
                "apple-code",
                transaction,
                callback_state=transaction.state,
                redirect_uri=REDIRECT.format(provider="apple"),
            )
        )


def test_apple_refuses_a_token_signed_by_anyone_else() -> None:
    transaction = _transaction("apple")
    other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    other_pem = other.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode("ascii")
    claims = {
        "iss": APPLE_ISSUER,
        "aud": APPLE_SERVICE_ID,
        "sub": "forged",
        "iat": TOKEN_NOW,
        "exp": TOKEN_NOW + 600,
        "nonce": transaction.nonce,
        "email": "victim@example.com",
        "email_verified": "true",
    }
    forged = google_jwt.encode(  # type: ignore[no-untyped-call]
        google_crypt.RSASigner.from_string(other_pem, APPLE_KID), claims, key_id=APPLE_KID
    )
    with pytest.raises(IdentityProviderRejected):
        _run(
            _apple(_apple_endpoints(forged.decode("ascii"))).exchange_code(
                "apple-code",
                transaction,
                callback_state=transaction.state,
                redirect_uri=REDIRECT.format(provider="apple"),
            )
        )


@pytest.mark.parametrize(
    "overrides",
    [{"email": None}, {"email_verified": "false"}, {"email_verified": None}],
)
def test_apple_without_a_verified_email_is_a_distinct_rejection(
    overrides: dict[str, Any],
) -> None:
    transaction = _transaction("apple")
    with pytest.raises(IdentityProviderEmailMissing):
        _run(
            _apple(_apple_endpoints(_id_token(transaction, **overrides))).exchange_code(
                "apple-code",
                transaction,
                callback_state=transaction.state,
                redirect_uri=REDIRECT.format(provider="apple"),
            )
        )


@pytest.mark.parametrize(
    ("status", "expected"), [(400, IdentityProviderRejected), (502, IdentityProviderUnavailable)]
)
def test_apple_token_errors(status: int, expected: type[Exception]) -> None:
    transaction = _transaction("apple")
    with pytest.raises(expected):
        _run(
            _apple(_apple_endpoints(None, token_status=status)).exchange_code(
                "apple-code",
                transaction,
                callback_state=transaction.state,
                redirect_uri=REDIRECT.format(provider="apple"),
            )
        )


def test_apple_private_key_accepts_the_p8_file_escaped_or_base64() -> None:
    escaped = EC_PEM.replace("\n", "\\n")
    as_base64 = base64.b64encode(EC_PEM.encode()).decode()
    der = serialization.load_pem_private_key(EC_PEM.encode(), password=None).private_bytes(
        serialization.Encoding.DER,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    for value in (EC_PEM, escaped, as_base64, base64.b64encode(der).decode()):
        assert "BEGIN PRIVATE KEY" in normalize_apple_private_key(value)
    with pytest.raises(ValueError):
        normalize_apple_private_key("not a key!")
    with pytest.raises(ValueError):
        AppleSignInProvider(
            service_id=APPLE_SERVICE_ID, team_id="short", key_id=APPLE_KEY_ID, private_key=EC_PEM
        )
