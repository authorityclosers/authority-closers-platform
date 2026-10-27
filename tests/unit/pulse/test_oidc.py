"""Sign in with Pulse's OpenID Connect adapter against a fictional Pulse (no network).

Discovery is read once and its issuer must be the configured one; the authorize address
carries PKCE S256, state and nonce; the code is swapped with HTTP Basic client auth; the
ID token is checked against the published keys (RS256 and ES256), issuer, audience,
expiry and nonce; a sign-in without a verified email is refused; userinfo adds the
title, team and orgs, never another person; the profile claims wait for the profile step.
"""

from __future__ import annotations

import base64
import json
import time
from typing import Any
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import httpx
import pytest
from cryptography.hazmat.primitives.asymmetric import ec, rsa
from google.auth import crypt
from google.auth import jwt as google_jwt

from ac_platform.http.auth_transactions import AuthTransaction
from ac_platform.http.identity_provider import (
    IdentityProviderEmailMissing,
    IdentityProviderRejected,
    IdentityProviderUnavailable,
)
from ac_platform.identity.services import ProviderAuthorizationType
from ac_platform.pulse.oidc import (
    PulseClaims,
    PulseClient,
    PulseSignInProvider,
    normalize_issuer,
)

ISSUER = "https://pulse.example.test"
CLIENT_ID = "sales-xray-test"
SECRET = "fictional-client-secret-0000"  # noqa: S105 - a test value


def _b64(number: int) -> str:
    raw = number.to_bytes((number.bit_length() + 7) // 8, "big")
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


class FakePulse:
    """A fictional Pulse: discovery, JWKS, token and userinfo."""

    def __init__(self, *, algorithm: str = "RS256") -> None:
        self.algorithm = algorithm
        if algorithm == "RS256":
            key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
            numbers = key.public_key().public_numbers()
            self.jwk: dict[str, Any] = {
                "kty": "RSA",
                "kid": "k1",
                "alg": "RS256",
                "use": "sig",
                "n": _b64(numbers.n),
                "e": _b64(numbers.e),
            }
            self.signer: Any = crypt.RSASigner.from_string(_pem(key), "k1")
        else:
            ec_key = ec.generate_private_key(ec.SECP256R1())
            point = ec_key.public_key().public_numbers()
            self.jwk = {
                "kty": "EC",
                "kid": "k1",
                "alg": "ES256",
                "crv": "P-256",
                "x": _b64(point.x),
                "y": _b64(point.y),
            }
            from google.auth.crypt import es256

            self.signer = es256.ES256Signer.from_string(_pem(ec_key), "k1")
        self.claims: dict[str, Any] = {}
        self.userinfo: dict[str, Any] = {}
        self.issuer_stated = ISSUER
        self.token_requests: list[httpx.Request] = []
        self.revoked: list[str] = []
        self.discovery_reads = 0
        self.token_status = 200

    def id_token(self, **over: Any) -> str:
        now = int(time.time())
        claims = {
            "iss": ISSUER,
            "aud": CLIENT_ID,
            "sub": "pulse-person-1",
            "iat": now,
            "exp": now + 300,
            "nonce": "n",
            "email": "kiran.mehta@example.test",
            "email_verified": True,
            "name": "Kiran Mehta",
            **self.claims,
            **over,
        }
        token = google_jwt.encode(self.signer, claims, key_id="k1")
        return token.decode() if isinstance(token, bytes) else str(token)

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/.well-known/openid-configuration":
            self.discovery_reads += 1
            return httpx.Response(
                200,
                json={
                    "issuer": self.issuer_stated,
                    "authorization_endpoint": f"{ISSUER}/oauth/authorize",
                    "token_endpoint": f"{ISSUER}/oauth/token",
                    "userinfo_endpoint": f"{ISSUER}/oauth/userinfo",
                    "jwks_uri": f"{ISSUER}/oauth/jwks",
                    "revocation_endpoint": f"{ISSUER}/oauth/revoke",
                    "code_challenge_methods_supported": ["S256"],
                    "token_endpoint_auth_methods_supported": ["client_secret_basic"],
                },
            )
        if path == "/oauth/jwks":
            return httpx.Response(200, json={"keys": [self.jwk]})
        if path == "/oauth/token":
            self.token_requests.append(request)
            if self.token_status != 200:
                return httpx.Response(self.token_status, json={"error": "invalid_grant"})
            form = parse_qs(request.content.decode())
            nonce = self.claims.get("nonce", "n")
            return httpx.Response(
                200,
                json={
                    "access_token": "at-1",
                    "token_type": "Bearer",
                    "expires_in": 300,
                    "id_token": self.id_token(nonce=nonce),
                    "scope": "openid profile email pulse.orgs",
                    "_code": form.get("code", [""])[0],
                },
            )
        if path == "/oauth/userinfo":
            return httpx.Response(200, json=self.userinfo)
        if path == "/oauth/revoke":
            self.revoked.append(parse_qs(request.content.decode())["token"][0])
            return httpx.Response(200)
        return httpx.Response(404)


def _pem(key: Any) -> str:
    from cryptography.hazmat.primitives import serialization

    return key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()


def _provider(pulse: FakePulse) -> PulseSignInProvider:
    client = PulseClient(
        issuer=ISSUER,
        client_id=CLIENT_ID,
        client_secret=SECRET,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(pulse.handler)),
    )
    return PulseSignInProvider(client)


def _transaction(nonce: str = "n") -> AuthTransaction:
    return AuthTransaction(
        transaction_id=uuid4(),
        state="s" * 43,
        nonce=nonce,
        pkce_verifier="v" * 64,
        authorization_type=ProviderAuthorizationType.AUTHENTICATE,
        surface="sales_xray",
        return_path="/auth/complete?flow=00000000-0000-4000-8000-000000000000",
        issued_at=int(time.time()),
        provider="pulse",
    )


@pytest.mark.parametrize("algorithm", ["RS256", "ES256"])
async def test_a_pulse_sign_in_becomes_a_verified_assertion(algorithm: str) -> None:
    pulse = FakePulse(algorithm=algorithm)
    pulse.userinfo = {
        "sub": "pulse-person-1",
        "title": "Sales manager",
        "team": "Inside sales",
        "picture": f"{ISSUER}/people/pulse-person-1/photo?v=3f9c",
        "pulse_orgs": [{"id": "org-1", "name": "Greenleaf Realty (test)", "role": "admin"}],
    }
    provider = _provider(pulse)
    with pytest.raises(IdentityProviderUnavailable):
        provider.authorization_url(_transaction(), redirect_uri="https://sx.test/cb")
    await provider.prepare()
    address = urlsplit(
        provider.authorization_url(_transaction(), redirect_uri="https://sx.test/cb")
    )
    asked = parse_qs(address.query)
    assert f"{address.scheme}://{address.netloc}{address.path}" == f"{ISSUER}/oauth/authorize"
    assert asked["scope"] == ["openid profile email pulse.orgs"]
    assert asked["code_challenge_method"] == ["S256"]
    assert asked["state"] == ["s" * 43] and asked["nonce"] == ["n"]

    assertion = await provider.exchange_code(
        "code-1", _transaction(), callback_state="s" * 43, redirect_uri="https://sx.test/cb"
    )
    assert (assertion.issuer, assertion.subject) == (ISSUER, "pulse-person-1")
    assert assertion.email == "kiran.mehta@example.test" and assertion.email_verified
    assert assertion.display_name == "Kiran Mehta"
    [token] = pulse.token_requests
    expected = base64.b64encode(f"{CLIENT_ID}:{SECRET}".encode()).decode()
    assert token.headers["authorization"] == f"Basic {expected}"
    form = parse_qs(token.content.decode())
    assert form["code_verifier"] == ["v" * 64] and "client_secret" not in form
    # Sign-in keeps no Pulse token: the access token is given back at once.
    assert pulse.revoked == ["at-1"]
    claims = provider.claims_for("s" * 43)
    assert claims is not None
    assert (claims.title, claims.team) == ("Sales manager", "Inside sales")
    assert claims.orgs[0].role == "admin"
    assert provider.claims_for("s" * 43) is None  # taken once
    assert pulse.discovery_reads == 1


@pytest.mark.parametrize(
    ("over", "why"),
    [
        ({"iss": "https://evil.example.test"}, "issuer"),
        ({"aud": "someone-else"}, "audience"),
        ({"nonce": "other"}, "nonce"),
        ({"exp": int(time.time()) - 600, "iat": int(time.time()) - 900}, "expired"),
    ],
)
async def test_an_id_token_that_is_not_for_this_sign_in_is_refused(
    over: dict[str, Any], why: str
) -> None:
    pulse = FakePulse()
    pulse.claims = over
    provider = _provider(pulse)
    await provider.prepare()
    with pytest.raises(IdentityProviderRejected):
        await provider.exchange_code(
            "code", _transaction(), callback_state="s" * 43, redirect_uri="https://sx.test/cb"
        )
    del why


async def test_an_unverified_email_is_no_sign_in() -> None:
    pulse = FakePulse()
    pulse.claims = {"email_verified": False}
    provider = _provider(pulse)
    await provider.prepare()
    with pytest.raises(IdentityProviderEmailMissing):
        await provider.exchange_code(
            "code", _transaction(), callback_state="s" * 43, redirect_uri="https://sx.test/cb"
        )


async def test_userinfo_never_speaks_for_another_person() -> None:
    pulse = FakePulse()
    pulse.userinfo = {"sub": "someone-else", "title": "Owner", "email": "x@example.test"}
    provider = _provider(pulse)
    await provider.prepare()
    assertion = await provider.exchange_code(
        "code", _transaction(), callback_state="s" * 43, redirect_uri="https://sx.test/cb"
    )
    assert assertion.email == "kiran.mehta@example.test"
    claims = provider.claims_for("s" * 43)
    assert claims is not None and claims.title is None


async def test_a_refused_code_and_a_wrong_state_are_refusals() -> None:
    pulse = FakePulse()
    pulse.token_status = 400
    provider = _provider(pulse)
    await provider.prepare()
    with pytest.raises(IdentityProviderRejected):
        await provider.exchange_code(
            "code", _transaction(), callback_state="s" * 43, redirect_uri="https://sx.test/cb"
        )
    with pytest.raises(IdentityProviderRejected):
        await provider.exchange_code(
            "code", _transaction(), callback_state="t" * 43, redirect_uri="https://sx.test/cb"
        )
    pulse.token_status = 503
    with pytest.raises(IdentityProviderUnavailable):
        await provider.exchange_code(
            "code", _transaction(), callback_state="s" * 43, redirect_uri="https://sx.test/cb"
        )


async def test_discovery_must_name_the_configured_issuer() -> None:
    pulse = FakePulse()
    pulse.issuer_stated = "https://other-pulse.example.test"
    provider = _provider(pulse)
    with pytest.raises(IdentityProviderUnavailable):
        await provider.prepare()


def test_issuers_are_https_except_on_this_computer() -> None:
    assert normalize_issuer("https://pulse-dev.estateautopilots.com/") == (
        "https://pulse-dev.estateautopilots.com"
    )
    assert normalize_issuer("http://127.0.0.1:4100") == "http://127.0.0.1:4100"
    for wrong in ("http://pulse.estateautopilots.com", "https://u:p@pulse.test", "ftp://x"):
        with pytest.raises(ValueError):
            normalize_issuer(wrong)


def test_claims_keep_display_text_only() -> None:
    claims = PulseClaims.from_claims(
        ISSUER,
        {
            "sub": "p1",
            "name": "  Tara\nKapoor ",
            "title": "x" * 500,
            "team": "Ops",
            "picture": 42,
            "pulse_orgs": [{"id": "o1"}, {"name": "no id"}, "junk"],
        },
    )
    assert claims.name == "Tara Kapoor"
    assert claims.title is None and claims.team == "Ops" and claims.picture is None
    assert [org.id for org in claims.orgs] == ["o1"]
    assert json.dumps(claims.subject) == '"p1"'
