"""Typed failures for the provider-neutral media delivery boundary."""

from __future__ import annotations

from ac_platform.kernel.errors import (
    AuthorizationDenied,
    DomainError,
    ResourceConflict,
    ResourceNotFound,
)


class MediaDeliveryError(RuntimeError):
    """Base class for expected media delivery failures."""

    code = "media_delivery_error"


class MediaUnavailableError(MediaDeliveryError):
    """The requested media version is not available for delivery."""

    code = "media_unavailable"


class MediaProcessingError(MediaDeliveryError):
    """The requested media version is still being processed."""

    code = "media_processing"


class MediaUnsupportedError(MediaDeliveryError):
    """The requested media representation is not supported by the player."""

    code = "media_unsupported"


class MediaRangeError(MediaDeliveryError):
    """A progressive delivery could not satisfy a byte-range request."""

    code = "media_range_error"


class MediaExpiredError(MediaDeliveryError):
    """A short-lived playback grant or delivery window has expired."""

    code = "media_expired"


class MediaNotYetValidError(MediaDeliveryError):
    """A playback grant is not valid until its server-issued start time."""

    code = "media_not_yet_valid"


class MediaAuthorizationMismatchError(MediaDeliveryError):
    """Delivery metadata is not bound to the authorized playback request."""

    code = "media_authorization_mismatch"


class MediaPolicyDeniedError(MediaDeliveryError):
    """An already-authorized caller cannot receive this media under policy."""

    code = "media_policy_denied"


class MediaOriginError(MediaDeliveryError):
    """The configured media origin could not serve the ephemeral delivery."""

    code = "media_origin_error"


class MediaCommandError(DomainError):
    """Base for expected media command/query failures at the HTTP boundary."""

    code = "media_command_rejected"
    title = "The media operation was rejected"
    status = 422


class MediaBadRequest(MediaCommandError):
    code = "media_request_invalid"
    title = "The media request is invalid"
    status = 400


class MediaNotFound(ResourceNotFound):
    code = "media_not_found"
    title = "Media not found"


class MediaForbidden(AuthorizationDenied):
    code = "media_forbidden"
    title = "Media access is not allowed"


class MediaConflict(ResourceConflict):
    code = "media_conflict"
    title = "The media resource changed"


class MediaQuotaExceeded(MediaCommandError):
    code = "media_quota_exceeded"
    title = "The media quota was exceeded"
    status = 429


class MediaStorageUnavailable(MediaCommandError):
    code = "media_storage_unavailable"
    title = "Media storage is temporarily unavailable"
    status = 503


class MediaScannerUnavailable(MediaCommandError):
    code = "media_scanner_unavailable"
    title = "Media safety scanning is temporarily unavailable"
    status = 503


class MediaScanRejected(MediaCommandError):
    code = "media_scan_rejected"
    title = "The media object was not accepted"
    status = 422


__all__ = [
    "MediaAuthorizationMismatchError",
    "MediaDeliveryError",
    "MediaExpiredError",
    "MediaNotYetValidError",
    "MediaOriginError",
    "MediaPolicyDeniedError",
    "MediaProcessingError",
    "MediaRangeError",
    "MediaUnsupportedError",
    "MediaUnavailableError",
    "MediaBadRequest",
    "MediaCommandError",
    "MediaConflict",
    "MediaForbidden",
    "MediaNotFound",
    "MediaQuotaExceeded",
    "MediaScanRejected",
    "MediaScannerUnavailable",
    "MediaStorageUnavailable",
]
