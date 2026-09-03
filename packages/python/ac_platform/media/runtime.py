"""Composition seams for media storage, inspection, processing, and telemetry."""

from __future__ import annotations

import hashlib
import hmac
from collections.abc import Callable
from dataclasses import dataclass

from ac_platform.application.settings import Settings
from ac_platform.media.processing import FailClosedProcessor, MediaProcessor
from ac_platform.media.scanner import ContentScanner, FailClosedScanner
from ac_platform.media.service import MediaService
from ac_platform.media.signing import MediaSigner
from ac_platform.media.storage import PrivateObjectStorage, UnconfiguredPrivateObjectStorage
from ac_platform.telemetry import TelemetryEvent, TelemetryRecorder


class NullTelemetrySink:
    """Explicit no-export sink used until an approved telemetry exporter is configured."""

    def record(self, event: TelemetryEvent) -> None:
        del event


@dataclass(frozen=True, slots=True)
class MediaRuntime:
    service: MediaService
    telemetry: TelemetryRecorder
    activity_media_resolver: Callable[..., object] | None = None
    media_descriptor_resolver: Callable[..., object] | None = None
    playback_policy_resolver: Callable[..., object] | None = None

    @property
    def learning_playback_composed(self) -> bool:
        """Whether all server-owned seams needed by learning are present."""

        return (
            self.activity_media_resolver is not None
            and self.media_descriptor_resolver is not None
            and self.playback_policy_resolver is not None
        )


def _derive(secret: str, label: bytes) -> bytes:
    return hmac.new(secret.encode("utf-8"), label, hashlib.sha256).digest()


def create_default_media_runtime(settings: Settings) -> MediaRuntime:
    """Build fail-closed defaults; production credentials are injected by deployment composition."""

    signer_secret = _derive(settings.session_token_pepper.get_secret_value(), b"media-signing-v1")
    webhook_secret = _derive(
        settings.email_challenge_secret.get_secret_value(), b"media-webhook-v1"
    )
    storage: PrivateObjectStorage = UnconfiguredPrivateObjectStorage()
    scanner: ContentScanner = FailClosedScanner()
    processor: MediaProcessor = FailClosedProcessor()
    service = MediaService(
        storage=storage,
        signer=MediaSigner(signer_secret),
        webhook_secret=webhook_secret,
        scanner=scanner,
        processor=processor,
    )
    return MediaRuntime(
        service=service,
        telemetry=TelemetryRecorder(NullTelemetrySink()),
        activity_media_resolver=service.resolve_activity_media_binding_for_learning,
        media_descriptor_resolver=service.resolve_activity_media_descriptor_for_learner,
    )


def compose_learning_playback_policy_resolver(
    policy: object,
) -> Callable[[object], object]:
    """Compose an explicit learning policy without inferring media semantics.

    The caller must supply a reviewed ``VideoEvidencePolicy``.  At request
    time the resolver additionally requires a server-resolved activity/media
    binding and a ready media duration; no catalog default can enable it.
    """

    from ac_platform.learning.services import VideoEvidencePolicy

    if not isinstance(policy, VideoEvidencePolicy):
        raise TypeError("a reviewed VideoEvidencePolicy is required")

    def resolve(access: object) -> object:
        activity = getattr(access, "activity", None)
        if activity is None or str(getattr(activity, "kind", "")).upper() != "VIDEO":
            raise ValueError("learning playback requires a video activity")
        if (
            getattr(activity, "media_binding_id", None) is None
            or getattr(activity, "media_asset_id", None) is None
            or getattr(activity, "media_version_id", None) is None
            or getattr(activity, "video_duration_seconds", None) is None
        ):
            raise ValueError("learning playback requires an approved ready media binding")
        if policy.version != activity.policy_version:
            raise ValueError("learning playback policy is not pinned to the activity")
        if abs(policy.coverage_threshold - activity.coverage_threshold) > 1e-12:
            raise ValueError("learning playback threshold is not pinned to the activity")
        return policy

    return resolve


__all__ = [
    "MediaRuntime",
    "NullTelemetrySink",
    "compose_learning_playback_policy_resolver",
    "create_default_media_runtime",
]
