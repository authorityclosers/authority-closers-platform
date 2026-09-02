"""Typed failures for the provider-neutral media delivery boundary."""

from __future__ import annotations


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
]
