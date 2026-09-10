"""Short-lived, signed browser transactions for external identity callbacks."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
from dataclasses import asdict, dataclass
from time import time
from urllib.parse import urlsplit
from uuid import UUID, uuid4

from ac_platform.identity.services import IssuedProviderAuthorization, ProviderAuthorizationType
from ac_platform.kernel.errors import DomainError

AUTH_TRANSACTION_MAX_AGE_SECONDS = 10 * 60
AUTH_TRANSACTION_FUTURE_SKEW_SECONDS = 30


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

    @classmethod
    def issue(
        cls,
        authorization_type: ProviderAuthorizationType,
        *,
        surface: str,
        return_path: str,
        consent_version: str | None = None,
        now: int | None = None,
    ) -> AuthTransaction:
        if surface not in {"learner", "admin", "coach"}:
            raise InvalidAuthTransaction("The requested application surface is not allowed.")
        return cls(
            transaction_id=uuid4(),
            authorization_type=authorization_type,
            surface=surface,
            state=secrets.token_urlsafe(32),
            nonce=secrets.token_urlsafe(32),
            pkce_verifier=secrets.token_urlsafe(64),
            return_path=normalize_return_path(return_path),
            issued_at=int(time() if now is None else now),
            consent_version=_normalize_consent_version(consent_version),
        )

    @classmethod
    def from_issued(
        cls,
        issued: IssuedProviderAuthorization,
        *,
        surface: str,
        return_path: str,
        consent_version: str | None = None,
    ) -> AuthTransaction:
        if surface not in {"learner", "admin", "coach"}:
            raise InvalidAuthTransaction("The requested application surface is not allowed.")
        return cls(
            transaction_id=issued.transaction_id,
            authorization_type=issued.authorization_type,
            surface=surface,
            state=issued.state,
            nonce=issued.nonce,
            pkce_verifier=issued.pkce_verifier,
            return_path=normalize_return_path(return_path),
            issued_at=int(issued.issued_at.timestamp()),
            consent_version=_normalize_consent_version(consent_version),
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
            if set(payload) not in (
                base_fields,
                base_fields | {"consent_version"},
            ):
                raise ValueError("unexpected transaction fields")
            if payload["v"] not in {1, 2}:
                raise ValueError("unsupported transaction version")
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
            )
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise InvalidAuthTransaction("The sign-in transaction payload is invalid.") from exc
        if transaction.surface not in {"learner", "admin", "coach"}:
            raise InvalidAuthTransaction("The requested application surface is not allowed.")
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


__all__ = [
    "AUTH_TRANSACTION_MAX_AGE_SECONDS",
    "AuthTransaction",
    "AuthTransactionCodec",
    "InvalidAuthTransaction",
    "normalize_return_path",
]
