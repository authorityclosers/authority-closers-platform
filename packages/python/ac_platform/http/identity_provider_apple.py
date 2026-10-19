"""Sign in with Apple on the web: Services ID, a signed client secret, form_post.

Apple posts the result to ``/v1/auth/apple/callback`` (a cross-site POST, so the
SameSite=Lax transaction cookie is not sent with it); the route bounces it to a
same-site GET with the code sealed in a short cookie, and the normal callback runs
from there. This adapter then exchanges the code with a short ES256 client secret
and verifies Apple's RS256 identity token against Apple's published keys, its
issuer, audience, expiry and the transaction's nonce. Private-relay addresses
(``…@privaterelay.appleid.com``) are ordinary verified emails here.
"""

from __future__ import annotations

import base64
import binascii
import hmac
import json
import time
from collections.abc import Callable, Mapping
from typing import Any
from urllib.parse import urlencode

import httpx
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPublicNumbers
from google.auth import jwt as google_jwt
from google.auth.crypt import es256

from ac_platform.http.auth_transactions import AuthTransaction
from ac_platform.http.identity_provider import (
    IdentityProviderEmailMissing,
    IdentityProviderRejected,
    IdentityProviderUnavailable,
)
from ac_platform.identity.services import VerifiedProviderAssertion

APPLE_ISSUER = "https://appleid.apple.com"
PRIVATE_RELAY_DOMAIN = "privaterelay.appleid.com"
_CLIENT_SECRET_SECONDS = 300
_KEYS_CACHE_SECONDS = 3600
_CLOCK_SKEW_SECONDS = 60


def normalize_apple_private_key(value: str) -> str:
    """Accept the .p8 key as PEM (real or escaped newlines) or as base64 of the file."""

    text = value.strip()
    if "BEGIN PRIVATE KEY" in text:
        return text.replace("\\n", "\n") + "\n"
    try:
        decoded = base64.b64decode(text, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("Apple private key must be the .p8 file or its base64") from exc
    if decoded.lstrip().startswith(b"-----BEGIN PRIVATE KEY-----"):
        return decoded.decode("ascii").strip() + "\n"
    der = serialization.load_der_private_key(decoded, password=None)
    return der.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode("ascii")


def _b64url_int(value: object) -> int:
    if not isinstance(value, str) or not value or len(value) > 1024:
        raise ValueError("invalid key number")
    raw = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    return int.from_bytes(raw, "big")


def _jwk_to_pem(key: Mapping[str, Any]) -> str:
    if key.get("kty") != "RSA" or key.get("alg", "RS256") != "RS256":
        raise ValueError("unsupported Apple key")
    numbers = RSAPublicNumbers(_b64url_int(key.get("e")), _b64url_int(key.get("n")))
    return (
        numbers.public_key()
        .public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode("ascii")
    )


def _claim_true(value: object) -> bool:
    return value is True or value == "true"


def _text(value: object, maximum: int) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = " ".join(value.split())
    return cleaned if 0 < len(cleaned) <= maximum else None


def apple_user_name(raw_user: str | None) -> tuple[str | None, str | None]:
    """First and last name from Apple's first-sign-in ``user`` form field, if any."""

    if not raw_user or len(raw_user) > 4096:
        return None, None
    try:
        payload = json.loads(raw_user)
    except ValueError:
        return None, None
    name = payload.get("name") if isinstance(payload, dict) else None
    if not isinstance(name, dict):
        return None, None
    return _text(name.get("firstName"), 100), _text(name.get("lastName"), 100)


Clock = Callable[[], float]


class AppleSignInProvider:
    """Sign in with Apple REST flow for one Services ID."""

    AUTHORIZATION_ENDPOINT = "https://appleid.apple.com/auth/authorize"
    TOKEN_ENDPOINT = "https://appleid.apple.com/auth/token"  # noqa: S105
    KEYS_ENDPOINT = "https://appleid.apple.com/auth/keys"

    def __init__(
        self,
        *,
        service_id: str,
        team_id: str,
        key_id: str,
        private_key: str,
        timeout_seconds: float = 10.0,
        http_client: httpx.AsyncClient | None = None,
        clock: Clock = time.time,
    ) -> None:
        normalized_service_id = service_id.strip()
        if not normalized_service_id or len(normalized_service_id) > 255:
            raise ValueError("Apple Services ID is invalid")
        normalized_team_id = team_id.strip()
        normalized_key_id = key_id.strip()
        if len(normalized_team_id) != 10 or not normalized_team_id.isalnum():
            raise ValueError("Apple team ID must be the 10-character team ID")
        if len(normalized_key_id) != 10 or not normalized_key_id.isalnum():
            raise ValueError("Apple key ID must be the 10-character key ID")
        if timeout_seconds <= 0 or timeout_seconds > 30:
            raise ValueError("Apple timeout must be between zero and 30 seconds")
        self._service_id = normalized_service_id
        self._team_id = normalized_team_id
        self._signer = es256.ES256Signer.from_string(
            normalize_apple_private_key(private_key),
            normalized_key_id,
        )
        self._key_id = normalized_key_id
        self._timeout = httpx.Timeout(timeout_seconds)
        self._http_client = http_client
        self._clock = clock
        self._keys: dict[str, str] = {}
        self._keys_expire_at = 0.0

    @property
    def audience(self) -> str:
        return self._service_id

    def authorization_url(
        self,
        transaction: AuthTransaction,
        *,
        redirect_uri: str,
    ) -> str:
        parameters = {
            "client_id": self._service_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            # Apple returns name and email only through form_post.
            "response_mode": "form_post",
            "scope": "name email",
            "state": transaction.state,
            "nonce": transaction.nonce,
        }
        return f"{self.AUTHORIZATION_ENDPOINT}?{urlencode(parameters)}"

    def client_secret(self) -> str:
        now = int(self._clock())
        token = google_jwt.encode(  # type: ignore[no-untyped-call]
            self._signer,
            {
                "iss": self._team_id,
                "iat": now,
                "exp": now + _CLIENT_SECRET_SECONDS,
                "aud": APPLE_ISSUER,
                "sub": self._service_id,
            },
            key_id=self._key_id,
        )
        return token.decode("ascii") if isinstance(token, bytes) else str(token)

    async def _request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        if self._http_client is not None:
            return await self._http_client.request(
                method,
                url,
                timeout=self._timeout,
                follow_redirects=False,
                **kwargs,
            )
        async with httpx.AsyncClient(timeout=self._timeout, follow_redirects=False) as client:
            return await client.request(method, url, **kwargs)

    async def _signing_keys(self, *, refresh: bool) -> dict[str, str]:
        if not refresh and self._keys and self._clock() < self._keys_expire_at:
            return self._keys
        try:
            response = await self._request("GET", self.KEYS_ENDPOINT)
        except httpx.HTTPError as exc:
            raise IdentityProviderUnavailable("Apple signing keys are unavailable.") from exc
        if response.status_code != 200:
            raise IdentityProviderUnavailable("Apple signing keys are unavailable.")
        try:
            payload = response.json()
            keys = {
                str(key["kid"]): _jwk_to_pem(key)
                for key in payload["keys"]
                if isinstance(key, dict) and isinstance(key.get("kid"), str)
            }
        except (KeyError, TypeError, ValueError) as exc:
            raise IdentityProviderUnavailable("Apple signing keys are invalid.") from exc
        if not keys:
            raise IdentityProviderUnavailable("Apple published no signing keys.")
        self._keys = keys
        self._keys_expire_at = self._clock() + _KEYS_CACHE_SECONDS
        return keys

    async def _verified_claims(self, id_token: str) -> Mapping[str, Any]:
        try:
            header = google_jwt.decode_header(id_token)  # type: ignore[no-untyped-call]
        except (ValueError, TypeError) as exc:
            raise IdentityProviderRejected("Apple identity token is malformed.") from exc
        kid = header.get("kid") if isinstance(header, dict) else None
        if not isinstance(kid, str) or header.get("alg") != "RS256":
            raise IdentityProviderRejected("Apple identity token header is invalid.")
        keys = await self._signing_keys(refresh=False)
        if kid not in keys:
            # Apple rotates keys; read them again once before refusing.
            keys = await self._signing_keys(refresh=True)
        if kid not in keys:
            raise IdentityProviderRejected("Apple identity token key is unknown.")
        try:
            claims = google_jwt.decode(  # type: ignore[no-untyped-call]
                id_token,
                certs={kid: keys[kid]},
                verify=True,
                audience=self._service_id,
                clock_skew_in_seconds=_CLOCK_SKEW_SECONDS,
            )
        except (ValueError, TypeError) as exc:
            raise IdentityProviderRejected("Apple identity token verification failed.") from exc
        if not isinstance(claims, Mapping):
            raise IdentityProviderRejected("Apple identity token is invalid.")
        return claims

    async def exchange_code(
        self,
        code: str,
        transaction: AuthTransaction,
        *,
        callback_state: str,
        redirect_uri: str,
    ) -> VerifiedProviderAssertion:
        if not hmac.compare_digest(callback_state, transaction.state):
            raise IdentityProviderRejected("Apple callback state did not match.")
        if not code or len(code) > 4096 or not code.isascii():
            raise IdentityProviderRejected("Apple returned an invalid authorization code.")
        try:
            response = await self._request(
                "POST",
                self.TOKEN_ENDPOINT,
                data={
                    "client_id": self._service_id,
                    "client_secret": self.client_secret(),
                    "code": code,
                    "grant_type": "authorization_code",
                    "redirect_uri": redirect_uri,
                },
            )
        except httpx.HTTPError as exc:
            raise IdentityProviderUnavailable("Apple token exchange is unavailable.") from exc
        if response.status_code >= 500:
            raise IdentityProviderUnavailable("Apple token exchange is unavailable.")
        if response.status_code != 200:
            raise IdentityProviderRejected("Apple rejected the authorization code.")
        try:
            payload = response.json()
            id_token = payload["id_token"] if isinstance(payload, dict) else None
        except (KeyError, ValueError) as exc:
            raise IdentityProviderRejected("Apple returned an invalid token response.") from exc
        if not isinstance(id_token, str) or not id_token or len(id_token) > 16_384:
            raise IdentityProviderRejected("Apple returned an invalid token response.")
        claims = await self._verified_claims(id_token)
        issuer = claims.get("iss")
        subject = claims.get("sub")
        audience = claims.get("aud")
        nonce = claims.get("nonce")
        if issuer != APPLE_ISSUER:
            raise IdentityProviderRejected("Apple identity token issuer is invalid.")
        if not isinstance(subject, str) or not subject or len(subject) > 512:
            raise IdentityProviderRejected("Apple identity token subject is invalid.")
        if not isinstance(audience, str) or not hmac.compare_digest(audience, self._service_id):
            raise IdentityProviderRejected("Apple identity token audience is invalid.")
        if not isinstance(nonce, str) or not hmac.compare_digest(nonce, transaction.nonce):
            raise IdentityProviderRejected("Apple identity token nonce is invalid.")
        email = claims.get("email")
        if (
            not isinstance(email, str)
            or not email.strip()
            or len(email) > 320
            or not _claim_true(claims.get("email_verified"))
        ):
            raise IdentityProviderEmailMissing("Apple did not share a verified email address.")
        return VerifiedProviderAssertion(
            issuer=APPLE_ISSUER,
            subject=subject,
            audience=audience,
            state=callback_state,
            nonce=nonce,
            authorization_type=transaction.authorization_type,
            email=email.strip(),
            email_verified=True,
        )


__all__ = [
    "APPLE_ISSUER",
    "PRIVATE_RELAY_DOMAIN",
    "AppleSignInProvider",
    "apple_user_name",
    "normalize_apple_private_key",
]
