"""Protocol boundary between HTTP OAuth and canonical identity commands."""

from __future__ import annotations

import asyncio
import hmac
from collections.abc import Callable, Mapping
from typing import Any, Protocol, cast
from urllib.parse import urlencode

import httpx
from google.auth.transport.requests import Request as GoogleAuthRequest
from google.oauth2.id_token import verify_oauth2_token

from ac_platform.http.auth_transactions import AuthTransaction
from ac_platform.identity.services import VerifiedProviderAssertion
from ac_platform.kernel.errors import DomainError


class IdentityProviderUnavailable(DomainError):
    code = "identity_provider_unavailable"
    title = "Sign-in is temporarily unavailable"
    status = 503


class IdentityProviderRejected(DomainError):
    code = "identity_provider_rejected"
    title = "Sign-in was rejected"
    status = 401


class OAuthIdentityProvider(Protocol):
    """A server-side provider adapter; no provider token crosses into a browser."""

    @property
    def audience(self) -> str: ...

    def authorization_url(
        self,
        transaction: AuthTransaction,
        *,
        redirect_uri: str,
    ) -> str: ...

    async def exchange_code(
        self,
        code: str,
        transaction: AuthTransaction,
        *,
        callback_state: str,
        redirect_uri: str,
    ) -> VerifiedProviderAssertion: ...


class DisabledIdentityProvider:
    """Production-safe default used until a reviewed Google adapter is supplied."""

    @property
    def audience(self) -> str:
        raise IdentityProviderUnavailable("No external identity provider is configured.")

    def authorization_url(
        self,
        transaction: AuthTransaction,
        *,
        redirect_uri: str,
    ) -> str:
        del transaction, redirect_uri
        raise IdentityProviderUnavailable("No external identity provider is configured.")

    async def exchange_code(
        self,
        code: str,
        transaction: AuthTransaction,
        *,
        callback_state: str,
        redirect_uri: str,
    ) -> VerifiedProviderAssertion:
        del code, transaction, callback_state, redirect_uri
        raise IdentityProviderUnavailable("No external identity provider is configured.")


TokenVerifier = Callable[[str, str], Mapping[str, Any]]


def _verify_google_token(token: str, audience: str) -> Mapping[str, Any]:
    claims = verify_oauth2_token(  # type: ignore[no-untyped-call]
        token,
        GoogleAuthRequest(),
        audience,
    )
    return cast(Mapping[str, Any], claims)


class GoogleOIDCProvider:
    """Google authorization-code adapter with PKCE and local ID-token verification."""

    AUTHORIZATION_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
    TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"  # noqa: S105

    def __init__(
        self,
        *,
        client_id: str,
        client_secret: str,
        timeout_seconds: float = 10.0,
        http_client: httpx.AsyncClient | None = None,
        token_verifier: TokenVerifier = _verify_google_token,
    ) -> None:
        normalized_client_id = client_id.strip()
        if not normalized_client_id.endswith(".apps.googleusercontent.com"):
            raise ValueError("Google client ID is not a web application client ID")
        if not client_secret or len(client_secret) > 4096:
            raise ValueError("Google client secret is invalid")
        if timeout_seconds <= 0 or timeout_seconds > 30:
            raise ValueError("Google OAuth timeout must be between zero and 30 seconds")
        self._client_id = normalized_client_id
        self._client_secret = client_secret
        self._timeout = httpx.Timeout(timeout_seconds)
        self._http_client = http_client
        self._token_verifier = token_verifier

    @property
    def audience(self) -> str:
        return self._client_id

    def authorization_url(
        self,
        transaction: AuthTransaction,
        *,
        redirect_uri: str,
    ) -> str:
        parameters = {
            "client_id": self._client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": "openid email profile",
            "state": transaction.state,
            "nonce": transaction.nonce,
            "code_challenge": transaction.pkce_challenge,
            "code_challenge_method": "S256",
            "access_type": "online",
            "include_granted_scopes": "true",
            "prompt": "select_account",
        }
        return f"{self.AUTHORIZATION_ENDPOINT}?{urlencode(parameters)}"

    async def _exchange_token(self, form: dict[str, str]) -> httpx.Response:
        if self._http_client is not None:
            return await self._http_client.post(
                self.TOKEN_ENDPOINT,
                data=form,
                timeout=self._timeout,
                follow_redirects=False,
            )
        async with httpx.AsyncClient(timeout=self._timeout, follow_redirects=False) as client:
            return await client.post(self.TOKEN_ENDPOINT, data=form)

    async def exchange_code(
        self,
        code: str,
        transaction: AuthTransaction,
        *,
        callback_state: str,
        redirect_uri: str,
    ) -> VerifiedProviderAssertion:
        if not hmac.compare_digest(callback_state, transaction.state):
            raise IdentityProviderRejected("Google callback state did not match.")
        if not code or len(code) > 4096 or not code.isascii():
            raise IdentityProviderRejected("Google returned an invalid authorization code.")
        try:
            response = await self._exchange_token(
                {
                    "code": code,
                    "client_id": self._client_id,
                    "client_secret": self._client_secret,
                    "redirect_uri": redirect_uri,
                    "grant_type": "authorization_code",
                    "code_verifier": transaction.pkce_verifier,
                }
            )
        except httpx.HTTPError as exc:
            raise IdentityProviderUnavailable("Google token exchange is unavailable.") from exc
        if response.status_code >= 500:
            raise IdentityProviderUnavailable("Google token exchange is unavailable.")
        if response.status_code != 200:
            raise IdentityProviderRejected("Google rejected the authorization code.")
        try:
            payload = response.json()
            if not isinstance(payload, dict):
                raise TypeError("token response is not an object")
            raw_id_token = payload["id_token"]
            if not isinstance(raw_id_token, str) or not raw_id_token or len(raw_id_token) > 16_384:
                raise ValueError("ID token is invalid")
        except (KeyError, TypeError, ValueError) as exc:
            raise IdentityProviderRejected("Google returned an invalid token response.") from exc
        try:
            claims = await asyncio.to_thread(
                self._token_verifier,
                raw_id_token,
                self._client_id,
            )
        except Exception as exc:
            raise IdentityProviderRejected("Google ID token verification failed.") from exc
        issuer = claims.get("iss")
        subject = claims.get("sub")
        audience = claims.get("aud")
        nonce = claims.get("nonce")
        email = claims.get("email")
        email_verified = claims.get("email_verified")
        display_name = claims.get("name")
        if not isinstance(issuer, str) or issuer not in {
            "accounts.google.com",
            "https://accounts.google.com",
        }:
            raise IdentityProviderRejected("Google ID token issuer is invalid.")
        if not isinstance(subject, str) or not subject or len(subject) > 512:
            raise IdentityProviderRejected("Google ID token subject is invalid.")
        if not isinstance(audience, str) or not hmac.compare_digest(audience, self._client_id):
            raise IdentityProviderRejected("Google ID token audience is invalid.")
        if not isinstance(nonce, str) or not hmac.compare_digest(nonce, transaction.nonce):
            raise IdentityProviderRejected("Google ID token nonce is invalid.")
        if not isinstance(email, str) or not email or len(email) > 320:
            raise IdentityProviderRejected("Google did not return a valid email.")
        if email_verified is not True:
            raise IdentityProviderRejected("Google email is not verified.")
        return VerifiedProviderAssertion(
            issuer=issuer,
            subject=subject,
            audience=audience,
            state=callback_state,
            nonce=nonce,
            authorization_type=transaction.authorization_type,
            email=email,
            email_verified=True,
            display_name=display_name if isinstance(display_name, str) else None,
        )


def create_google_provider(
    *,
    client_id: str,
    client_secret: str,
) -> GoogleOIDCProvider:
    return GoogleOIDCProvider(client_id=client_id, client_secret=client_secret)


__all__ = [
    "DisabledIdentityProvider",
    "GoogleOIDCProvider",
    "IdentityProviderRejected",
    "IdentityProviderUnavailable",
    "OAuthIdentityProvider",
    "create_google_provider",
]
