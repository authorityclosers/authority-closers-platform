"""OpenID Connect against one Pulse issuer: discovery, PKCE code flow, ID-token checks.

Pulse publishes ``{issuer}/.well-known/openid-configuration``; every endpoint is read
from there, so Pulse may move them. ID tokens are signed RS256 or ES256 with a ``kid``
from the published JWKS (read again once when a token names an unknown key, because
Pulse rotates with overlap). Sales X-Ray checks the issuer, the audience (its own client
id), the expiry, the nonce of the sign-in it started, and that the email is verified.
The client authenticates with HTTP Basic (``client_secret_basic``) unless Pulse only
offers ``client_secret_post``. No Pulse token ever reaches a browser.
"""

from __future__ import annotations

import base64
import hmac
import time
from collections import OrderedDict
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import quote, urlencode, urlsplit

import httpx
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ec import SECP256R1, EllipticCurvePublicNumbers
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPublicNumbers
from google.auth import jwt as google_jwt

from ac_platform.http.auth_transactions import AuthTransaction
from ac_platform.http.identity_provider import (
    IdentityProviderEmailMissing,
    IdentityProviderRejected,
    IdentityProviderUnavailable,
)
from ac_platform.identity.services import VerifiedProviderAssertion

# The scopes a person's sign-in asks for (contract, section 1).
SIGN_IN_SCOPES = "openid profile email pulse.orgs"
# The scopes an organisation's link asks for (contract, section 2).
ORG_LINK_SCOPES = "openid pulse.org.read pulse.org.webhooks"
_DISCOVERY_SECONDS = 3600
_KEYS_SECONDS = 3600
_CLOCK_SKEW_SECONDS = 60
_LOCAL_HOSTS = ("127.0.0.1", "localhost")
_MAX_BODY = 256 * 1024
_ALGORITHMS = frozenset({"RS256", "ES256"})

Clock = Callable[[], float]


def normalize_issuer(value: str) -> str:
    """The issuer as Pulse states it: https (http only on this computer), no trailing /."""
    text = (value or "").strip().rstrip("/")
    try:
        parts = urlsplit(text)
    except ValueError as exc:
        raise ValueError("Pulse issuer is not a URL") from exc
    host = parts.hostname or ""
    local = host in _LOCAL_HOSTS or host.endswith(".test")
    if parts.scheme != "https" and not (parts.scheme == "http" and local):
        raise ValueError("Pulse issuer must use https")
    if not host or parts.query or parts.fragment or parts.username or parts.password:
        raise ValueError("Pulse issuer must be a plain base address")
    return text


def _https_like(url: object, issuer: str) -> str:
    if not isinstance(url, str) or not url or len(url) > 2048:
        raise ValueError("endpoint missing")
    parts = urlsplit(url)
    issuer_parts = urlsplit(issuer)
    if parts.scheme != "https" and not (parts.scheme == "http" and issuer_parts.scheme == "http"):
        raise ValueError("endpoint must use https")
    if not parts.hostname or parts.username or parts.password or parts.fragment:
        raise ValueError("endpoint is not a plain address")
    return url


def _b64url_int(value: object) -> int:
    if not isinstance(value, str) or not value or len(value) > 1024:
        raise ValueError("invalid key number")
    raw = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    return int.from_bytes(raw, "big")


def jwk_to_pem(key: Mapping[str, Any]) -> str:
    """A public JWK (RSA, or EC P-256) as PEM, for the ID-token verifier."""
    kty = key.get("kty")
    if kty == "RSA" and key.get("alg", "RS256") == "RS256":
        public = RSAPublicNumbers(_b64url_int(key.get("e")), _b64url_int(key.get("n"))).public_key()
    elif kty == "EC" and key.get("crv") == "P-256" and key.get("alg", "ES256") == "ES256":
        public = EllipticCurvePublicNumbers(  # type: ignore[assignment]
            _b64url_int(key.get("x")), _b64url_int(key.get("y")), SECP256R1()
        ).public_key()
    else:
        raise ValueError("unsupported Pulse key")
    return public.public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    ).decode("ascii")


def _text(value: object, maximum: int) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = " ".join(value.split())
    if not cleaned or len(cleaned) > maximum:
        return None
    if any(ord(char) < 0x20 or ord(char) == 0x7F for char in cleaned):
        return None
    return cleaned


@dataclass(frozen=True, slots=True)
class Discovery:
    issuer: str
    authorization_endpoint: str
    token_endpoint: str
    jwks_uri: str
    userinfo_endpoint: str | None
    revocation_endpoint: str | None
    api_base: str
    basic_auth: bool


@dataclass(frozen=True, slots=True)
class PulseOrg:
    id: str
    name: str | None
    role: str | None


@dataclass(frozen=True, slots=True)
class PulseClaims:
    """What a person's Pulse account says about them (display only, never an identity key)."""

    issuer: str
    subject: str
    name: str | None = None
    given_name: str | None = None
    family_name: str | None = None
    picture: str | None = None
    title: str | None = None
    team: str | None = None
    handle: str | None = None
    orgs: tuple[PulseOrg, ...] = field(default_factory=tuple)

    @classmethod
    def from_claims(cls, issuer: str, claims: Mapping[str, Any]) -> PulseClaims:
        orgs: list[PulseOrg] = []
        raw_orgs = claims.get("pulse_orgs")
        if isinstance(raw_orgs, list):
            for item in raw_orgs[:20]:
                if isinstance(item, Mapping) and _text(item.get("id"), 128):
                    orgs.append(
                        PulseOrg(
                            id=str(_text(item.get("id"), 128)),
                            name=_text(item.get("name"), 200),
                            role=_text(item.get("role"), 40),
                        )
                    )
        picture = claims.get("picture")
        return cls(
            issuer=issuer,
            subject=str(claims.get("sub")),
            name=_text(claims.get("name"), 200),
            given_name=_text(claims.get("given_name"), 200),
            family_name=_text(claims.get("family_name"), 200),
            picture=picture if isinstance(picture, str) and len(picture) <= 2048 else None,
            title=_text(claims.get("title") or claims.get("job_title"), 120),
            team=_text(claims.get("team"), 120),
            handle=_text(claims.get("preferred_username"), 60),
            orgs=tuple(orgs),
        )


class PulseClient:
    """One Pulse issuer and Sales X-Ray's client there."""

    def __init__(
        self,
        *,
        issuer: str,
        client_id: str,
        client_secret: str,
        timeout_seconds: float = 10.0,
        http_client: httpx.AsyncClient | None = None,
        clock: Clock = time.time,
    ) -> None:
        self.issuer = normalize_issuer(issuer)
        self.client_id = client_id.strip()
        if not self.client_id or len(self.client_id) > 255:
            raise ValueError("Pulse client id is invalid")
        if not client_secret or len(client_secret) > 4096:
            raise ValueError("Pulse client secret is invalid")
        if timeout_seconds <= 0 or timeout_seconds > 30:
            raise ValueError("Pulse timeout must be between zero and 30 seconds")
        self._secret = client_secret
        self._timeout = httpx.Timeout(timeout_seconds)
        self._http_client = http_client
        self._clock = clock
        self._discovery: Discovery | None = None
        self._discovery_until = 0.0
        self._keys: dict[str, str] = {}
        self._keys_until = 0.0

    # ----- transport ----------------------------------------------------------------

    async def request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        try:
            if self._http_client is not None:
                return await self._http_client.request(
                    method, url, timeout=self._timeout, follow_redirects=False, **kwargs
                )
            async with httpx.AsyncClient(
                timeout=self._timeout, follow_redirects=False, trust_env=False
            ) as client:
                return await client.request(method, url, **kwargs)
        except httpx.HTTPError as exc:
            raise IdentityProviderUnavailable("Pulse is unavailable.") from exc

    @staticmethod
    def json_of(response: httpx.Response) -> dict[str, Any]:
        if len(response.content) > _MAX_BODY:
            raise IdentityProviderUnavailable("Pulse answered with too much.")
        try:
            payload = response.json()
        except ValueError as exc:
            raise IdentityProviderUnavailable("Pulse answered with something unreadable.") from exc
        if not isinstance(payload, dict):
            raise IdentityProviderUnavailable("Pulse answered with something unreadable.")
        return payload

    # ----- discovery and keys -------------------------------------------------------

    @property
    def cached_discovery(self) -> Discovery | None:
        return self._discovery

    async def discovery(self) -> Discovery:
        if self._discovery is not None and self._clock() < self._discovery_until:
            return self._discovery
        response = await self.request("GET", f"{self.issuer}/.well-known/openid-configuration")
        if response.status_code != 200:
            raise IdentityProviderUnavailable("Pulse sign-in is not published.")
        payload = self.json_of(response)
        try:
            stated = normalize_issuer(str(payload.get("issuer") or ""))
            if stated != self.issuer:
                raise ValueError("issuer mismatch")
            methods = payload.get("token_endpoint_auth_methods_supported")
            basic = not (
                isinstance(methods, list)
                and "client_secret_basic" not in methods
                and "client_secret_post" in methods
            )
            pkce = payload.get("code_challenge_methods_supported")
            if isinstance(pkce, list) and "S256" not in pkce:
                raise ValueError("Pulse does not offer PKCE S256")
            api_base = payload.get("pulse_org_api_base") or f"{self.issuer}/api/v1"
            found = Discovery(
                issuer=stated,
                authorization_endpoint=_https_like(payload.get("authorization_endpoint"), stated),
                token_endpoint=_https_like(payload.get("token_endpoint"), stated),
                jwks_uri=_https_like(payload.get("jwks_uri"), stated),
                userinfo_endpoint=(
                    _https_like(payload["userinfo_endpoint"], stated)
                    if payload.get("userinfo_endpoint")
                    else None
                ),
                revocation_endpoint=(
                    _https_like(payload["revocation_endpoint"], stated)
                    if payload.get("revocation_endpoint")
                    else None
                ),
                api_base=_https_like(api_base, stated).rstrip("/"),
                basic_auth=basic,
            )
        except (ValueError, KeyError, TypeError) as exc:
            raise IdentityProviderUnavailable("Pulse sign-in settings are invalid.") from exc
        self._discovery = found
        self._discovery_until = self._clock() + _DISCOVERY_SECONDS
        return found

    async def _signing_keys(self, *, refresh: bool) -> dict[str, str]:
        if not refresh and self._keys and self._clock() < self._keys_until:
            return self._keys
        found = await self.discovery()
        response = await self.request("GET", found.jwks_uri)
        if response.status_code != 200:
            raise IdentityProviderUnavailable("Pulse signing keys are unavailable.")
        payload = self.json_of(response)
        keys: dict[str, str] = {}
        for key in payload.get("keys") or []:
            if not isinstance(key, Mapping) or not isinstance(key.get("kid"), str):
                continue
            if key.get("use") not in (None, "sig"):
                continue
            try:
                keys[str(key["kid"])] = jwk_to_pem(key)
            except (ValueError, TypeError):
                continue
        if not keys:
            raise IdentityProviderUnavailable("Pulse published no signing keys.")
        self._keys = keys
        self._keys_until = self._clock() + _KEYS_SECONDS
        return keys

    async def verify_id_token(self, raw: str, *, nonce: str) -> dict[str, Any]:
        if not isinstance(raw, str) or not raw or len(raw) > 16_384 or not raw.isascii():
            raise IdentityProviderRejected("Pulse returned an invalid ID token.")
        try:
            header = google_jwt.decode_header(raw)  # type: ignore[no-untyped-call]
        except (ValueError, TypeError) as exc:
            raise IdentityProviderRejected("Pulse ID token is malformed.") from exc
        kid = header.get("kid") if isinstance(header, dict) else None
        if not isinstance(kid, str) or header.get("alg") not in _ALGORITHMS:
            raise IdentityProviderRejected("Pulse ID token header is invalid.")
        keys = await self._signing_keys(refresh=False)
        if kid not in keys:
            keys = await self._signing_keys(refresh=True)
        if kid not in keys:
            raise IdentityProviderRejected("Pulse ID token key is unknown.")
        try:
            claims = google_jwt.decode(  # type: ignore[no-untyped-call]
                raw,
                certs={kid: keys[kid]},
                verify=True,
                audience=self.client_id,
                clock_skew_in_seconds=_CLOCK_SKEW_SECONDS,
            )
        except (ValueError, TypeError) as exc:
            raise IdentityProviderRejected("Pulse ID token verification failed.") from exc
        if not isinstance(claims, dict):
            raise IdentityProviderRejected("Pulse ID token is invalid.")
        issuer = claims.get("iss")
        if not isinstance(issuer, str) or issuer.rstrip("/") != self.issuer:
            raise IdentityProviderRejected("Pulse ID token issuer is invalid.")
        audience = claims.get("aud")
        audiences = audience if isinstance(audience, list) else [audience]
        if self.client_id not in audiences:
            raise IdentityProviderRejected("Pulse ID token audience is invalid.")
        if len(audiences) > 1 and claims.get("azp") != self.client_id:
            raise IdentityProviderRejected("Pulse ID token audience is invalid.")
        stated = claims.get("nonce")
        if not isinstance(stated, str) or not hmac.compare_digest(stated, nonce):
            raise IdentityProviderRejected("Pulse ID token nonce is invalid.")
        subject = claims.get("sub")
        if not isinstance(subject, str) or not subject or len(subject) > 255:
            raise IdentityProviderRejected("Pulse ID token subject is invalid.")
        return claims

    # ----- the OAuth endpoints ------------------------------------------------------

    def authorize_url(self, found: Discovery, parameters: Mapping[str, str]) -> str:
        joiner = "&" if "?" in found.authorization_endpoint else "?"
        return f"{found.authorization_endpoint}{joiner}{urlencode(dict(parameters))}"

    async def token(self, form: Mapping[str, str]) -> dict[str, Any]:
        """The token endpoint, with this client's credentials. 4xx rejects; 5xx is down."""
        found = await self.discovery()
        body = dict(form)
        headers = {"Accept": "application/json"}
        if found.basic_auth:
            pair = f"{quote(self.client_id, safe='')}:{quote(self._secret, safe='')}"
            headers["Authorization"] = "Basic " + base64.b64encode(pair.encode()).decode()
        else:
            body["client_id"] = self.client_id
            body["client_secret"] = self._secret
        response = await self.request("POST", found.token_endpoint, data=body, headers=headers)
        if response.status_code >= 500:
            raise IdentityProviderUnavailable("Pulse token exchange is unavailable.")
        if response.status_code != 200:
            raise IdentityProviderRejected("Pulse refused the token request.")
        return self.json_of(response)

    async def userinfo(self, access_token: str) -> dict[str, Any]:
        found = await self.discovery()
        if found.userinfo_endpoint is None:
            return {}
        response = await self.request(
            "GET",
            found.userinfo_endpoint,
            headers={"Authorization": f"Bearer {access_token}", "Accept": "application/json"},
        )
        if response.status_code != 200:
            return {}
        return self.json_of(response)

    async def revoke(self, token: str, *, hint: str = "refresh_token") -> bool:
        found = await self.discovery()
        if found.revocation_endpoint is None:
            return False
        headers: dict[str, str] = {}
        body = {"token": token, "token_type_hint": hint}
        if found.basic_auth:
            pair = f"{quote(self.client_id, safe='')}:{quote(self._secret, safe='')}"
            headers["Authorization"] = "Basic " + base64.b64encode(pair.encode()).decode()
        else:
            body.update(client_id=self.client_id, client_secret=self._secret)
        try:
            response = await self.request(
                "POST", found.revocation_endpoint, data=body, headers=headers
            )
        except IdentityProviderUnavailable:
            return False
        return response.status_code == 200


class PulseSignInProvider:
    """Sign in with Pulse: the same identity path as Google (a verified email links)."""

    def __init__(self, client: PulseClient) -> None:
        self.client = client
        # The display claims of a sign-in this process just checked, by its state, for
        # the profile step that runs right after in the same request.
        self._claims: OrderedDict[str, PulseClaims] = OrderedDict()

    @property
    def audience(self) -> str:
        return self.client.client_id

    @property
    def issuer(self) -> str:
        return self.client.issuer

    async def prepare(self) -> None:
        """Read Pulse's discovery document before an authorize address is made."""
        await self.client.discovery()

    def authorization_url(self, transaction: AuthTransaction, *, redirect_uri: str) -> str:
        found = self.client.cached_discovery
        if found is None:
            raise IdentityProviderUnavailable("Pulse sign-in is not ready yet.")
        return self.client.authorize_url(
            found,
            {
                "client_id": self.client.client_id,
                "redirect_uri": redirect_uri,
                "response_type": "code",
                "scope": SIGN_IN_SCOPES,
                "state": transaction.state,
                "nonce": transaction.nonce,
                "code_challenge": transaction.pkce_challenge,
                "code_challenge_method": "S256",
            },
        )

    def claims_for(self, state: str) -> PulseClaims | None:
        return self._claims.pop(state, None)

    async def exchange_code(
        self,
        code: str,
        transaction: AuthTransaction,
        *,
        callback_state: str,
        redirect_uri: str,
    ) -> VerifiedProviderAssertion:
        if not hmac.compare_digest(callback_state, transaction.state):
            raise IdentityProviderRejected("Pulse callback state did not match.")
        if not code or len(code) > 4096 or not code.isascii():
            raise IdentityProviderRejected("Pulse returned an invalid authorization code.")
        payload = await self.client.token(
            {
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": redirect_uri,
                "code_verifier": transaction.pkce_verifier,
            }
        )
        claims = await self.client.verify_id_token(
            str(payload.get("id_token") or ""), nonce=transaction.nonce
        )
        merged: dict[str, Any] = dict(claims)
        access_token = payload.get("access_token")
        if isinstance(access_token, str) and access_token:
            info = await self.client.userinfo(access_token)
            # Userinfo adds claims; it never changes who signed in.
            if info.get("sub") == claims["sub"]:
                for name, value in info.items():
                    merged.setdefault(name, value)
            # Sign-in needs nothing from Pulse later: give the tokens back at once.
            await self.client.revoke(access_token, hint="access_token")
        email = merged.get("email")
        verified = merged.get("email_verified")
        if (
            not isinstance(email, str)
            or not email.strip()
            or len(email) > 320
            or not (verified is True or verified == "true")
        ):
            raise IdentityProviderEmailMissing("Pulse did not share a verified email address.")
        profile = PulseClaims.from_claims(self.client.issuer, merged)
        self._claims[callback_state] = profile
        while len(self._claims) > 256:
            self._claims.popitem(last=False)
        return VerifiedProviderAssertion(
            issuer=self.client.issuer,
            subject=str(claims["sub"]),
            audience=self.client.client_id,
            state=callback_state,
            nonce=transaction.nonce,
            authorization_type=transaction.authorization_type,
            email=email.strip(),
            email_verified=True,
            display_name=profile.name,
            given_name=profile.given_name,
            family_name=profile.family_name,
            picture_url=profile.picture,
        )


__all__ = [
    "ORG_LINK_SCOPES",
    "SIGN_IN_SCOPES",
    "Discovery",
    "PulseClaims",
    "PulseClient",
    "PulseOrg",
    "PulseSignInProvider",
    "jwk_to_pem",
    "normalize_issuer",
]
