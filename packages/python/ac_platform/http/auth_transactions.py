"""Short-lived, signed browser transactions for external identity callbacks."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import secrets
from dataclasses import asdict, dataclass
from time import time
from urllib.parse import parse_qsl, urlsplit
from uuid import UUID, uuid4

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from ac_platform.identity.services import IssuedProviderAuthorization, ProviderAuthorizationType
from ac_platform.kernel.errors import DomainError

AUTH_TRANSACTION_MAX_AGE_SECONDS = 10 * 60
AUTH_TRANSACTION_FUTURE_SKEW_SECONDS = 30
SALES_XRAY_COMPLETION_RECEIPT_TTL_SECONDS = 180
# The Sales Xray Android app signs in with Google in a Chrome Custom Tab (Google
# refuses embedded web views) and takes the result back with a sealed one-time
# handoff code. The app proves it started the sign-in with its own PKCE-style
# verifier, so a code caught by another app on the phone is useless.
SALES_XRAY_APP_HANDOFF_TTL_SECONDS = 60
SALES_XRAY_APP_CHALLENGE_PATTERN = re.compile(r"[A-Za-z0-9_-]{43}")
SALES_XRAY_APP_VERIFIER_PATTERN = re.compile(r"[A-Za-z0-9._~-]{43,128}")
_SALES_XRAY_APP_HANDOFF_MAX_LENGTH = 1024
_SALES_XRAY_APP_HANDOFF_AAD = b"ac-platform:sales-xray-app-handoff:v1"


# Identity providers a sign-in transaction can be bound to. A transaction issued
# for one provider is refused at another provider's callback.
AUTH_PROVIDERS = frozenset({"google", "facebook", "apple"})


class InvalidAuthTransaction(DomainError):
    code = "invalid_auth_transaction"
    title = "The sign-in transaction is invalid"
    status = 400


def _normalize_consent_version(value: str | None) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise InvalidAuthTransaction("The consent version is invalid.")
    normalized = value.strip()
    if not 1 <= len(normalized) <= 64 or "\x00" in normalized:
        raise InvalidAuthTransaction("The consent version is invalid.")
    return normalized


def _normalize_age_attested(value: bool, consent_version: str | None) -> bool:
    if type(value) is not bool:
        raise InvalidAuthTransaction("The learner age acknowledgement is invalid.")
    if value and consent_version is None:
        raise InvalidAuthTransaction("The age acknowledgement requires a consent version.")
    return value


def _normalize_app_challenge(value: object, surface: str) -> str | None:
    if value is None:
        return None
    if surface != "sales_xray":
        raise InvalidAuthTransaction("Only the Sales Xray app can take a sign-in back.")
    if not isinstance(value, str) or SALES_XRAY_APP_CHALLENGE_PATTERN.fullmatch(value) is None:
        raise InvalidAuthTransaction("The app sign-in challenge is invalid.")
    return value


def _normalize_provider(value: object, surface: str) -> str:
    if value is None:
        return "google"
    if not isinstance(value, str) or value not in AUTH_PROVIDERS:
        raise InvalidAuthTransaction("The sign-in provider is not allowed.")
    if value != "google" and surface != "sales_xray":
        raise InvalidAuthTransaction("This sign-in provider is only offered by Sales Xray.")
    return value


def _base64url_encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _base64url_decode(value: str) -> bytes:
    if not value or not value.isascii():
        raise InvalidAuthTransaction("The sign-in transaction is malformed.")
    try:
        return base64.b64decode(
            value.encode("ascii") + b"=" * (-len(value) % 4),
            altchars=b"-_",
            validate=True,
        )
    except (ValueError, TypeError) as exc:
        raise InvalidAuthTransaction("The sign-in transaction is malformed.") from exc


def normalize_return_path(candidate: str) -> str:
    """Accept only a bounded absolute path on an Authority Closers surface."""

    if len(candidate) > 512 or not candidate.startswith("/") or candidate.startswith("//"):
        raise InvalidAuthTransaction("The requested return path is not allowed.")
    if "\\" in candidate or "\x00" in candidate:
        raise InvalidAuthTransaction("The requested return path is not allowed.")
    parsed = urlsplit(candidate)
    if parsed.scheme or parsed.netloc or parsed.fragment:
        raise InvalidAuthTransaction("The requested return path is not allowed.")
    return candidate


def sales_xray_completion_flow_id(return_path: str) -> UUID | None:
    """Extract only the UUID from the exact signed Sales Xray completion path."""

    try:
        normalized = normalize_return_path(return_path)
        parsed = urlsplit(normalized)
        query = parse_qsl(parsed.query, keep_blank_values=True, strict_parsing=True)
        if parsed.path != "/auth/complete" or len(query) != 1 or query[0][0] != "flow":
            return None
        flow_id = UUID(query[0][1])
        if str(flow_id) != query[0][1].lower():
            return None
        return flow_id
    except (InvalidAuthTransaction, ValueError):
        return None


@dataclass(frozen=True, slots=True)
class SalesXrayCompletionReceipt:
    flow_id: UUID
    session_id: UUID
    surface: str
    issued_at: int
    expires_at: int


class SalesXrayCompletionReceiptCodec:
    """Domain-separated signed completion cookies, independent of session credentials."""

    def __init__(self, transaction_secret: bytes | str) -> None:
        if isinstance(transaction_secret, str):
            transaction_secret = transaction_secret.encode("utf-8")
        if len(transaction_secret) < 32:
            raise ValueError("OAuth transaction secret must contain at least 32 bytes")
        self._secret = hmac.new(
            transaction_secret,
            b"ac-platform:sales-xray-completion-receipt:v1\x00",
            hashlib.sha256,
        ).digest()

    def encode(
        self,
        *,
        flow_id: UUID,
        session_id: UUID,
        now: int | None = None,
    ) -> str:
        issued_at = int(time() if now is None else now)
        payload = {
            "v": 1,
            "flow_id": str(flow_id),
            "session_id": str(session_id),
            "surface": "sales_xray",
            "issued_at": issued_at,
            "expires_at": issued_at + SALES_XRAY_COMPLETION_RECEIPT_TTL_SECONDS,
        }
        serialized = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        encoded_payload = _base64url_encode(serialized)
        signature = hmac.new(self._secret, encoded_payload.encode("ascii"), hashlib.sha256).digest()
        return f"{encoded_payload}.{_base64url_encode(signature)}"

    def decode(self, value: str, *, now: int | None = None) -> SalesXrayCompletionReceipt:
        try:
            encoded_payload, encoded_signature = value.split(".", maxsplit=1)
        except ValueError as exc:
            raise InvalidAuthTransaction("The completion receipt is malformed.") from exc
        supplied_signature = _base64url_decode(encoded_signature)
        expected_signature = hmac.new(
            self._secret,
            encoded_payload.encode("ascii"),
            hashlib.sha256,
        ).digest()
        if not hmac.compare_digest(supplied_signature, expected_signature):
            raise InvalidAuthTransaction("The completion receipt signature is invalid.")
        try:
            payload = json.loads(_base64url_decode(encoded_payload))
            expected_fields = {"v", "flow_id", "session_id", "surface", "issued_at", "expires_at"}
            if not isinstance(payload, dict) or set(payload) != expected_fields:
                raise ValueError("unexpected completion receipt fields")
            if payload["v"] != 1 or payload["surface"] != "sales_xray":
                raise ValueError("unsupported completion receipt")
            if type(payload["issued_at"]) is not int or type(payload["expires_at"]) is not int:
                raise ValueError("invalid completion receipt time")
            receipt = SalesXrayCompletionReceipt(
                flow_id=UUID(str(payload["flow_id"])),
                session_id=UUID(str(payload["session_id"])),
                surface="sales_xray",
                issued_at=payload["issued_at"],
                expires_at=payload["expires_at"],
            )
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise InvalidAuthTransaction("The completion receipt payload is invalid.") from exc
        current_time = int(time() if now is None else now)
        if (
            receipt.expires_at - receipt.issued_at != SALES_XRAY_COMPLETION_RECEIPT_TTL_SECONDS
            or receipt.issued_at > current_time + AUTH_TRANSACTION_FUTURE_SKEW_SECONDS
            or receipt.expires_at <= current_time
        ):
            raise InvalidAuthTransaction("The completion receipt has expired or is invalid.")
        return receipt


@dataclass(frozen=True, slots=True)
class AuthTransaction:
    transaction_id: UUID
    authorization_type: ProviderAuthorizationType
    surface: str
    state: str
    nonce: str
    pkce_verifier: str
    return_path: str
    issued_at: int
    consent_version: str | None = None
    # Explicit confirmation of the canonical 18+ learner acknowledgement.
    # Missing values in previously issued signed transactions default to false.
    age_attested: bool = False
    # Set only when the Sales Xray app started this sign-in in a Custom Tab: the
    # callback then hands the session to the app instead of the browser.
    app_challenge: str | None = None
    # The identity provider this transaction was issued for. Older signed
    # transactions carry no value and are Google's.
    provider: str = "google"

    @classmethod
    def issue(
        cls,
        authorization_type: ProviderAuthorizationType,
        *,
        surface: str,
        return_path: str,
        consent_version: str | None = None,
        age_attested: bool = False,
        app_challenge: str | None = None,
        provider: str = "google",
        now: int | None = None,
    ) -> AuthTransaction:
        if surface not in {"learner", "admin", "coach", "sales_xray"}:
            raise InvalidAuthTransaction("The requested application surface is not allowed.")
        normalized_consent = _normalize_consent_version(consent_version)
        return cls(
            transaction_id=uuid4(),
            authorization_type=authorization_type,
            surface=surface,
            state=secrets.token_urlsafe(32),
            nonce=secrets.token_urlsafe(32),
            pkce_verifier=secrets.token_urlsafe(64),
            return_path=normalize_return_path(return_path),
            issued_at=int(time() if now is None else now),
            consent_version=normalized_consent,
            age_attested=_normalize_age_attested(age_attested, normalized_consent),
            app_challenge=_normalize_app_challenge(app_challenge, surface),
            provider=_normalize_provider(provider, surface),
        )

    @classmethod
    def from_issued(
        cls,
        issued: IssuedProviderAuthorization,
        *,
        surface: str,
        return_path: str,
        consent_version: str | None = None,
        age_attested: bool = False,
        app_challenge: str | None = None,
        provider: str = "google",
    ) -> AuthTransaction:
        if surface not in {"learner", "admin", "coach", "sales_xray"}:
            raise InvalidAuthTransaction("The requested application surface is not allowed.")
        normalized_consent = _normalize_consent_version(consent_version)
        return cls(
            transaction_id=issued.transaction_id,
            authorization_type=issued.authorization_type,
            surface=surface,
            state=issued.state,
            nonce=issued.nonce,
            pkce_verifier=issued.pkce_verifier,
            return_path=normalize_return_path(return_path),
            issued_at=int(issued.issued_at.timestamp()),
            consent_version=normalized_consent,
            age_attested=_normalize_age_attested(age_attested, normalized_consent),
            app_challenge=_normalize_app_challenge(app_challenge, surface),
            provider=_normalize_provider(provider, surface),
        )

    @property
    def pkce_challenge(self) -> str:
        return _base64url_encode(hashlib.sha256(self.pkce_verifier.encode("ascii")).digest())


class AuthTransactionCodec:
    """HMAC-authenticate callback state without persisting provider credentials."""

    def __init__(self, secret: bytes | str) -> None:
        if isinstance(secret, str):
            secret = secret.encode("utf-8")
        if len(secret) < 32:
            raise ValueError("OAuth transaction secret must contain at least 32 bytes")
        self._secret = secret

    def encode(self, transaction: AuthTransaction) -> str:
        payload = {
            "v": 2,
            **asdict(transaction),
            "transaction_id": str(transaction.transaction_id),
            "authorization_type": transaction.authorization_type.value,
        }
        if transaction.app_challenge is None:
            # Ordinary browser transactions keep exactly their previous shape.
            payload.pop("app_challenge")
        if transaction.provider == "google":
            # Google transactions keep exactly their previous shape too.
            payload.pop("provider")
        serialized = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        encoded_payload = _base64url_encode(serialized)
        signature = hmac.new(self._secret, encoded_payload.encode("ascii"), hashlib.sha256).digest()
        return f"{encoded_payload}.{_base64url_encode(signature)}"

    def decode(self, value: str, *, now: int | None = None) -> AuthTransaction:
        try:
            encoded_payload, encoded_signature = value.split(".", maxsplit=1)
        except ValueError as exc:
            raise InvalidAuthTransaction("The sign-in transaction is malformed.") from exc
        supplied_signature = _base64url_decode(encoded_signature)
        expected_signature = hmac.new(
            self._secret,
            encoded_payload.encode("ascii"),
            hashlib.sha256,
        ).digest()
        if not hmac.compare_digest(supplied_signature, expected_signature):
            raise InvalidAuthTransaction("The sign-in transaction signature is invalid.")
        try:
            payload = json.loads(_base64url_decode(encoded_payload))
            base_fields = {
                "v",
                "transaction_id",
                "authorization_type",
                "surface",
                "state",
                "nonce",
                "pkce_verifier",
                "return_path",
                "issued_at",
            }
            known_shapes = (
                base_fields,
                base_fields | {"consent_version"},
                base_fields | {"consent_version", "age_attested"},
                base_fields | {"consent_version", "age_attested", "app_challenge"},
            )
            # A Facebook or Apple transaction adds "provider" to any of them.
            if set(payload) - {"provider"} not in known_shapes:
                raise ValueError("unexpected transaction fields")
            if payload["v"] not in {1, 2}:
                raise ValueError("unsupported transaction version")
            age_attested = payload.get("age_attested", False)
            if type(age_attested) is not bool:
                raise ValueError("invalid age attestation")
            transaction = AuthTransaction(
                transaction_id=UUID(str(payload["transaction_id"])),
                authorization_type=ProviderAuthorizationType(payload["authorization_type"]),
                surface=str(payload["surface"]),
                state=str(payload["state"]),
                nonce=str(payload["nonce"]),
                pkce_verifier=str(payload["pkce_verifier"]),
                return_path=normalize_return_path(str(payload["return_path"])),
                issued_at=int(payload["issued_at"]),
                consent_version=_normalize_consent_version(payload.get("consent_version")),
                age_attested=age_attested,
                app_challenge=_normalize_app_challenge(
                    payload.get("app_challenge"),
                    str(payload["surface"]),
                ),
                provider=_normalize_provider(payload.get("provider"), str(payload["surface"])),
            )
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise InvalidAuthTransaction("The sign-in transaction payload is invalid.") from exc
        if transaction.surface not in {"learner", "admin", "coach", "sales_xray"}:
            raise InvalidAuthTransaction("The requested application surface is not allowed.")
        if transaction.age_attested and transaction.consent_version is None:
            raise InvalidAuthTransaction("The age attestation is not bound to learner consent.")
        for value_name, token in (
            ("state", transaction.state),
            ("nonce", transaction.nonce),
            ("PKCE verifier", transaction.pkce_verifier),
        ):
            if (
                len(token) < 32
                or len(token) > 160
                or not token.isascii()
                or any(character.isspace() for character in token)
            ):
                raise InvalidAuthTransaction(f"The transaction {value_name} is invalid.")
        current_time = int(time() if now is None else now)
        if transaction.issued_at > current_time + AUTH_TRANSACTION_FUTURE_SKEW_SECONDS:
            raise InvalidAuthTransaction("The sign-in transaction timestamp is invalid.")
        if current_time - transaction.issued_at > AUTH_TRANSACTION_MAX_AGE_SECONDS:
            raise InvalidAuthTransaction("The sign-in transaction has expired.")
        return transaction


@dataclass(frozen=True, slots=True)
class SalesXrayAppHandoff:
    session_token: str
    session_id: UUID
    flow_id: UUID
    app_challenge: str
    issued_at: int
    expires_at: int


class SalesXrayAppHandoffCodec:
    """Sealed (encrypted and authenticated) one-time sign-in handoff to the Sales Xray app.

    The code carries a session that no browser holds. Only this server can read
    it, it lives 60 seconds, and it is redeemed once: the exchange revokes that
    session and issues a fresh one to the app's web view.
    """

    def __init__(self, transaction_secret: bytes | str) -> None:
        if isinstance(transaction_secret, str):
            transaction_secret = transaction_secret.encode("utf-8")
        if len(transaction_secret) < 32:
            raise ValueError("OAuth transaction secret must contain at least 32 bytes")
        self._aead = AESGCM(
            hmac.new(
                transaction_secret,
                b"ac-platform:sales-xray-app-handoff:v1\x00",
                hashlib.sha256,
            ).digest()
        )

    def encode(
        self,
        *,
        session_token: str,
        session_id: UUID,
        flow_id: UUID,
        app_challenge: str,
        now: int | None = None,
    ) -> str:
        if SALES_XRAY_APP_CHALLENGE_PATTERN.fullmatch(app_challenge) is None:
            raise InvalidAuthTransaction("The app sign-in challenge is invalid.")
        issued_at = int(time() if now is None else now)
        payload = {
            "v": 1,
            "session_token": session_token,
            "session_id": str(session_id),
            "flow_id": str(flow_id),
            "app_challenge": app_challenge,
            "issued_at": issued_at,
            "expires_at": issued_at + SALES_XRAY_APP_HANDOFF_TTL_SECONDS,
        }
        serialized = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        nonce = secrets.token_bytes(12)
        return _base64url_encode(
            nonce + self._aead.encrypt(nonce, serialized, _SALES_XRAY_APP_HANDOFF_AAD)
        )

    def decode(self, value: str, *, now: int | None = None) -> SalesXrayAppHandoff:
        if not isinstance(value, str) or len(value) > _SALES_XRAY_APP_HANDOFF_MAX_LENGTH:
            raise InvalidAuthTransaction("The app sign-in code is malformed.")
        sealed = _base64url_decode(value)
        if len(sealed) < 12 + 16:
            raise InvalidAuthTransaction("The app sign-in code is malformed.")
        try:
            serialized = self._aead.decrypt(sealed[:12], sealed[12:], _SALES_XRAY_APP_HANDOFF_AAD)
        except InvalidTag as exc:
            raise InvalidAuthTransaction("The app sign-in code is invalid.") from exc
        try:
            payload = json.loads(serialized)
            expected_fields = {
                "v",
                "session_token",
                "session_id",
                "flow_id",
                "app_challenge",
                "issued_at",
                "expires_at",
            }
            if not isinstance(payload, dict) or set(payload) != expected_fields:
                raise ValueError("unexpected app handoff fields")
            if payload["v"] != 1:
                raise ValueError("unsupported app handoff")
            if type(payload["issued_at"]) is not int or type(payload["expires_at"]) is not int:
                raise ValueError("invalid app handoff time")
            if not isinstance(payload["session_token"], str) or not isinstance(
                payload["app_challenge"], str
            ):
                raise ValueError("invalid app handoff values")
            handoff = SalesXrayAppHandoff(
                session_token=payload["session_token"],
                session_id=UUID(str(payload["session_id"])),
                flow_id=UUID(str(payload["flow_id"])),
                app_challenge=payload["app_challenge"],
                issued_at=payload["issued_at"],
                expires_at=payload["expires_at"],
            )
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise InvalidAuthTransaction("The app sign-in code payload is invalid.") from exc
        current_time = int(time() if now is None else now)
        if (
            handoff.expires_at - handoff.issued_at != SALES_XRAY_APP_HANDOFF_TTL_SECONDS
            or handoff.issued_at > current_time + AUTH_TRANSACTION_FUTURE_SKEW_SECONDS
            or handoff.expires_at <= current_time
        ):
            raise InvalidAuthTransaction("The app sign-in code has expired or is invalid.")
        return handoff


# Apple posts its sign-in result cross-site (response_mode=form_post), so the
# SameSite=Lax transaction cookie is not sent with that POST. The POST only seals
# what Apple sent into this short cookie and redirects to a same-site GET, where
# the normal callback checks run.
APPLE_FORM_POST_TTL_SECONDS = 120
_APPLE_FORM_POST_AAD = b"ac-platform:apple-form-post:v1"
_APPLE_FORM_POST_MAX_LENGTH = 6000


@dataclass(frozen=True, slots=True)
class AppleFormPost:
    state: str
    code: str | None
    error: str | None
    first_name: str | None
    last_name: str | None
    issued_at: int
    expires_at: int


class AppleFormPostCodec:
    """Sealed (encrypted and authenticated) copy of one Apple form_post, two minutes."""

    def __init__(self, transaction_secret: bytes | str) -> None:
        if isinstance(transaction_secret, str):
            transaction_secret = transaction_secret.encode("utf-8")
        if len(transaction_secret) < 32:
            raise ValueError("OAuth transaction secret must contain at least 32 bytes")
        self._aead = AESGCM(
            hmac.new(
                transaction_secret,
                b"ac-platform:apple-form-post:v1\x00",
                hashlib.sha256,
            ).digest()
        )

    def encode(
        self,
        *,
        state: str,
        code: str | None,
        error: str | None,
        first_name: str | None = None,
        last_name: str | None = None,
        now: int | None = None,
    ) -> str:
        issued_at = int(time() if now is None else now)
        payload = {
            "v": 1,
            "state": state,
            "code": code,
            "error": error,
            "first_name": first_name,
            "last_name": last_name,
            "issued_at": issued_at,
            "expires_at": issued_at + APPLE_FORM_POST_TTL_SECONDS,
        }
        serialized = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        nonce = secrets.token_bytes(12)
        sealed = _base64url_encode(
            nonce + self._aead.encrypt(nonce, serialized, _APPLE_FORM_POST_AAD)
        )
        if len(sealed) > _APPLE_FORM_POST_MAX_LENGTH:
            raise InvalidAuthTransaction("The Apple sign-in result is too large.")
        return sealed

    def decode(self, value: str, *, now: int | None = None) -> AppleFormPost:
        if not isinstance(value, str) or len(value) > _APPLE_FORM_POST_MAX_LENGTH:
            raise InvalidAuthTransaction("The Apple sign-in result is malformed.")
        sealed = _base64url_decode(value)
        if len(sealed) < 12 + 16:
            raise InvalidAuthTransaction("The Apple sign-in result is malformed.")
        try:
            serialized = self._aead.decrypt(sealed[:12], sealed[12:], _APPLE_FORM_POST_AAD)
        except InvalidTag as exc:
            raise InvalidAuthTransaction("The Apple sign-in result is invalid.") from exc
        try:
            payload = json.loads(serialized)
            expected = {
                "v",
                "state",
                "code",
                "error",
                "first_name",
                "last_name",
                "issued_at",
                "expires_at",
            }
            if not isinstance(payload, dict) or set(payload) != expected or payload["v"] != 1:
                raise ValueError("unexpected Apple form_post fields")
            for name in ("code", "error", "first_name", "last_name"):
                if payload[name] is not None and not isinstance(payload[name], str):
                    raise ValueError("invalid Apple form_post value")
            if not isinstance(payload["state"], str):
                raise ValueError("invalid Apple form_post state")
            if type(payload["issued_at"]) is not int or type(payload["expires_at"]) is not int:
                raise ValueError("invalid Apple form_post time")
            result = AppleFormPost(
                state=payload["state"],
                code=payload["code"],
                error=payload["error"],
                first_name=payload["first_name"],
                last_name=payload["last_name"],
                issued_at=payload["issued_at"],
                expires_at=payload["expires_at"],
            )
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise InvalidAuthTransaction("The Apple sign-in result is invalid.") from exc
        current_time = int(time() if now is None else now)
        if (
            result.expires_at - result.issued_at != APPLE_FORM_POST_TTL_SECONDS
            or result.issued_at > current_time + AUTH_TRANSACTION_FUTURE_SKEW_SECONDS
            or result.expires_at <= current_time
        ):
            raise InvalidAuthTransaction("The Apple sign-in result has expired.")
        return result


def sales_xray_app_verifier_matches(app_challenge: str, verifier: str) -> bool:
    """RFC 7636 S256: the app's verifier must hash to the challenge it started with."""

    if SALES_XRAY_APP_VERIFIER_PATTERN.fullmatch(verifier) is None:
        return False
    expected = _base64url_encode(hashlib.sha256(verifier.encode("ascii")).digest())
    return hmac.compare_digest(expected, app_challenge)


__all__ = [
    "APPLE_FORM_POST_TTL_SECONDS",
    "AUTH_PROVIDERS",
    "AUTH_TRANSACTION_MAX_AGE_SECONDS",
    "AppleFormPost",
    "AppleFormPostCodec",
    "SALES_XRAY_APP_HANDOFF_TTL_SECONDS",
    "SALES_XRAY_COMPLETION_RECEIPT_TTL_SECONDS",
    "AuthTransaction",
    "AuthTransactionCodec",
    "InvalidAuthTransaction",
    "SalesXrayAppHandoff",
    "SalesXrayAppHandoffCodec",
    "SalesXrayCompletionReceipt",
    "SalesXrayCompletionReceiptCodec",
    "normalize_return_path",
    "sales_xray_app_verifier_matches",
    "sales_xray_completion_flow_id",
]
