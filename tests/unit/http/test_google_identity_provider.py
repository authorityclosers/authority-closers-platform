from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from time import time
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from google.auth import jwt
from google.auth.crypt import RSASigner

import ac_platform.http.identity_provider as identity_provider_module
from ac_platform.http.auth_transactions import AuthTransaction
from ac_platform.http.identity_provider import (
    GoogleOIDCProvider,
    IdentityProviderRejected,
    IdentityProviderUnavailable,
)
from ac_platform.identity.services import ProviderAuthorizationType

CLIENT_ID = "123456.apps.googleusercontent.com"
CLIENT_SECRET = "test-google-client-secret"  # noqa: S105
REDIRECT_URI = "https://api.authorityclosers.test/v1/auth/google/callback"
NOW = 1_788_055_200


@dataclass(frozen=True)
class _CertificateResponse:
    status: int
    data: bytes


class _CertificateRequest:
    def __init__(self, public_key: bytes) -> None:
        self._response = _CertificateResponse(
            status=200,
            data=json.dumps({"test-key": public_key.decode("ascii")}).encode("utf-8"),
        )

    def __call__(self, url: str, *, method: str) -> _CertificateResponse:
        assert url.startswith("https://www.googleapis.com/")
        assert method == "GET"
        return self._response


def _transaction() -> AuthTransaction:
    return AuthTransaction.issue(
        ProviderAuthorizationType.AUTHENTICATE,
        surface="learner",
        return_path="/home",
        now=NOW,
    )


def _claims(transaction: AuthTransaction, **overrides: Any) -> Mapping[str, Any]:
    return {
        "iss": "https://accounts.google.com",
        "sub": "google-subject-123",
        "aud": CLIENT_ID,
        "nonce": transaction.nonce,
        "email": "learner@authorityclosers.test",
        "email_verified": True,
        **overrides,
    }


def test_authorization_url_uses_code_flow_state_nonce_and_s256_without_secrets() -> None:
    transaction = _transaction()
    provider = GoogleOIDCProvider(client_id=CLIENT_ID, client_secret=CLIENT_SECRET)

    location = provider.authorization_url(transaction, redirect_uri=REDIRECT_URI)
    query = parse_qs(urlsplit(location).query)

    assert urlsplit(location).geturl().startswith(GoogleOIDCProvider.AUTHORIZATION_ENDPOINT)
    assert query["response_type"] == ["code"]
    assert query["scope"] == ["openid email profile"]
    assert query["state"] == [transaction.state]
    assert query["nonce"] == [transaction.nonce]
    assert query["code_challenge"] == [transaction.pkce_challenge]
    assert query["code_challenge_method"] == ["S256"]
    assert query["redirect_uri"] == [REDIRECT_URI]
    assert "hd" not in query
    assert CLIENT_SECRET not in location
    assert transaction.pkce_verifier not in location


@pytest.mark.asyncio
async def test_google_oidc_accepts_verified_accounts_outside_authority_closers_domain() -> None:
    transaction = _transaction()

    def exchange(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"id_token": "signed-google-id-token"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(exchange)) as client:
        provider = GoogleOIDCProvider(
            client_id=CLIENT_ID,
            client_secret=CLIENT_SECRET,
            http_client=client,
            token_verifier=lambda token, audience: _claims(
                transaction,
                email="eligible.user@gmail.com",
            ),
        )
        assertion = await provider.exchange_code(
            "authorization-code",
            transaction,
            callback_state=transaction.state,
            redirect_uri=REDIRECT_URI,
        )

    assert assertion.email == "eligible.user@gmail.com"
    assert assertion.email_verified is True


@pytest.mark.asyncio
async def test_code_exchange_keeps_provider_tokens_server_side_and_returns_verified_assertion() -> (
    None
):
    transaction = _transaction()
    observed_form: dict[str, list[str]] = {}

    def exchange(request: httpx.Request) -> httpx.Response:
        assert request.url == GoogleOIDCProvider.TOKEN_ENDPOINT
        observed_form.update(parse_qs(request.content.decode("ascii")))
        return httpx.Response(200, json={"id_token": "signed-google-id-token", "access_token": "x"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(exchange)) as client:
        provider = GoogleOIDCProvider(
            client_id=CLIENT_ID,
            client_secret=CLIENT_SECRET,
            http_client=client,
            token_verifier=lambda token, audience: _claims(transaction),
        )
        assertion = await provider.exchange_code(
            "authorization-code",
            transaction,
            callback_state=transaction.state,
            redirect_uri=REDIRECT_URI,
        )

    assert observed_form["client_secret"] == [CLIENT_SECRET]
    assert observed_form["code_verifier"] == [transaction.pkce_verifier]
    assert observed_form["redirect_uri"] == [REDIRECT_URI]
    assert assertion.subject == "google-subject-123"
    assert assertion.email_verified is True
    assert assertion.authorization_type is ProviderAuthorizationType.AUTHENTICATE
    assert assertion.replay_key is None


@pytest.mark.asyncio
async def test_callback_state_mismatch_is_rejected_before_network_access() -> None:
    called = False

    def exchange(request: httpx.Request) -> httpx.Response:
        nonlocal called
        called = True
        return httpx.Response(500)

    transaction = _transaction()
    async with httpx.AsyncClient(transport=httpx.MockTransport(exchange)) as client:
        provider = GoogleOIDCProvider(
            client_id=CLIENT_ID,
            client_secret=CLIENT_SECRET,
            http_client=client,
        )
        with pytest.raises(IdentityProviderRejected, match="state"):
            await provider.exchange_code(
                "authorization-code",
                transaction,
                callback_state="x" * 43,
                redirect_uri=REDIRECT_URI,
            )

    assert called is False


@pytest.mark.asyncio
async def test_verified_token_nonce_and_email_gate_fail_closed() -> None:
    transaction = _transaction()

    def exchange(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"id_token": "signed-google-id-token"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(exchange)) as client:
        provider = GoogleOIDCProvider(
            client_id=CLIENT_ID,
            client_secret=CLIENT_SECRET,
            http_client=client,
            token_verifier=lambda token, audience: _claims(
                transaction,
                nonce="wrong-nonce",
                email_verified=False,
            ),
        )
        with pytest.raises(IdentityProviderRejected, match="nonce"):
            await provider.exchange_code(
                "authorization-code",
                transaction,
                callback_state=transaction.state,
                redirect_uri=REDIRECT_URI,
            )


@pytest.mark.asyncio
@pytest.mark.parametrize("malformed_issuer", [None, 42, ["https://accounts.google.com"]])
async def test_malformed_issuer_claim_is_a_bounded_authentication_rejection(
    malformed_issuer: object,
) -> None:
    transaction = _transaction()

    def exchange(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"id_token": "signed-google-id-token"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(exchange)) as client:
        provider = GoogleOIDCProvider(
            client_id=CLIENT_ID,
            client_secret=CLIENT_SECRET,
            http_client=client,
            token_verifier=lambda token, audience: _claims(
                transaction,
                iss=malformed_issuer,
            ),
        )

        with pytest.raises(IdentityProviderRejected, match="issuer"):
            await provider.exchange_code(
                "authorization-code",
                transaction,
                callback_state=transaction.state,
                redirect_uri=REDIRECT_URI,
            )


@pytest.mark.asyncio
async def test_provider_server_error_is_unavailable_not_authentication_success() -> None:
    transaction = _transaction()

    def exchange(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"error": "temporarily_unavailable"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(exchange)) as client:
        provider = GoogleOIDCProvider(
            client_id=CLIENT_ID,
            client_secret=CLIENT_SECRET,
            http_client=client,
        )
        with pytest.raises(IdentityProviderUnavailable):
            await provider.exchange_code(
                "authorization-code",
                transaction,
                callback_state=transaction.state,
                redirect_uri=REDIRECT_URI,
            )


def test_pinned_google_auth_verifies_real_rsa_signature_audience_issuer_and_expiry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    private_key = rsa.generate_private_key(public_exponent=65_537, key_size=2048)
    private_pem = private_key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    public_pem = private_key.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    signer = RSASigner.from_string(  # type: ignore[no-untyped-call]
        private_pem,
        key_id="test-key",
    )
    now = int(time())

    def signed(expiry: int) -> str:
        encoded: bytes = jwt.encode(  # type: ignore[no-untyped-call]
            signer,
            {
                "iss": "https://accounts.google.com",
                "sub": "signed-subject",
                "aud": CLIENT_ID,
                "iat": now - 1,
                "exp": expiry,
                "nonce": "n" * 43,
                "email": "signed@authorityclosers.test",
                "email_verified": True,
            },
        )
        return encoded.decode("ascii")

    monkeypatch.setattr(
        identity_provider_module,
        "GoogleAuthRequest",
        lambda: _CertificateRequest(public_pem),
    )

    claims = identity_provider_module._verify_google_token(signed(now + 60), CLIENT_ID)
    assert claims["sub"] == "signed-subject"

    with pytest.raises(ValueError, match="Token expired"):
        identity_provider_module._verify_google_token(signed(now - 60), CLIENT_ID)

    token = signed(now + 60)
    header, payload, signature = token.split(".")
    replacement = "A" if signature[5] != "A" else "B"
    tampered = f"{header}.{payload}.{signature[:5]}{replacement}{signature[6:]}"
    with pytest.raises(ValueError, match="Could not verify token signature"):
        identity_provider_module._verify_google_token(tampered, CLIENT_ID)
