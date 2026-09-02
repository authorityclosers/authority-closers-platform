"""Short-lived media token signing without provider-specific claims."""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

from ac_platform.media.errors import MediaForbidden


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _unb64(value: str) -> bytes:
    return base64.urlsafe_b64decode(value.encode("ascii") + b"=" * (-len(value) % 4))


class MediaSigner:
    """HMAC signer for opaque media upload/read/playback grants."""

    def __init__(self, secret: bytes | str) -> None:
        raw = secret.encode("utf-8") if isinstance(secret, str) else bytes(secret)
        if len(raw) < 32:
            raise ValueError("media signing secret must be at least 32 bytes")
        self._secret = raw

    def digest(self, token: str) -> bytes:
        return hmac.new(self._secret, token.encode("ascii"), hashlib.sha256).digest()

    def sign(
        self,
        claims: dict[str, Any],
        *,
        now: datetime,
        lifetime: timedelta,
        token_type: str,
        nonce: str | None = None,
    ) -> str:
        if lifetime <= timedelta(0):
            raise ValueError("media token lifetime must be positive")
        issued_at = int(now.astimezone(UTC).timestamp())
        payload = dict(claims)
        payload.update(
            {
                "typ": "AC-MEDIA",
                "token_type": token_type,
                "iat": issued_at,
                "exp": issued_at + int(lifetime.total_seconds()),
                "nonce": nonce or secrets.token_urlsafe(12),
            }
        )
        encoded_payload = _b64(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        )
        unsigned = f"AC-MEDIA.{encoded_payload}"
        signature = hmac.new(self._secret, unsigned.encode("ascii"), hashlib.sha256).digest()
        return f"{unsigned}.{_b64(signature)}"

    def verify(self, token: str, *, now: datetime, token_type: str) -> dict[str, Any]:
        try:
            if not isinstance(token, str) or len(token) > 4096:
                raise ValueError
            header, encoded_payload, encoded_signature = token.split(".", 2)
            unsigned = f"{header}.{encoded_payload}"
            expected = hmac.new(self._secret, unsigned.encode("ascii"), hashlib.sha256).digest()
            if header != "AC-MEDIA" or not hmac.compare_digest(expected, _unb64(encoded_signature)):
                raise ValueError
            payload = json.loads(_unb64(encoded_payload))
            if (
                not isinstance(payload, dict)
                or payload.get("typ") != "AC-MEDIA"
                or payload.get("token_type") != token_type
            ):
                raise ValueError
            if int(payload["exp"]) <= int(now.astimezone(UTC).timestamp()):
                raise ValueError
            return payload
        except (
            ValueError,
            TypeError,
            KeyError,
            json.JSONDecodeError,
            UnicodeError,
            binascii.Error,
        ):
            raise MediaForbidden("The media authorization token is invalid or expired.") from None


__all__ = ["MediaSigner"]
