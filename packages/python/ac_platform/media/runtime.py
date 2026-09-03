"""Composition seams for media storage, inspection, processing, and telemetry."""

from __future__ import annotations

import hashlib
import hmac
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
    return MediaRuntime(
        service=MediaService(
            storage=storage,
            signer=MediaSigner(signer_secret),
            webhook_secret=webhook_secret,
            scanner=scanner,
            processor=processor,
        ),
        telemetry=TelemetryRecorder(NullTelemetrySink()),
    )


__all__ = ["MediaRuntime", "NullTelemetrySink", "create_default_media_runtime"]
