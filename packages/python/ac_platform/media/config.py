"""Validated, fail-closed configuration for private media providers.

The application intentionally does not read provider credentials from this
module's repr, error messages, or telemetry.  A :class:`MediaProviderConfig`
is validation data only in this slice: governance references are evidence
labels, never authorization, and the shipped application cannot activate a
provider or mount its callback path.  A future gated slice must supply an
immutable externally attested activation boundary.

This module describes a provider contract; it does not contact a bucket,
create a bucket, or validate credentials against a remote service.
"""

from __future__ import annotations

import hashlib
import ipaddress
import json
import os
import re
import socket
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Protocol, runtime_checkable
from urllib.parse import urlsplit

from pydantic import SecretStr

from ac_platform.media.errors import MediaConfigurationError

_BUCKET_PATTERN = re.compile(r"^[a-z0-9][a-z0-9.-]{2,62}$")
_ACCESS_KEY_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{5,127}$")
_REGION_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,62}$")
_ORIGIN_HOST_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.-]*$|^\[[0-9A-Fa-f:]+\]$")
_ENDPOINT_HOST_PATTERN = re.compile(r"^[a-z0-9](?:[a-z0-9.-]{0,251}[a-z0-9])?$")
_GOVERNANCE_REFERENCE = "AC-GOV-AUD-001"
_MEDIA_GAP_REFERENCE = "GAP-MEDIA-001"
_MAX_RESOLVED_ENDPOINT_ADDRESSES = 32


class MediaStorageProvider(StrEnum):
    """Supported S3 API compatible provider shapes.

    ``S3`` and ``MINIO`` intentionally share one adapter.  Provider-specific
    behavior belongs in deployment composition, not in media domain models.
    """

    UNCONFIGURED = "unconfigured"
    S3 = "s3"
    MINIO = "minio"


@runtime_checkable
class MediaProviderActivationVerifier(Protocol):
    """External verifier for an immutable audited activation record.

    The application owns no issuer or signing key for this record.  A
    deployment control plane may inject an implementation that verifies the
    exact non-secret configuration fingerprint and the two controlled-document
    references.  In the absence of that implementation activation is denied.
    """

    def verify(
        self,
        *,
        config_fingerprint: str,
        governance_reference: str,
        media_gap_reference: str,
    ) -> bool: ...


def _text(value: object | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, SecretStr):
        value = value.get_secret_value()
    if not isinstance(value, str):
        value = str(value)
    normalized = value.strip()
    return normalized or None


def _secret(value: object | None) -> SecretStr | None:
    normalized = _text(value)
    return SecretStr(normalized) if normalized is not None else None


def _bool(value: object | None, *, field_name: str, default: bool = False) -> bool:
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
    raise ValueError(f"{field_name} must be a boolean")


def _bounded_int(value: object | None, *, field_name: str, default: int, maximum: int) -> int:
    if value is None or value == "":
        result = default
    else:
        if isinstance(value, bool):
            raise ValueError(f"{field_name} must be an integer")
        try:
            result = value if isinstance(value, int) else int(str(value))
        except (TypeError, ValueError) as error:
            raise ValueError(f"{field_name} must be an integer") from error
    if result <= 0 or result > maximum:
        raise ValueError(f"{field_name} must be between 1 and {maximum}")
    return result


def _split_origins(value: object | None) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        values = value.split(",")
    else:
        if not isinstance(value, Iterable):
            raise ValueError("media allowed origins must be a comma-separated list")
        values = list(value)
    return tuple(str(item).strip() for item in values if str(item).strip())


def _split_hosts(value: object | None) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        values = value.split(",")
    else:
        if not isinstance(value, Iterable):
            raise ValueError("media approved endpoint hosts must be a comma-separated list")
        values = list(value)
    hosts = tuple(str(item).strip().lower().rstrip(".") for item in values if str(item).strip())
    if len(hosts) > 16 or len(set(hosts)) != len(hosts):
        raise ValueError("media approved endpoint hosts must be unique and bounded")
    for host in hosts:
        if not _ENDPOINT_HOST_PATTERN.fullmatch(host):
            raise ValueError("media approved endpoint host is invalid")
    return hosts


def _reject_private_endpoint_host(host: str, *, field_name: str) -> None:
    normalized = host.rstrip(".").lower()
    if normalized == "localhost" or normalized.endswith(".localhost"):
        raise ValueError(f"{field_name} must not target loopback or localhost")
    # A hostname is not resolved here.  Provider composition is fail-closed
    # without an immutable approval record, so credentials cannot be sent to a
    # rebinding hostname.  Obvious local-only suffixes are rejected up front.
    if normalized.endswith((".local", ".internal", ".lan")):
        raise ValueError(f"{field_name} must not target a private hostname")
    try:
        address = ipaddress.ip_address(normalized)
    except ValueError:
        return
    if (
        address.is_loopback
        or address.is_private
        or address.is_link_local
        or address.is_reserved
        or address.is_multicast
        or address.is_unspecified
    ):
        raise ValueError(f"{field_name} must not target a private or non-routable address")


def _resolve_public_endpoint_addresses(host: str, port: int) -> frozenset[str]:
    """Resolve an approved provider host and reject every unsafe answer.

    Host allowlists alone do not protect a credential-bearing client from DNS
    rebinding.  We resolve all answers, reject any non-global address, and
    require at least one routable answer.  The caller performs two resolutions
    at the composition boundary so an answer changing during validation fails
    closed instead of being treated as an approved endpoint.
    """

    try:
        answers = socket.getaddrinfo(host, port, 0, socket.SOCK_STREAM)
    except (OSError, ValueError) as error:
        raise ValueError("media storage endpoint could not be resolved safely") from error
    addresses: set[str] = set()
    for answer in answers:
        sockaddr = answer[4] if len(answer) > 4 else ()
        raw_address = sockaddr[0] if isinstance(sockaddr, tuple) and sockaddr else None
        if not isinstance(raw_address, str):
            raise ValueError("media storage endpoint returned an invalid address")
        try:
            address = ipaddress.ip_address(raw_address)
        except ValueError as error:
            raise ValueError("media storage endpoint returned an invalid address") from error
        # ``is_global`` is deliberately stricter than only checking RFC1918:
        # loopback, link-local, documentation, shared, reserved, multicast,
        # and unspecified ranges must never receive provider credentials.
        if not address.is_global:
            raise ValueError("media storage endpoint resolved to a private or non-routable address")
        addresses.add(address.compressed)
        if len(addresses) > _MAX_RESOLVED_ENDPOINT_ADDRESSES:
            raise ValueError("media storage endpoint returned too many addresses")
    if not addresses:
        raise ValueError("media storage endpoint returned no addresses")
    return frozenset(addresses)


def resolve_media_endpoint_addresses(endpoint_url: str) -> tuple[str, ...]:
    """Return a stable public DNS answer set for an approved HTTPS endpoint.

    This is intentionally a composition-time safety check, not a provider
    health probe.  It performs no credentialed request and never returns
    secret material.  Re-resolving on each active adapter operation lets the
    adapter detect a later DNS answer change and remain unavailable.
    """

    try:
        parsed = urlsplit(endpoint_url)
        host = parsed.hostname
        port = parsed.port or 443
    except (TypeError, ValueError) as error:
        raise ValueError("media storage endpoint could not be parsed safely") from error
    if (
        parsed.scheme != "https"
        or not parsed.netloc
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or host is None
    ):
        raise ValueError("media storage endpoint must be a credential-free HTTPS URL")
    if port < 1 or port > 65535:
        raise ValueError("media storage endpoint port is invalid")
    try:
        _reject_private_endpoint_host(host, field_name="media storage endpoint")
    except ValueError:
        raise
    if host is None:
        raise ValueError("media storage endpoint has no host")
    normalized_host = host.rstrip(".").lower()
    first = _resolve_public_endpoint_addresses(normalized_host, port)
    second = _resolve_public_endpoint_addresses(normalized_host, port)
    if first != second:
        raise ValueError("media storage endpoint DNS resolution changed during validation")
    return tuple(sorted(first))


def _provider_endpoint_host_allowed(
    host: str,
    *,
    provider: MediaStorageProvider,
    approved_endpoint_hosts: tuple[str, ...],
) -> bool:
    normalized = host.rstrip(".").lower()
    # Every credential-bearing endpoint is deployment-approved explicitly.
    # Even a public AWS S3 hostname is unapproved until the immutable
    # composition record binds that exact host.
    del provider
    return normalized in approved_endpoint_hosts


def _validate_url(
    value: str,
    *,
    field_name: str,
    environment: str,
    allow_http_loopback: bool,
    allow_http_private: bool = False,
    require_origin: bool = False,
    reject_private_host: bool = False,
) -> str:
    if any(ord(character) < 0x20 or ord(character) == 0x7F for character in value):
        raise ValueError(f"{field_name} must not contain control characters")
    if value != value.strip() or any(character.isspace() for character in value):
        raise ValueError(f"{field_name} must not contain whitespace")
    try:
        parsed = urlsplit(value)
    except ValueError as error:
        raise ValueError(f"{field_name} must be a valid URL") from error
    if parsed.scheme not in {"https", "http"} or not parsed.netloc or parsed.hostname is None:
        raise ValueError(f"{field_name} must be an absolute HTTP(S) URL")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError(f"{field_name} must not contain credentials")
    if parsed.query or parsed.fragment:
        raise ValueError(f"{field_name} must not contain a query or fragment")
    try:
        port = parsed.port
    except ValueError as error:
        raise ValueError(f"{field_name} must contain a valid port") from error
    if port is not None and not 1 <= port <= 65535:
        raise ValueError(f"{field_name} must contain a valid port")
    host = parsed.hostname
    host_for_validation = f"[{host}]" if host is not None and ":" in host else host
    if host_for_validation is None or not _ORIGIN_HOST_PATTERN.fullmatch(host_for_validation):
        raise ValueError(f"{field_name} must contain a valid host")
    if reject_private_host:
        _reject_private_endpoint_host(host, field_name=field_name)
    if require_origin and parsed.path not in {"", "/"}:
        raise ValueError(f"{field_name} must be an origin without a path")
    if parsed.scheme == "http":
        loopback = host in {"localhost", "127.0.0.1", "::1"}
        if not allow_http_private and (not allow_http_loopback or not loopback):
            raise ValueError(f"{field_name} must use HTTPS outside local loopback")
        if environment in {"staging", "production"}:
            raise ValueError(f"{field_name} must use HTTPS in deployment environments")
    return value.rstrip("/") if require_origin else value


@dataclass(frozen=True, slots=True)
class MediaProviderConfig:
    """Complete media provider configuration, inert by default.

    ``enabled=False`` is a safe and useful configuration: composition returns
    :class:`~ac_platform.media.storage.UnconfiguredPrivateObjectStorage` and
    never imports or instantiates a provider SDK.  Enabled configuration is
    still only validated data; this class performs no network operation and
    cannot produce an activation record or verifier.
    """

    environment: str = "local"
    enabled: bool = False
    provider: MediaStorageProvider | str = MediaStorageProvider.UNCONFIGURED
    endpoint_url: str | None = None
    bucket: str | None = None
    region: str | None = None
    access_key_id: str | None = None
    secret_access_key: SecretStr | None = field(default=None, repr=False, compare=False)
    delivery_origin: str | None = None
    allowed_origins: tuple[str, ...] = ()
    governance_reference: str | None = None
    media_gap_reference: str | None = None
    approved_endpoint_hosts: tuple[str, ...] = ()
    upload_ttl_seconds: int = 900
    playback_ttl_seconds: int = 900
    max_upload_bytes: int = 512 * 1024 * 1024
    quota_window_seconds: int = 3600
    quota_bytes_per_actor: int = 2 * 1024 * 1024 * 1024
    quota_uploads_per_actor: int = 100
    max_renditions: int = 6
    max_processing_output_bytes: int = 4 * 1024 * 1024 * 1024
    max_processing_caption_bytes: int = 25 * 1024 * 1024
    allow_range_requests: bool = True

    def __post_init__(self) -> None:
        environment = _text(self.environment) or "local"
        if environment not in {"local", "test", "development", "staging", "production"}:
            raise ValueError("media environment is unsupported")
        object.__setattr__(self, "environment", environment)
        try:
            provider = MediaStorageProvider(self.provider)
        except ValueError as error:
            raise ValueError("media provider must be s3, minio, or unconfigured") from error
        object.__setattr__(self, "provider", provider)
        object.__setattr__(self, "allowed_origins", _split_origins(self.allowed_origins))
        object.__setattr__(self, "access_key_id", _text(self.access_key_id))
        object.__setattr__(self, "secret_access_key", _secret(self.secret_access_key))
        object.__setattr__(self, "endpoint_url", _text(self.endpoint_url))
        object.__setattr__(self, "delivery_origin", _text(self.delivery_origin))
        object.__setattr__(self, "bucket", _text(self.bucket))
        object.__setattr__(self, "region", _text(self.region))
        object.__setattr__(self, "governance_reference", _text(self.governance_reference))
        object.__setattr__(self, "media_gap_reference", _text(self.media_gap_reference))
        object.__setattr__(
            self,
            "approved_endpoint_hosts",
            _split_hosts(self.approved_endpoint_hosts),
        )
        if not isinstance(self.enabled, bool):
            raise ValueError("media provider enabled must be a boolean")
        object.__setattr__(
            self,
            "upload_ttl_seconds",
            _bounded_int(
                self.upload_ttl_seconds,
                field_name="media upload TTL",
                default=900,
                maximum=3600,
            ),
        )
        object.__setattr__(
            self,
            "playback_ttl_seconds",
            _bounded_int(
                self.playback_ttl_seconds,
                field_name="media playback TTL",
                default=900,
                maximum=3600,
            ),
        )
        object.__setattr__(
            self,
            "max_upload_bytes",
            _bounded_int(
                self.max_upload_bytes,
                field_name="media max upload bytes",
                default=512 * 1024 * 1024,
                maximum=8 * 1024 * 1024 * 1024,
            ),
        )
        object.__setattr__(
            self,
            "quota_window_seconds",
            _bounded_int(
                self.quota_window_seconds,
                field_name="media quota window",
                default=3600,
                maximum=7 * 24 * 3600,
            ),
        )
        object.__setattr__(
            self,
            "quota_bytes_per_actor",
            _bounded_int(
                self.quota_bytes_per_actor,
                field_name="media quota bytes",
                default=2 * 1024 * 1024 * 1024,
                maximum=32 * 1024 * 1024 * 1024,
            ),
        )
        object.__setattr__(
            self,
            "quota_uploads_per_actor",
            _bounded_int(
                self.quota_uploads_per_actor,
                field_name="media quota uploads",
                default=100,
                maximum=10_000,
            ),
        )
        object.__setattr__(
            self,
            "max_renditions",
            _bounded_int(
                self.max_renditions,
                field_name="media max renditions",
                default=6,
                maximum=16,
            ),
        )
        object.__setattr__(
            self,
            "max_processing_output_bytes",
            _bounded_int(
                self.max_processing_output_bytes,
                field_name="media max processing output bytes",
                default=4 * 1024 * 1024 * 1024,
                maximum=64 * 1024 * 1024 * 1024,
            ),
        )
        object.__setattr__(
            self,
            "max_processing_caption_bytes",
            _bounded_int(
                self.max_processing_caption_bytes,
                field_name="media max processing caption bytes",
                default=25 * 1024 * 1024,
                maximum=25 * 1024 * 1024,
            ),
        )
        if not isinstance(self.allow_range_requests, bool):
            raise ValueError("media range policy must be a boolean")

        if not self.enabled:
            # An explicitly disabled provider never acquires meaning from
            # partially supplied values.  Keep those values out of runtime
            # composition and do not reject local config typos as activation.
            return
        if provider is MediaStorageProvider.UNCONFIGURED:
            raise ValueError("enabled media provider must select s3 or minio")
        if self.endpoint_url is None:
            raise ValueError("media storage endpoint is required when enabled")
        if self.bucket is None or not _BUCKET_PATTERN.fullmatch(self.bucket):
            raise ValueError("media storage bucket is invalid or missing")
        if self.region is None or not _REGION_PATTERN.fullmatch(self.region):
            raise ValueError("media storage region is invalid or missing")
        if self.access_key_id is None or not _ACCESS_KEY_PATTERN.fullmatch(self.access_key_id):
            raise ValueError("media storage access key is invalid or missing")
        secret = self.secret_access_key.get_secret_value() if self.secret_access_key else ""
        if len(secret.encode("utf-8")) < 16 or any(character.isspace() for character in secret):
            raise ValueError("media storage secret access key is invalid or missing")
        _validate_url(
            self.endpoint_url,
            field_name="media storage endpoint",
            environment=environment,
            allow_http_loopback=False,
            allow_http_private=False,
            reject_private_host=True,
        )
        endpoint_host = urlsplit(self.endpoint_url).hostname
        if endpoint_host is None or not _provider_endpoint_host_allowed(
            endpoint_host,
            provider=provider,
            approved_endpoint_hosts=self.approved_endpoint_hosts,
        ):
            raise ValueError("media storage endpoint host is not approved")
        if self.delivery_origin is None:
            raise ValueError("media delivery origin is required when enabled")
        _validate_url(
            self.delivery_origin,
            field_name="media delivery origin",
            environment=environment,
            allow_http_loopback=False,
            require_origin=True,
        )
        if not self.allowed_origins:
            raise ValueError("at least one media CORS origin is required when enabled")
        if len(self.allowed_origins) > 16 or len(set(self.allowed_origins)) != len(
            self.allowed_origins
        ):
            raise ValueError("media CORS origins must be unique and bounded")
        for origin in self.allowed_origins:
            if origin == "*":
                raise ValueError("media CORS origins must not contain a wildcard")
            _validate_url(
                origin,
                field_name="media CORS origin",
                environment=environment,
                allow_http_loopback=environment in {"local", "test", "development"},
                require_origin=True,
            )
        if self.governance_reference != _GOVERNANCE_REFERENCE:
            raise ValueError("media provider requires AC-GOV-AUD-001 approval reference")
        if self.media_gap_reference != _MEDIA_GAP_REFERENCE:
            raise ValueError("media provider requires GAP-MEDIA-001 approval reference")

    def activation_verified(
        self,
        verifier: MediaProviderActivationVerifier | None,
    ) -> bool:
        """Return true only when an external verifier approves this config.

        The verifier is deliberately a dependency-injection port rather than
        an object issued by this package.  A missing, malformed, or failing
        verifier always yields denial and never changes configuration state.
        """

        if (
            not self.enabled
            or self.provider is MediaStorageProvider.UNCONFIGURED
            or verifier is None
        ):
            return False
        if not isinstance(verifier, MediaProviderActivationVerifier):
            return False
        try:
            return (
                verifier.verify(
                    config_fingerprint=self.activation_fingerprint,
                    governance_reference=self.governance_reference or "",
                    media_gap_reference=self.media_gap_reference or "",
                )
                is True
            )
        except Exception:
            return False

    @property
    def activation_fingerprint(self) -> str:
        """Stable non-secret binding used by an audited activation record."""

        payload = {
            "environment": self.environment,
            "enabled": self.enabled,
            "provider": MediaStorageProvider(self.provider).value,
            "endpoint_url": self.endpoint_url,
            "bucket": self.bucket,
            "region": self.region,
            "access_key_id": self.access_key_id,
            "delivery_origin": self.delivery_origin,
            "allowed_origins": self.allowed_origins,
            "approved_endpoint_hosts": self.approved_endpoint_hosts,
            "governance_reference": self.governance_reference,
            "media_gap_reference": self.media_gap_reference,
            "upload_ttl_seconds": self.upload_ttl_seconds,
            "playback_ttl_seconds": self.playback_ttl_seconds,
            "max_upload_bytes": self.max_upload_bytes,
            "quota_window_seconds": self.quota_window_seconds,
            "quota_bytes_per_actor": self.quota_bytes_per_actor,
            "quota_uploads_per_actor": self.quota_uploads_per_actor,
            "max_renditions": self.max_renditions,
            "max_processing_output_bytes": self.max_processing_output_bytes,
            "max_processing_caption_bytes": self.max_processing_caption_bytes,
            "allow_range_requests": self.allow_range_requests,
        }
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()

    def validate(self) -> MediaProviderConfig:
        """Return this already-validated immutable configuration object."""

        return self

    @property
    def secret_access_key_value(self) -> str | None:
        """Return secret material only for an adapter factory call.

        Callers should not log or persist this value.  The property exists to
        keep ``SecretStr`` handling at the composition boundary.
        """

        return self.secret_access_key.get_secret_value() if self.secret_access_key else None

    @classmethod
    def from_environment(
        cls,
        environ: Mapping[str, object] | None = None,
    ) -> MediaProviderConfig:
        """Build configuration from a supplied environment mapping.

        A mapping is accepted for deterministic tests.  Production callers
        may omit it to read ``os.environ``; values are never printed.
        """

        values: Mapping[str, object] = os.environ if environ is None else environ

        def first(*names: str) -> object | None:
            for name in names:
                value = values.get(name)
                if value is not None and value != "":
                    return value
            return None

        enabled = _bool(
            first("AC_MEDIA_PROVIDER_ENABLED", "AC_MEDIA_STORAGE_ENABLED"),
            field_name="AC_MEDIA_PROVIDER_ENABLED",
            default=False,
        )
        provider = first("AC_MEDIA_PROVIDER", "AC_MEDIA_STORAGE_PROVIDER")
        return cls(
            environment=_text(first("AC_ENVIRONMENT")) or "local",
            enabled=enabled,
            provider=_text(provider) or MediaStorageProvider.UNCONFIGURED,
            endpoint_url=_text(first("AC_MEDIA_STORAGE_ENDPOINT", "AC_MEDIA_S3_ENDPOINT")),
            bucket=_text(first("AC_MEDIA_STORAGE_BUCKET", "AC_MEDIA_S3_BUCKET")),
            region=_text(first("AC_MEDIA_STORAGE_REGION", "AC_MEDIA_S3_REGION")),
            access_key_id=_text(
                first("AC_MEDIA_STORAGE_ACCESS_KEY_ID", "AC_MEDIA_S3_ACCESS_KEY_ID")
            ),
            secret_access_key=_secret(
                first("AC_MEDIA_STORAGE_SECRET_ACCESS_KEY", "AC_MEDIA_S3_SECRET_ACCESS_KEY")
            ),
            delivery_origin=_text(first("AC_MEDIA_DELIVERY_ORIGIN", "AC_MEDIA_PUBLIC_ORIGIN")),
            allowed_origins=_split_origins(
                first("AC_MEDIA_CORS_ORIGINS", "AC_MEDIA_ALLOWED_ORIGINS")
            ),
            governance_reference=_text(first("AC_MEDIA_GOVERNANCE_REFERENCE")),
            media_gap_reference=_text(first("AC_MEDIA_GAP_REFERENCE")),
            approved_endpoint_hosts=_split_hosts(first("AC_MEDIA_STORAGE_APPROVED_ENDPOINT_HOSTS")),
            upload_ttl_seconds=_bounded_int(
                first("AC_MEDIA_UPLOAD_TTL_SECONDS"),
                field_name="AC_MEDIA_UPLOAD_TTL_SECONDS",
                default=900,
                maximum=3600,
            ),
            playback_ttl_seconds=_bounded_int(
                first("AC_MEDIA_PLAYBACK_TTL_SECONDS"),
                field_name="AC_MEDIA_PLAYBACK_TTL_SECONDS",
                default=900,
                maximum=3600,
            ),
            max_upload_bytes=_bounded_int(
                first("AC_MEDIA_MAX_UPLOAD_BYTES"),
                field_name="AC_MEDIA_MAX_UPLOAD_BYTES",
                default=512 * 1024 * 1024,
                maximum=8 * 1024 * 1024 * 1024,
            ),
            quota_window_seconds=_bounded_int(
                first("AC_MEDIA_QUOTA_WINDOW_SECONDS"),
                field_name="AC_MEDIA_QUOTA_WINDOW_SECONDS",
                default=3600,
                maximum=7 * 24 * 3600,
            ),
            quota_bytes_per_actor=_bounded_int(
                first("AC_MEDIA_QUOTA_BYTES_PER_ACTOR"),
                field_name="AC_MEDIA_QUOTA_BYTES_PER_ACTOR",
                default=2 * 1024 * 1024 * 1024,
                maximum=32 * 1024 * 1024 * 1024,
            ),
            quota_uploads_per_actor=_bounded_int(
                first("AC_MEDIA_QUOTA_UPLOADS_PER_ACTOR"),
                field_name="AC_MEDIA_QUOTA_UPLOADS_PER_ACTOR",
                default=100,
                maximum=10_000,
            ),
            max_renditions=_bounded_int(
                first("AC_MEDIA_MAX_RENDITIONS"),
                field_name="AC_MEDIA_MAX_RENDITIONS",
                default=6,
                maximum=16,
            ),
            max_processing_output_bytes=_bounded_int(
                first("AC_MEDIA_MAX_PROCESSING_OUTPUT_BYTES"),
                field_name="AC_MEDIA_MAX_PROCESSING_OUTPUT_BYTES",
                default=4 * 1024 * 1024 * 1024,
                maximum=64 * 1024 * 1024 * 1024,
            ),
            max_processing_caption_bytes=_bounded_int(
                first("AC_MEDIA_MAX_PROCESSING_CAPTION_BYTES"),
                field_name="AC_MEDIA_MAX_PROCESSING_CAPTION_BYTES",
                default=25 * 1024 * 1024,
                maximum=25 * 1024 * 1024,
            ),
            allow_range_requests=_bool(
                first("AC_MEDIA_ALLOW_RANGE_REQUESTS"),
                field_name="AC_MEDIA_ALLOW_RANGE_REQUESTS",
                default=True,
            ),
        )

    @classmethod
    def from_settings(cls, settings: Any) -> MediaProviderConfig:
        """Build media config from validated application settings.

        ``Any`` keeps this package decoupled from the application settings
        module and makes the media package straightforward to test in
        isolation.  Secret values are unwrapped only inside this call.
        """

        return cls(
            environment=getattr(settings, "environment", "local"),
            enabled=getattr(settings, "media_provider_enabled", False),
            provider=getattr(settings, "media_provider", MediaStorageProvider.UNCONFIGURED),
            endpoint_url=getattr(settings, "media_storage_endpoint", None),
            bucket=getattr(settings, "media_storage_bucket", None),
            region=getattr(settings, "media_storage_region", None),
            access_key_id=getattr(settings, "media_storage_access_key_id", None),
            secret_access_key=getattr(settings, "media_storage_secret_access_key", None),
            delivery_origin=getattr(settings, "media_delivery_origin", None),
            allowed_origins=getattr(settings, "media_cors_origins", ()),
            governance_reference=getattr(settings, "media_governance_reference", None),
            media_gap_reference=getattr(settings, "media_gap_reference", None),
            approved_endpoint_hosts=getattr(settings, "media_storage_approved_endpoint_hosts", ()),
            upload_ttl_seconds=getattr(settings, "media_upload_ttl_seconds", 900),
            playback_ttl_seconds=getattr(settings, "media_playback_ttl_seconds", 900),
            max_upload_bytes=getattr(settings, "media_max_upload_bytes", 512 * 1024 * 1024),
            quota_window_seconds=getattr(settings, "media_quota_window_seconds", 3600),
            quota_bytes_per_actor=getattr(
                settings, "media_quota_bytes_per_actor", 2 * 1024 * 1024 * 1024
            ),
            quota_uploads_per_actor=getattr(settings, "media_quota_uploads_per_actor", 100),
            max_renditions=getattr(settings, "media_max_renditions", 6),
            max_processing_output_bytes=getattr(
                settings, "media_max_processing_output_bytes", 4 * 1024 * 1024 * 1024
            ),
            max_processing_caption_bytes=getattr(
                settings, "media_max_processing_caption_bytes", 25 * 1024 * 1024
            ),
            allow_range_requests=getattr(settings, "media_allow_range_requests", True),
        )


def validate_media_environment(environ: Mapping[str, object] | None = None) -> MediaProviderConfig:
    """Convenience validator used by startup checks and focused tests."""

    try:
        return MediaProviderConfig.from_environment(environ)
    except (TypeError, ValueError) as error:
        raise MediaConfigurationError("media provider configuration is invalid") from error


# Composition aliases keep the public contract readable at call sites that
# refer to storage rather than the broader provider boundary.
MediaStorageConfig = MediaProviderConfig
MediaProvider = MediaStorageProvider


__all__ = [
    "MediaProvider",
    "MediaProviderActivationVerifier",
    "MediaProviderConfig",
    "MediaStorageConfig",
    "MediaStorageProvider",
    "resolve_media_endpoint_addresses",
    "validate_media_environment",
]
