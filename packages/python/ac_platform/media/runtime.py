"""Composition seams for media storage, inspection, processing, and telemetry."""

from __future__ import annotations

import hashlib
import hmac
from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from sqlalchemy.orm import Session

from ac_platform.application.settings import Settings
from ac_platform.kernel.authz import ActorContext
from ac_platform.media.config import (
    MediaProviderActivationVerifier,
    MediaProviderConfig,
)
from ac_platform.media.database_delivery_authorizer import (
    DatabaseMediaDeliveryAuthorizer,
    DeliveryActivityResolver,
)
from ac_platform.media.delivery import PrivateMediaDeliveryHandler
from ac_platform.media.errors import MediaConfigurationError
from ac_platform.media.lifecycle import (
    MediaLifecycleHooks,
    MediaRetentionPolicy,
    NoopMediaLifecycleHooks,
)
from ac_platform.media.policy import (
    MediaCorsPolicy,
    SignedMediaDeliveryPort,
)
from ac_platform.media.processing import FailClosedProcessor, MediaProcessor, ProcessingQuota
from ac_platform.media.scanner import ContentScanner, FailClosedScanner
from ac_platform.media.service import MediaService
from ac_platform.media.signing import MediaSigner
from ac_platform.media.storage import (
    PrivateObjectStorage,
    compose_private_object_storage,
)
from ac_platform.media.telemetry import MediaTelemetryExporter, MediaTelemetryRecorder
from ac_platform.telemetry import TelemetryEvent, TelemetryRecorder


class NullTelemetrySink:
    """Explicit no-export sink used until an approved telemetry exporter is configured."""

    def record(self, event: TelemetryEvent) -> None:
        del event


@dataclass(frozen=True, slots=True)
class MediaRuntime:
    service: MediaService
    telemetry: TelemetryRecorder
    environment: str = "local"
    media_config: MediaProviderConfig | None = None
    activation_verifier: MediaProviderActivationVerifier | None = None
    media_telemetry: MediaTelemetryRecorder | None = None
    media_delivery: SignedMediaDeliveryPort | None = None
    media_cors_policy: MediaCorsPolicy | None = None
    activity_media_resolver: Callable[..., object] | None = None
    media_descriptor_resolver: Callable[..., object] | None = None
    playback_policy_resolver: Callable[..., object] | None = None
    authenticated_delivery_handler_factory: (
        Callable[[Session, ActorContext], PrivateMediaDeliveryHandler] | None
    ) = None

    @property
    def learning_playback_composed(self) -> bool:
        """Whether all server-owned seams needed by learning are present."""

        return (
            self.activity_media_resolver is not None
            and self.media_descriptor_resolver is not None
            and self.playback_policy_resolver is not None
        )

    @property
    def provider_activation_verified(self) -> bool:
        """Whether an external verifier currently approves this runtime."""

        return self.media_config is not None and self.media_config.activation_verified(
            self.activation_verifier
        )


def _derive(secret: str, label: bytes) -> bytes:
    return hmac.new(secret.encode("utf-8"), label, hashlib.sha256).digest()


def create_media_runtime(
    settings: Settings,
    *,
    client_factory: Callable[..., Any] | None = None,
    storage: PrivateObjectStorage | None = None,
    scanner: ContentScanner | None = None,
    processor: MediaProcessor | None = None,
    media_telemetry_exporter: MediaTelemetryExporter | None = None,
    lifecycle_hooks: MediaLifecycleHooks | None = None,
    retention_policy: MediaRetentionPolicy | None = None,
    activation_verifier: MediaProviderActivationVerifier | None = None,
    media_delivery_handler: SignedMediaDeliveryPort | None = None,
    delivery_activity_resolver: DeliveryActivityResolver | None = None,
) -> MediaRuntime:
    """Compose media dependencies without contacting external providers.

    The application/deployment composition is intentionally inert in this
    slice.  Local/test callers may exercise explicit seams, but staging and
    production cannot inject a runtime, enable provider settings, or supply a
    future activation verifier.  A later slice must provide a separately
    reviewed immutable attestation and app delivery/worker composition.
    """

    config = MediaProviderConfig.from_settings(settings)

    activation_verified = config.activation_verified(activation_verifier)
    injected_dependencies = any(
        dependency is not None
        for dependency in (
            client_factory,
            storage,
            scanner,
            processor,
            media_telemetry_exporter,
            lifecycle_hooks,
            retention_policy,
            activation_verifier,
            media_delivery_handler,
            delivery_activity_resolver,
        )
    )
    if settings.environment not in {"local", "test"} and (
        settings.media_provider_enabled or injected_dependencies
    ):
        raise MediaConfigurationError(
            "non-local media composition rejects provider activation and injected dependencies"
        )
    if settings.media_provider_enabled and not activation_verified and storage is not None:
        raise MediaConfigurationError(
            "an enabled media provider requires an externally verified activation"
        )
    # Configuration references are deliberately inert.  Keep composition
    # fail-closed until the controlled audit integration supplies the
    # immutable approval bound to this exact configuration.

    if settings.media_provider_enabled and (
        lifecycle_hooks is None
        or isinstance(lifecycle_hooks, NoopMediaLifecycleHooks)
        or retention_policy is None
    ):
        raise MediaConfigurationError(
            "an enabled media runtime requires explicit non-noop retention hooks and policy"
        )

    signer_secret = _derive(settings.session_token_pepper.get_secret_value(), b"media-signing-v1")
    webhook_secret = _derive(
        settings.email_challenge_secret.get_secret_value(), b"media-webhook-v1"
    )
    media_signer = MediaSigner(signer_secret)
    selected_storage = storage or compose_private_object_storage(
        config,
        activation_verifier=activation_verifier,
        client_factory=client_factory,
    )
    selected_scanner = scanner or FailClosedScanner()
    selected_processor = processor or FailClosedProcessor()

    # A signed URL issuer is not an application delivery handler. Do not
    # expose or attach one until the reviewed app route/session/grant handler
    # is explicitly composed by the caller.
    media_delivery = media_delivery_handler if activation_verified else None
    if media_delivery is not None:
        if not isinstance(media_delivery, SignedMediaDeliveryPort):
            raise MediaConfigurationError(
                "the media delivery dependency must use the reviewed application delivery port"
            )
        if (
            config.delivery_origin is None
            or media_delivery.delivery_origin != config.delivery_origin.rstrip("/")
            or media_delivery.playback_ttl != timedelta(seconds=config.playback_ttl_seconds)
            or media_delivery.range_policy.supports_range != config.allow_range_requests
        ):
            raise MediaConfigurationError(
                "the media delivery dependency does not match the approved configuration"
            )
    media_cors_policy = (
        MediaCorsPolicy(config.allowed_origins) if media_delivery is not None else None
    )
    service = MediaService(
        storage=selected_storage,
        signer=media_signer,
        webhook_secret=webhook_secret,
        scanner=selected_scanner,
        processor=selected_processor,
        upload_ttl=timedelta(seconds=config.upload_ttl_seconds),
        playback_ttl=timedelta(seconds=config.playback_ttl_seconds),
        max_upload_bytes=config.max_upload_bytes,
        quota_window=timedelta(seconds=config.quota_window_seconds),
        quota_bytes_per_actor=config.quota_bytes_per_actor,
        quota_uploads_per_actor=config.quota_uploads_per_actor,
        lifecycle_hooks=lifecycle_hooks,
        retention_policy=retention_policy,
        delivery_port=media_delivery,
        processing_quota=ProcessingQuota(
            max_source_bytes=config.max_upload_bytes,
            max_output_bytes=config.max_processing_output_bytes,
            max_renditions=config.max_renditions,
            max_caption_bytes=config.max_processing_caption_bytes,
        ),
        media_config=config,
        activation_verifier=activation_verifier,
        delivery_activity_resolver=delivery_activity_resolver,
    )
    handler_factory: Callable[[Session, ActorContext], PrivateMediaDeliveryHandler] | None = None
    if (
        media_delivery is not None
        and media_cors_policy is not None
        and delivery_activity_resolver is not None
    ):
        if media_delivery.delivery_origin != str(settings.public_app_url).rstrip("/"):
            raise MediaConfigurationError(
                "request-authenticated learner media must use the learner's same origin"
            )

        def authenticated_handler(
            database: Session, actor: ActorContext
        ) -> PrivateMediaDeliveryHandler:
            return PrivateMediaDeliveryHandler(
                storage=selected_storage,
                signer=media_delivery.signer,
                delivery_port=media_delivery,
                max_object_bytes=min(8 * 1024**3, media_delivery.range_policy.max_bytes),
                authorizer=DatabaseMediaDeliveryAuthorizer(
                    database,
                    actor,
                    signer=media_signer,
                    activity_resolver=delivery_activity_resolver,
                ),
                cors_policy=media_cors_policy,
            )

        handler_factory = authenticated_handler
    return MediaRuntime(
        service=service,
        telemetry=TelemetryRecorder(NullTelemetrySink()),
        environment=settings.environment,
        media_config=config,
        activation_verifier=activation_verifier,
        media_telemetry=MediaTelemetryRecorder(media_telemetry_exporter),
        media_delivery=media_delivery,
        media_cors_policy=media_cors_policy,
        activity_media_resolver=service.resolve_activity_media_binding_for_learning,
        media_descriptor_resolver=service.resolve_activity_media_descriptor_for_learner,
        authenticated_delivery_handler_factory=handler_factory,
    )


def create_default_media_runtime(settings: Settings) -> MediaRuntime:
    """Build the application runtime with its fail-closed composition defaults."""

    runtime = create_media_runtime(settings)
    if settings.media_staging_public_films_delivery_enabled:
        from ac_platform.media.staging_fixture_runtime import compose_staging_fixture_delivery

        return compose_staging_fixture_delivery(settings, runtime)
    return runtime


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
    "create_media_runtime",
    "create_default_media_runtime",
]
