"""Provider-neutral delivery, CORS, range, and signed URL policy."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from urllib.parse import parse_qs, quote, unquote, urlsplit

from ac_platform.media.contracts import (
    EphemeralMediaUrl,
    MediaAssetVersion,
    MediaAuthorizationContext,
)
from ac_platform.media.errors import MediaForbidden, MediaRangeError
from ac_platform.media.signing import MediaSigner

_ORIGIN_PATTERN = re.compile(r"^https?://[^\s/?#]+$")
_HEADER_TOKEN_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9-]{0,63}$")
_MAX_RANGE_BYTES = 8 * 1024 * 1024 * 1024


class RangeMode(StrEnum):
    DENY = "deny"
    SINGLE = "single"


@dataclass(frozen=True, slots=True)
class RangePolicy:
    """Safe representation of progressive byte-range behavior."""

    mode: RangeMode | str = RangeMode.SINGLE
    max_bytes: int = 8 * 1024 * 1024 * 1024

    def __post_init__(self) -> None:
        try:
            mode = RangeMode(self.mode)
        except ValueError as error:
            raise ValueError("range mode must be deny or single") from error
        if (
            isinstance(self.max_bytes, bool)
            or not isinstance(self.max_bytes, int)
            or self.max_bytes <= 0
            or self.max_bytes > _MAX_RANGE_BYTES
        ):
            raise ValueError("range policy max_bytes is outside the bounded limit")
        object.__setattr__(self, "mode", mode)

    @property
    def supports_range(self) -> bool:
        return self.mode is RangeMode.SINGLE

    def validate_header(self, value: str | None) -> tuple[int, int | None] | None:
        """Validate one RFC 9110 single byte range.

        Multiple ranges, suffix ranges, and malformed values are rejected to
        keep the media front door bounded and easy to audit.
        """

        if value is None:
            return None
        if not self.supports_range:
            raise MediaRangeError("byte ranges are not allowed for this delivery")
        normalized = value.strip()
        if not normalized.startswith("bytes=") or "," in normalized:
            raise MediaRangeError("only one byte range is supported")
        match = re.fullmatch(r"bytes=(\d+)-(\d*)", normalized)
        if match is None:
            raise MediaRangeError("the byte range is invalid")
        start = int(match.group(1))
        end = int(match.group(2)) if match.group(2) else None
        if start >= self.max_bytes or (end is not None and end < start):
            raise MediaRangeError("the byte range exceeds the delivery limit")
        if end is not None and end - start + 1 > self.max_bytes:
            raise MediaRangeError("the byte range exceeds the delivery limit")
        return start, end


@dataclass(frozen=True, slots=True)
class MediaCorsPolicy:
    """Exact-origin CORS policy for signed media delivery."""

    allowed_origins: tuple[str, ...]
    allow_credentials: bool = False
    allowed_methods: tuple[str, ...] = ("GET", "HEAD", "OPTIONS")
    allowed_headers: tuple[str, ...] = ("Accept", "Origin", "Range", "If-Range")
    exposed_headers: tuple[str, ...] = (
        "Accept-Ranges",
        "Content-Length",
        "Content-Range",
        "Content-Type",
        "ETag",
    )
    max_age_seconds: int = 600

    def __post_init__(self) -> None:
        if isinstance(self.allowed_origins, str):
            raise TypeError("media CORS origins must be a sequence")
        origins = tuple(
            origin.rstrip("/") if isinstance(origin, str) else origin
            for origin in self.allowed_origins
        )
        if not origins or len(origins) > 16:
            raise ValueError("media CORS policy requires one to sixteen origins")
        if len(set(origins)) != len(origins):
            raise ValueError("media CORS origins must be unique")
        for origin in origins:
            if origin == "*" or not _ORIGIN_PATTERN.fullmatch(origin):
                raise ValueError("media CORS origins must be exact HTTP(S) origins")
            parsed = urlsplit(origin)
            if parsed.username or parsed.password or parsed.path not in {"", "/"}:
                raise ValueError("media CORS origins must not contain credentials or paths")
            if parsed.scheme == "http" and parsed.hostname not in {
                "localhost",
                "127.0.0.1",
                "::1",
            }:
                raise ValueError("non-loopback media CORS origins must use HTTPS")
        for field_name, values in (
            ("allowed methods", self.allowed_methods),
            ("allowed headers", self.allowed_headers),
            ("exposed headers", self.exposed_headers),
        ):
            if (
                not values
                or len(values) > 32
                or any(
                    not isinstance(value, str) or not _HEADER_TOKEN_PATTERN.fullmatch(value)
                    for value in values
                )
            ):
                raise ValueError(f"media CORS {field_name} are invalid")
        if not isinstance(self.allow_credentials, bool):
            raise TypeError("media CORS allow_credentials must be a boolean")
        if self.max_age_seconds < 0 or self.max_age_seconds > 86_400:
            raise ValueError("media CORS max age is outside the bounded limit")
        object.__setattr__(self, "allowed_origins", origins)

    def allows_origin(self, origin: str | None) -> bool:
        return origin is not None and origin.rstrip("/") in self.allowed_origins

    def response_headers(self, origin: str | None) -> dict[str, str]:
        """Return CORS headers only for an exact configured origin."""

        if origin is None:
            return {}
        if not self.allows_origin(origin):
            raise MediaForbidden("the media request origin is not allowed")
        return {
            "Access-Control-Allow-Origin": origin.rstrip("/"),
            "Access-Control-Allow-Credentials": "true" if self.allow_credentials else "false",
            "Access-Control-Allow-Methods": ", ".join(self.allowed_methods),
            "Access-Control-Allow-Headers": ", ".join(self.allowed_headers),
            "Access-Control-Expose-Headers": ", ".join(self.exposed_headers),
            "Access-Control-Max-Age": str(self.max_age_seconds),
            "Vary": "Origin",
        }


@dataclass(frozen=True, slots=True)
class SignedMediaUrl:
    """Opaque short-lived delivery URL plus its non-authoritative metadata."""

    url: EphemeralMediaUrl
    expires_at: datetime
    media_version: MediaAssetVersion
    kind: str
    supports_range: bool = False
    token: str = field(default="", repr=False, compare=False)

    def __post_init__(self) -> None:
        if not isinstance(self.url, EphemeralMediaUrl):
            object.__setattr__(self, "url", EphemeralMediaUrl(str(self.url)))
        if not isinstance(self.media_version, MediaAssetVersion):
            raise TypeError("signed media URL media_version is invalid")
        if self.expires_at.tzinfo is None or self.expires_at.utcoffset() is None:
            raise ValueError("signed media URL expiry must be timezone-aware")
        if not self.kind.strip() or self.kind not in {"upload", "read", "playback"}:
            raise ValueError("signed media URL kind is unsupported")
        if not isinstance(self.supports_range, bool):
            raise TypeError("signed media URL supports_range must be a boolean")


class SignedMediaDeliveryPort:
    """HMAC-backed provider-neutral URL issuer for local/test delivery."""

    def __init__(
        self,
        *,
        signer: MediaSigner,
        delivery_origin: str,
        playback_ttl: timedelta = timedelta(minutes=15),
        range_policy: RangePolicy | None = None,
    ) -> None:
        origin = delivery_origin.rstrip("/")
        parsed = urlsplit(origin)
        if (
            parsed.scheme != "https"
            or not parsed.netloc
            or parsed.hostname is None
            or parsed.username
            or parsed.password
            or parsed.path not in {"", "/"}
        ):
            raise ValueError("media delivery origin must be an HTTPS origin")
        try:
            port = parsed.port
        except ValueError as error:
            raise ValueError("media delivery origin must contain a valid port") from error
        if port is not None and not 1 <= port <= 65535:
            raise ValueError("media delivery origin must contain a valid port")
        if playback_ttl <= timedelta(0) or playback_ttl > timedelta(hours=1):
            raise ValueError("media playback TTL must be between zero and one hour")
        self.signer = signer
        self.delivery_origin = origin
        self.playback_ttl = playback_ttl
        self.range_policy = range_policy or RangePolicy()

    def issue(
        self,
        *,
        authorization: MediaAuthorizationContext,
        activity_id: str,
        activity_version: str,
        media_version: MediaAssetVersion,
        object_key: str,
        now: datetime | None = None,
        kind: str = "playback",
        supports_range: bool | None = None,
    ) -> SignedMediaUrl:
        if kind not in {"read", "playback"}:
            raise ValueError("signed delivery kind must be read or playback")
        if supports_range is not None and not isinstance(supports_range, bool):
            raise TypeError("signed media URL supports_range must be a boolean")
        effective_supports_range = (
            self.range_policy.supports_range if supports_range is None else supports_range
        )
        if effective_supports_range and not self.range_policy.supports_range:
            raise MediaRangeError("byte ranges are not allowed for this delivery")
        if not object_key or ".." in object_key or "\\" in object_key or object_key.startswith("/"):
            raise ValueError("signed delivery object key is invalid")
        issued_at = now or datetime.now(UTC)
        if issued_at.tzinfo is None or issued_at.utcoffset() is None:
            raise ValueError("media delivery issue time must be timezone-aware")
        issued_at = issued_at.astimezone(UTC)
        expires_at = issued_at + self.playback_ttl
        token = self.signer.sign(
            {
                "tenant_id": authorization._binding[0],
                "person_id": authorization._binding[1],
                "session_id": authorization._binding[2],
                "activity_id": activity_id,
                "activity_version": activity_version,
                "asset_id": str(media_version.asset_id),
                "version_id": str(media_version.version_id),
                "key": object_key,
                "supports_range": effective_supports_range,
            },
            now=issued_at,
            lifetime=self.playback_ttl,
            token_type=kind,
        )
        encoded_key = quote(object_key, safe="")
        encoded_token = quote(token, safe="")
        url = EphemeralMediaUrl(
            f"{self.delivery_origin}/v1/media/{kind}/{encoded_key}?token={encoded_token}"
        )
        return SignedMediaUrl(
            url=url,
            expires_at=expires_at,
            media_version=media_version,
            kind=kind,
            supports_range=effective_supports_range,
            token=token,
        )

    def verify(
        self,
        signed: SignedMediaUrl,
        *,
        now: datetime | None = None,
        authorization: MediaAuthorizationContext | None = None,
        media_version: MediaAssetVersion | None = None,
    ) -> Mapping[str, object]:
        if not isinstance(signed, SignedMediaUrl):
            raise TypeError("signed media URL is invalid")
        current = now or datetime.now(UTC)
        if current.tzinfo is None or current.utcoffset() is None:
            raise ValueError("media delivery verification time must be timezone-aware")
        current = current.astimezone(UTC)
        try:
            claims = self.signer.verify(signed.token, now=current, token_type=signed.kind)
        except Exception as error:
            raise MediaForbidden("the signed media URL is invalid or expired") from error
        claim_key = claims.get("key")
        if (
            claims.get("asset_id") != str(signed.media_version.asset_id)
            or claims.get("version_id") != str(signed.media_version.version_id)
            or not isinstance(claim_key, str)
            or not claim_key
            or ".." in claim_key
            or "\\" in claim_key
            or claim_key.startswith("/")
        ):
            raise MediaForbidden("the signed media URL is outside the media version scope")
        claimed_supports_range = claims.get("supports_range")
        if (
            not isinstance(claimed_supports_range, bool)
            or claimed_supports_range != signed.supports_range
            or claimed_supports_range
            and not self.range_policy.supports_range
        ):
            raise MediaForbidden("the signed media URL range policy is invalid")
        parsed_url = urlsplit(signed.url.value)
        expected_path_prefix = f"/v1/media/{signed.kind}/"
        query = parse_qs(parsed_url.query, keep_blank_values=True)
        if (
            f"{parsed_url.scheme}://{parsed_url.netloc}".rstrip("/") != self.delivery_origin
            or not parsed_url.path.startswith(expected_path_prefix)
            or unquote(parsed_url.path[len(expected_path_prefix) :]) != claim_key
            or query.get("token") != [signed.token]
        ):
            raise MediaForbidden("the signed media URL metadata is invalid")
        if authorization is not None:
            expected = {
                "tenant_id": authorization._binding[0],
                "person_id": authorization._binding[1],
                "session_id": authorization._binding[2],
            }
            if any(claims.get(key) != value for key, value in expected.items()):
                raise MediaForbidden("the signed media URL is outside the authorization scope")
        if media_version is not None and (
            claims.get("asset_id") != str(media_version.asset_id)
            or claims.get("version_id") != str(media_version.version_id)
        ):
            raise MediaForbidden("the signed media URL is outside the media version scope")
        return claims


# Alias used by callers that prefer the implementation name.
HmacSignedMediaDelivery = SignedMediaDeliveryPort


__all__ = [
    "HmacSignedMediaDelivery",
    "MediaCorsPolicy",
    "RangeMode",
    "RangePolicy",
    "SignedMediaDeliveryPort",
    "SignedMediaUrl",
]
