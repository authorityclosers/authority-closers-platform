"""Continue with Facebook: a server-side redirect flow, no Facebook SDK in the page.

The browser only ever visits facebook.com's authorization dialog and comes back to
``/v1/auth/facebook/callback`` with a code. The code is exchanged here with the app
secret and the transaction's PKCE verifier, and the person is read from the Graph API
with ``appsecret_proof``. No Facebook token reaches the browser or the database.

Inside the Android app (owner, 23 Oct 2026) Facebook's own SDK signs in instead and
the page passes its user access token here once (``verify_native_token``). It counts
only if ``debug_token`` says Facebook issued it to this app, for that person.

Meta returns ``email`` only when the person has a confirmed primary address, but it
gives no verification flag, so Sales Xray never links a Facebook email to an existing
account (see ``link_existing_email`` in the identity application).
"""

from __future__ import annotations

import hashlib
import hmac
import re
from typing import Any
from urllib.parse import urlencode

import httpx

from ac_platform.http.auth_transactions import AuthTransaction
from ac_platform.http.identity_provider import (
    IdentityProviderEmailMissing,
    IdentityProviderRejected,
    IdentityProviderUnavailable,
)
from ac_platform.identity.services import VerifiedProviderAssertion

FACEBOOK_ISSUER = "https://www.facebook.com"
DEFAULT_GRAPH_VERSION = "v23.0"
_GRAPH_VERSION = re.compile(r"v\d{1,2}\.\d")
_APP_ID = re.compile(r"[0-9]{5,25}")
_SUBJECT = re.compile(r"[0-9]{1,40}")


def _text(value: object, maximum: int) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = " ".join(value.split())
    return cleaned if 0 < len(cleaned) <= maximum else None


class FacebookLoginProvider:
    """Facebook Login (manual flow) with PKCE, the app secret and appsecret_proof."""

    DIALOG_HOST = "https://www.facebook.com"
    GRAPH_HOST = "https://graph.facebook.com"
    SCOPE = "public_profile,email"

    def __init__(
        self,
        *,
        app_id: str,
        app_secret: str,
        graph_version: str = DEFAULT_GRAPH_VERSION,
        timeout_seconds: float = 10.0,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        normalized_app_id = app_id.strip()
        if _APP_ID.fullmatch(normalized_app_id) is None:
            raise ValueError("Facebook app ID must be the numeric app ID")
        secret = app_secret.strip()
        if not secret or len(secret) > 512:
            raise ValueError("Facebook app secret is invalid")
        version = graph_version.strip() or DEFAULT_GRAPH_VERSION
        if _GRAPH_VERSION.fullmatch(version) is None:
            raise ValueError("Facebook Graph API version must look like v23.0")
        if timeout_seconds <= 0 or timeout_seconds > 30:
            raise ValueError("Facebook timeout must be between zero and 30 seconds")
        self._app_id = normalized_app_id
        self._app_secret = secret
        self._version = version
        self._timeout = httpx.Timeout(timeout_seconds)
        self._http_client = http_client

    @property
    def audience(self) -> str:
        return self._app_id

    def authorization_url(
        self,
        transaction: AuthTransaction,
        *,
        redirect_uri: str,
    ) -> str:
        parameters = {
            "client_id": self._app_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": self.SCOPE,
            "state": transaction.state,
            "code_challenge": transaction.pkce_challenge,
            "code_challenge_method": "S256",
            # Ask again for the email permission if it was declined before.
            "auth_type": "rerequest",
        }
        return f"{self.DIALOG_HOST}/{self._version}/dialog/oauth?{urlencode(parameters)}"

    async def _get(self, path: str, parameters: dict[str, str]) -> httpx.Response:
        url = f"{self.GRAPH_HOST}/{self._version}/{path}"
        if self._http_client is not None:
            return await self._http_client.get(
                url,
                params=parameters,
                timeout=self._timeout,
                follow_redirects=False,
            )
        async with httpx.AsyncClient(timeout=self._timeout, follow_redirects=False) as client:
            return await client.get(url, params=parameters)

    @staticmethod
    def _json_object(response: httpx.Response) -> dict[str, Any]:
        try:
            payload = response.json()
        except ValueError as exc:
            raise IdentityProviderRejected("Facebook returned an invalid response.") from exc
        if not isinstance(payload, dict):
            raise IdentityProviderRejected("Facebook returned an invalid response.")
        return payload

    async def exchange_code(
        self,
        code: str,
        transaction: AuthTransaction,
        *,
        callback_state: str,
        redirect_uri: str,
    ) -> VerifiedProviderAssertion:
        if not hmac.compare_digest(callback_state, transaction.state):
            raise IdentityProviderRejected("Facebook callback state did not match.")
        if not code or len(code) > 4096 or not code.isascii():
            raise IdentityProviderRejected("Facebook returned an invalid authorization code.")
        try:
            token_response = await self._get(
                "oauth/access_token",
                {
                    "client_id": self._app_id,
                    "client_secret": self._app_secret,
                    "redirect_uri": redirect_uri,
                    "code": code,
                    "code_verifier": transaction.pkce_verifier,
                },
            )
        except httpx.HTTPError as exc:
            raise IdentityProviderUnavailable("Facebook token exchange is unavailable.") from exc
        if token_response.status_code >= 500:
            raise IdentityProviderUnavailable("Facebook token exchange is unavailable.")
        if token_response.status_code != 200:
            raise IdentityProviderRejected("Facebook rejected the authorization code.")
        access_token = self._json_object(token_response).get("access_token")
        if not isinstance(access_token, str) or not access_token or len(access_token) > 4096:
            raise IdentityProviderRejected("Facebook returned an invalid token response.")
        return await self._profile_assertion(
            access_token, transaction, callback_state=callback_state
        )

    async def verify_native_token(
        self,
        token: str,
        transaction: AuthTransaction,
        *,
        callback_state: str,
    ) -> VerifiedProviderAssertion:
        """A user access token from the Facebook SDK in the Android app.

        A token Facebook issued to another app, or no longer valid, is refused before
        the person is read; the person read must be the one the token belongs to.
        """

        if not hmac.compare_digest(callback_state, transaction.state):
            raise IdentityProviderRejected("Facebook sign-in state did not match.")
        if not token or len(token) > 4096 or not token.isascii():
            raise IdentityProviderRejected("Facebook returned an invalid access token.")
        try:
            debug_response = await self._get(
                "debug_token",
                {
                    "input_token": token,
                    "access_token": f"{self._app_id}|{self._app_secret}",
                },
            )
        except httpx.HTTPError as exc:
            raise IdentityProviderUnavailable("Facebook token check is unavailable.") from exc
        if debug_response.status_code >= 500:
            raise IdentityProviderUnavailable("Facebook token check is unavailable.")
        if debug_response.status_code != 200:
            raise IdentityProviderRejected("Facebook refused the token check.")
        data = self._json_object(debug_response).get("data")
        if not isinstance(data, dict):
            raise IdentityProviderRejected("Facebook returned an invalid token check.")
        app_id = data.get("app_id")
        user_id = data.get("user_id")
        if (
            data.get("is_valid") is not True
            or not isinstance(app_id, str)
            or not hmac.compare_digest(app_id, self._app_id)
            or data.get("type") != "USER"
            or not isinstance(user_id, str)
            or _SUBJECT.fullmatch(user_id) is None
        ):
            raise IdentityProviderRejected("The Facebook token is not for this app.")
        return await self._profile_assertion(
            token, transaction, callback_state=callback_state, expected_subject=user_id
        )

    async def _profile_assertion(
        self,
        access_token: str,
        transaction: AuthTransaction,
        *,
        callback_state: str,
        expected_subject: str | None = None,
    ) -> VerifiedProviderAssertion:
        proof = hmac.new(
            self._app_secret.encode("utf-8"),
            access_token.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        try:
            me_response = await self._get(
                "me",
                {
                    "fields": "id,name,first_name,last_name,email",
                    "access_token": access_token,
                    "appsecret_proof": proof,
                },
            )
        except httpx.HTTPError as exc:
            raise IdentityProviderUnavailable("Facebook profile is unavailable.") from exc
        if me_response.status_code >= 500:
            raise IdentityProviderUnavailable("Facebook profile is unavailable.")
        if me_response.status_code != 200:
            raise IdentityProviderRejected("Facebook refused the profile request.")
        profile = self._json_object(me_response)
        subject = profile.get("id")
        if not isinstance(subject, str) or _SUBJECT.fullmatch(subject) is None:
            raise IdentityProviderRejected("Facebook returned an invalid person id.")
        if expected_subject is not None and not hmac.compare_digest(subject, expected_subject):
            raise IdentityProviderRejected("The Facebook token belongs to someone else.")
        email = profile.get("email")
        if not isinstance(email, str) or not email.strip() or len(email) > 320 or "@" not in email:
            # Phone-only accounts, or the email permission was declined.
            raise IdentityProviderEmailMissing("Facebook did not share an email address.")
        return VerifiedProviderAssertion(
            issuer=FACEBOOK_ISSUER,
            subject=subject,
            audience=self._app_id,
            state=callback_state,
            # Facebook's code flow carries no nonce; state, PKCE and the app
            # secret bind this exchange to the transaction instead.
            nonce=transaction.nonce,
            authorization_type=transaction.authorization_type,
            email=email.strip(),
            email_verified=True,
            display_name=_text(profile.get("name"), 200),
            given_name=_text(profile.get("first_name"), 100),
            family_name=_text(profile.get("last_name"), 100),
        )


__all__ = ["DEFAULT_GRAPH_VERSION", "FACEBOOK_ISSUER", "FacebookLoginProvider"]
