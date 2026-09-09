"""Provider-neutral, ephemeral media delivery contracts.

This module deliberately contains no persistence, authorization, URL signing,
storage, DNS, or HTTP route implementation.  A caller must supply an already
authorized activity/media version.  Adapter output is delivery metadata for a
short-lived playback window; it is not canonical media identity or learning
progress.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import InitVar, dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Protocol, cast, runtime_checkable
from urllib.parse import urlsplit

from ac_platform.media.errors import (
    MediaAuthorizationMismatchError,
    MediaExpiredError,
    MediaNotYetValidError,
)

_OPAQUE_IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_LANGUAGE_PATTERN = re.compile(r"^[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})*$")
_MIME_PATTERN = re.compile(r"^[a-z0-9!#$&^_.+-]+/[a-z0-9!#$&^_.+-]+$")


def _opaque_identifier(value: str, *, field: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field} must be a string")
    normalized = value.strip()
    if not _OPAQUE_IDENTIFIER_PATTERN.fullmatch(normalized):
        raise ValueError(f"{field} must be a bounded opaque identifier")
    return normalized


def _language(value: str, *, field: str = "language") -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field} must be a string")
    normalized = value.strip()
    if not _LANGUAGE_PATTERN.fullmatch(normalized):
        raise ValueError(f"{field} must be a valid language tag")
    return normalized


def _label(value: str, *, field: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field} must be a string")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field} must not be blank")
    if len(normalized) > 200:
        raise ValueError(f"{field} exceeds 200 characters")
    return normalized


def _mime_type(value: str, *, field: str = "mime_type") -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field} must be a string")
    normalized = value.strip().lower()
    if not _MIME_PATTERN.fullmatch(normalized):
        raise ValueError(f"{field} must be a valid MIME type")
    return normalized


def _ephemeral_url(value: str, *, field: str = "url", allow_loopback_http: bool = False) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field} must be a string")
    if any(ord(character) < 0x20 or ord(character) == 0x7F for character in value):
        raise ValueError(f"{field} must not contain control characters")
    if any(character.isspace() for character in value):
        raise ValueError(f"{field} must not contain whitespace")
    normalized = value.strip()
    try:
        parsed = urlsplit(normalized)
    except ValueError as error:
        raise ValueError(f"{field} must be a valid HTTPS URL") from error
    loopback_http = (
        allow_loopback_http is True
        and parsed.scheme == "http"
        and parsed.hostname in {"127.0.0.1", "localhost", "learner.localhost"}
    )
    if (
        (parsed.scheme != "https" and not loopback_http)
        or not parsed.netloc
        or parsed.hostname is None
    ):
        raise ValueError(f"{field} must be an absolute HTTPS URL")
    try:
        port = parsed.port
    except ValueError as error:
        raise ValueError(f"{field} must contain a valid port") from error
    if port is not None and not 1 <= port <= 65535:
        raise ValueError(f"{field} must contain a valid port")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError(f"{field} must not contain credentials")
    if "#" in normalized:
        raise ValueError(f"{field} must not contain a URL fragment")
    return normalized


def _aware_utc(value: datetime, *, field: str) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError(f"{field} must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field} must be timezone-aware")
    return value.astimezone(UTC)


def _now(value: datetime | None) -> datetime:
    return _aware_utc(value if value is not None else datetime.now(UTC), field="now")


def _positive_int(value: int, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{field} must be a positive integer")
    return value


def _nonnegative_int(value: int, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{field} must be a non-negative integer")
    return value


def _require_instance[T](value: object, expected: type[T], *, field: str) -> T:
    if not isinstance(value, expected):
        raise TypeError(f"{field} must be a {expected.__name__}")
    return value


def _tuple_of[T](value: object, expected: type[T], *, field: str) -> tuple[T, ...]:
    if isinstance(value, str | bytes | bytearray) or not isinstance(value, Iterable):
        raise TypeError(f"{field} must be an iterable of {expected.__name__}")
    items = tuple(cast(Iterable[object], value))
    if any(not isinstance(item, expected) for item in items):
        raise TypeError(f"{field} must contain only {expected.__name__} values")
    return tuple(cast(T, item) for item in items)


class MediaDeliveryKind(StrEnum):
    """Delivery representations understood by the learner player."""

    HLS = "hls"
    PROGRESSIVE = "progressive"


class TranscriptFormat(StrEnum):
    """Provider-neutral transcript representations."""

    TEXT = "text"
    WEBVTT = "webvtt"
    JSON = "json"


@dataclass(frozen=True, slots=True)
class MediaAssetId:
    """Stable application-owned identity for a logical media asset."""

    value: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "value", _opaque_identifier(self.value, field="asset_id"))

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True)
class MediaVersionId:
    """Stable application-owned identity for an immutable media version."""

    value: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "value", _opaque_identifier(self.value, field="version_id"))

    def __str__(self) -> str:
        return self.value


def _coerce_asset_id(value: object, *, field: str) -> MediaAssetId:
    if isinstance(value, MediaAssetId):
        return value
    if isinstance(value, str):
        return MediaAssetId(value)
    raise TypeError(f"{field} must be a MediaAssetId or string")


def _coerce_version_id(value: object, *, field: str) -> MediaVersionId:
    if isinstance(value, MediaVersionId):
        return value
    if isinstance(value, str):
        return MediaVersionId(value)
    raise TypeError(f"{field} must be a MediaVersionId or string")


_AUTHORIZATION_CONTEXT_SEAL = object()


@dataclass(frozen=True, slots=True, init=False)
class MediaAuthorizationContext:
    """Opaque server-created binding for one authorized playback scope.

    The binding stores tenant, person, and session identifiers privately.  The
    delivery layer can compare contexts for equality without interpreting
    membership, entitlement, or other protected business semantics.
    """

    _binding: tuple[str, str, str] = field(repr=False)

    def __init__(self, *, _binding: tuple[str, str, str], _seal: object) -> None:
        if _seal is not _AUTHORIZATION_CONTEXT_SEAL:
            raise TypeError("media authorization contexts must be created by the server factory")
        object.__setattr__(self, "_binding", _binding)

    @classmethod
    def _from_server_authorization(
        cls,
        *,
        tenant_id: str,
        person_id: str,
        session_id: str,
    ) -> MediaAuthorizationContext:
        return cls(
            _binding=(
                _opaque_identifier(tenant_id, field="tenant_id"),
                _opaque_identifier(person_id, field="person_id"),
                _opaque_identifier(session_id, field="session_id"),
            ),
            _seal=_AUTHORIZATION_CONTEXT_SEAL,
        )


def create_media_authorization_context(
    *,
    tenant_id: str,
    person_id: str,
    session_id: str,
) -> MediaAuthorizationContext:
    """Create the opaque context supplied by a trusted authorization layer."""

    return MediaAuthorizationContext._from_server_authorization(
        tenant_id=tenant_id,
        person_id=person_id,
        session_id=session_id,
    )


@dataclass(frozen=True, slots=True)
class MediaAssetVersion:
    """An immutable logical asset/version pair, independent of any provider."""

    asset_id: MediaAssetId
    version_id: MediaVersionId

    def __post_init__(self) -> None:
        object.__setattr__(self, "asset_id", _coerce_asset_id(self.asset_id, field="asset_id"))
        object.__setattr__(
            self,
            "version_id",
            _coerce_version_id(self.version_id, field="version_id"),
        )


@dataclass(frozen=True, slots=True)
class EphemeralMediaUrl:
    """A non-authoritative delivery URL returned for a short-lived window."""

    value: str
    allow_loopback_http: InitVar[bool] = field(default=False, kw_only=True)

    def __post_init__(self, allow_loopback_http: bool) -> None:
        object.__setattr__(
            self, "value", _ephemeral_url(self.value, allow_loopback_http=allow_loopback_http)
        )

    def __str__(self) -> str:
        return self.value


def _coerce_url(value: object, *, field: str) -> EphemeralMediaUrl:
    if isinstance(value, EphemeralMediaUrl):
        return value
    if isinstance(value, str):
        return EphemeralMediaUrl(value)
    raise TypeError(f"{field} must be an EphemeralMediaUrl or string")


@dataclass(frozen=True, slots=True)
class MediaDeliveryDescriptor:
    """One ephemeral primary or fallback delivery representation."""

    kind: MediaDeliveryKind
    url: EphemeralMediaUrl
    supports_range: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.kind, MediaDeliveryKind):
            object.__setattr__(self, "kind", MediaDeliveryKind(self.kind))
        object.__setattr__(self, "url", _coerce_url(self.url, field="delivery.url"))
        if not isinstance(self.supports_range, bool):
            raise TypeError("supports_range must be a boolean")


@dataclass(frozen=True, slots=True)
class PosterDescriptor:
    """Poster metadata accompanying a delivery representation."""

    url: EphemeralMediaUrl
    width: int
    height: int
    mime_type: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "url", _coerce_url(self.url, field="poster.url"))
        object.__setattr__(self, "width", _positive_int(self.width, field="poster.width"))
        object.__setattr__(self, "height", _positive_int(self.height, field="poster.height"))
        object.__setattr__(self, "mime_type", _mime_type(self.mime_type, field="poster.mime_type"))


@dataclass(frozen=True, slots=True)
class CaptionTrackDescriptor:
    """One timed caption track available to the player."""

    language: str
    label: str
    url: EphemeralMediaUrl
    is_default: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "url", _coerce_url(self.url, field="caption.url"))
        object.__setattr__(self, "language", _language(self.language))
        object.__setattr__(self, "label", _label(self.label, field="caption.label"))
        if not isinstance(self.is_default, bool):
            raise TypeError("caption.is_default must be a boolean")


@dataclass(frozen=True, slots=True)
class TranscriptDescriptor:
    """A transcript reference with no provider-specific identity."""

    language: str
    format: TranscriptFormat
    url: EphemeralMediaUrl

    def __post_init__(self) -> None:
        object.__setattr__(self, "url", _coerce_url(self.url, field="transcript.url"))
        object.__setattr__(self, "language", _language(self.language))
        if not isinstance(self.format, TranscriptFormat):
            object.__setattr__(self, "format", TranscriptFormat(self.format))


@dataclass(frozen=True, slots=True)
class RenditionDescriptor:
    """Technical metadata for one approved media rendition."""

    name: str
    width: int
    height: int
    bitrate_kbps: int
    mime_type: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", _label(self.name, field="rendition.name"))
        object.__setattr__(self, "width", _positive_int(self.width, field="rendition.width"))
        object.__setattr__(self, "height", _positive_int(self.height, field="rendition.height"))
        object.__setattr__(
            self,
            "bitrate_kbps",
            _positive_int(self.bitrate_kbps, field="rendition.bitrate_kbps"),
        )
        object.__setattr__(
            self,
            "mime_type",
            _mime_type(self.mime_type, field="rendition.mime_type"),
        )


@dataclass(frozen=True, slots=True)
class PlaybackGrantDescriptor:
    """A scoped, short-lived grant descriptor without a signing secret/token."""

    grant_id: str
    authorization: MediaAuthorizationContext
    activity_id: str
    activity_version: str
    media_version: MediaAssetVersion
    issued_at: datetime
    expires_at: datetime

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "authorization",
            _require_instance(
                self.authorization,
                MediaAuthorizationContext,
                field="authorization",
            ),
        )
        object.__setattr__(self, "grant_id", _opaque_identifier(self.grant_id, field="grant_id"))
        object.__setattr__(
            self,
            "activity_id",
            _opaque_identifier(self.activity_id, field="activity_id"),
        )
        object.__setattr__(
            self,
            "activity_version",
            _opaque_identifier(self.activity_version, field="activity_version"),
        )
        object.__setattr__(
            self,
            "media_version",
            _require_instance(self.media_version, MediaAssetVersion, field="media_version"),
        )
        issued_at = _aware_utc(self.issued_at, field="issued_at")
        expires_at = _aware_utc(self.expires_at, field="expires_at")
        if expires_at <= issued_at:
            raise ValueError("expires_at must be after issued_at")
        object.__setattr__(self, "issued_at", issued_at)
        object.__setattr__(self, "expires_at", expires_at)

    def is_expired(self, *, now: datetime | None = None) -> bool:
        return _now(now) >= self.expires_at

    def validate(
        self,
        *,
        now: datetime | None = None,
        max_lifetime: timedelta | None = None,
    ) -> None:
        current_time = _now(now)
        if max_lifetime is not None and max_lifetime <= timedelta(0):
            raise ValueError("max_lifetime must be positive")
        if max_lifetime is not None and self.expires_at - self.issued_at > max_lifetime:
            raise ValueError("playback grant lifetime exceeds the configured bound")
        if current_time < self.issued_at:
            raise MediaNotYetValidError("the playback grant is not valid yet")
        if current_time >= self.expires_at:
            raise MediaExpiredError("the playback grant has expired")


@dataclass(frozen=True, slots=True)
class AuthorizedMediaVersion:
    """Already-authorized input to a media adapter.

    Constructing this value does not perform authorization.  The activity and
    learning boundary must establish authorization before calling the port.
    """

    authorization: MediaAuthorizationContext
    activity_id: str
    activity_version: str
    media_version: MediaAssetVersion

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "authorization",
            _require_instance(
                self.authorization,
                MediaAuthorizationContext,
                field="authorization",
            ),
        )
        object.__setattr__(
            self,
            "activity_id",
            _opaque_identifier(self.activity_id, field="activity_id"),
        )
        object.__setattr__(
            self,
            "activity_version",
            _opaque_identifier(self.activity_version, field="activity_version"),
        )
        object.__setattr__(
            self,
            "media_version",
            _require_instance(self.media_version, MediaAssetVersion, field="media_version"),
        )


@dataclass(frozen=True, slots=True)
class MediaDeliveryMetadata:
    """Ephemeral provider-neutral metadata for an authorized media version."""

    authorization: MediaAuthorizationContext
    activity_id: str
    activity_version: str
    media_version: MediaAssetVersion
    grant: PlaybackGrantDescriptor
    delivery: MediaDeliveryDescriptor
    fallback: MediaDeliveryDescriptor | None = None
    poster: PosterDescriptor | None = None
    captions: tuple[CaptionTrackDescriptor, ...] = ()
    transcript: TranscriptDescriptor | None = None
    duration_seconds: int | None = None
    renditions: tuple[RenditionDescriptor, ...] = ()

    def __post_init__(self) -> None:
        authorization = _require_instance(
            self.authorization,
            MediaAuthorizationContext,
            field="authorization",
        )
        activity_id = _opaque_identifier(self.activity_id, field="activity_id")
        activity_version = _opaque_identifier(self.activity_version, field="activity_version")
        media_version = _require_instance(
            self.media_version,
            MediaAssetVersion,
            field="media_version",
        )
        grant = _require_instance(self.grant, PlaybackGrantDescriptor, field="grant")
        delivery = _require_instance(
            self.delivery,
            MediaDeliveryDescriptor,
            field="delivery",
        )
        fallback = (
            None
            if self.fallback is None
            else _require_instance(self.fallback, MediaDeliveryDescriptor, field="fallback")
        )
        poster = (
            None
            if self.poster is None
            else _require_instance(self.poster, PosterDescriptor, field="poster")
        )
        transcript = (
            None
            if self.transcript is None
            else _require_instance(self.transcript, TranscriptDescriptor, field="transcript")
        )
        captions = _tuple_of(self.captions, CaptionTrackDescriptor, field="captions")
        renditions = _tuple_of(self.renditions, RenditionDescriptor, field="renditions")
        object.__setattr__(self, "authorization", authorization)
        object.__setattr__(self, "activity_id", activity_id)
        object.__setattr__(self, "activity_version", activity_version)
        object.__setattr__(self, "media_version", media_version)
        object.__setattr__(self, "grant", grant)
        object.__setattr__(self, "delivery", delivery)
        object.__setattr__(self, "fallback", fallback)
        object.__setattr__(self, "poster", poster)
        object.__setattr__(self, "transcript", transcript)
        if (
            grant.authorization != authorization
            or grant.activity_id != activity_id
            or grant.activity_version != activity_version
            or grant.media_version != media_version
        ):
            raise ValueError("playback grant scope does not match delivery metadata")
        if fallback is not None and fallback.kind is not MediaDeliveryKind.PROGRESSIVE:
            raise ValueError("delivery fallback must be progressive")
        if fallback is not None and not fallback.supports_range:
            raise ValueError("delivery fallback must support byte ranges")
        if delivery.kind is MediaDeliveryKind.PROGRESSIVE and fallback is not None:
            raise ValueError("progressive delivery cannot have a progressive fallback")
        if self.duration_seconds is not None:
            object.__setattr__(
                self,
                "duration_seconds",
                _nonnegative_int(self.duration_seconds, field="duration_seconds"),
            )
        if sum(caption.is_default for caption in captions) > 1:
            raise ValueError("at most one caption track may be the default")
        if len({caption.language.casefold() for caption in captions}) != len(captions):
            raise ValueError("caption languages must be unique")
        object.__setattr__(self, "captions", captions)
        object.__setattr__(self, "renditions", renditions)

    def matches_request(self, request: AuthorizedMediaVersion) -> bool:
        """Return whether this response is bound to the supplied request scope."""

        request = _require_instance(request, AuthorizedMediaVersion, field="request")
        return (
            self.authorization == request.authorization
            and self.activity_id == request.activity_id
            and self.activity_version == request.activity_version
            and self.media_version == request.media_version
        )

    def validate_for_request(
        self,
        request: AuthorizedMediaVersion,
        *,
        now: datetime | None = None,
        max_lifetime: timedelta | None = None,
    ) -> None:
        """Fail closed unless metadata and its grant match an authorized request."""

        if not self.matches_request(request):
            raise MediaAuthorizationMismatchError(
                "delivery metadata does not match the authorized media request"
            )
        self.validate_grant(now=now, max_lifetime=max_lifetime)

    def validate_grant(
        self,
        *,
        now: datetime | None = None,
        max_lifetime: timedelta | None = None,
    ) -> None:
        """Fail closed when the ephemeral delivery window is no longer valid."""

        self.grant.validate(now=now, max_lifetime=max_lifetime)


@runtime_checkable
class MediaDeliveryPort(Protocol):
    """Resolve ephemeral metadata for an already-authorized media version."""

    async def resolve_delivery(
        self,
        request: AuthorizedMediaVersion,
    ) -> MediaDeliveryMetadata:
        """Return provider-neutral delivery metadata without authorizing access."""


async def resolve_authorized_delivery(
    port: MediaDeliveryPort,
    request: AuthorizedMediaVersion,
    *,
    now: datetime | None = None,
    max_lifetime: timedelta | None = None,
) -> MediaDeliveryMetadata:
    """Resolve through a port and enforce response/request/grant binding."""

    metadata = await port.resolve_delivery(request)
    if not isinstance(metadata, MediaDeliveryMetadata):
        raise TypeError("media delivery port must return MediaDeliveryMetadata")
    metadata.validate_for_request(
        request,
        now=now,
        max_lifetime=max_lifetime,
    )
    return metadata


__all__ = [
    "AuthorizedMediaVersion",
    "CaptionTrackDescriptor",
    "MediaAuthorizationContext",
    "create_media_authorization_context",
    "EphemeralMediaUrl",
    "MediaAssetId",
    "MediaAssetVersion",
    "MediaDeliveryDescriptor",
    "MediaDeliveryKind",
    "MediaDeliveryMetadata",
    "MediaDeliveryPort",
    "MediaVersionId",
    "PlaybackGrantDescriptor",
    "PosterDescriptor",
    "RenditionDescriptor",
    "TranscriptDescriptor",
    "TranscriptFormat",
    "resolve_authorized_delivery",
]
