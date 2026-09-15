"""Explicit local composition for the complete private Studio video path.

The default application runtime remains inert.  This module adds a dedicated
Studio service alongside existing avatar and technical-film services; it never
replaces their storage or delivery resolvers.  Local composition uses the real
ClamAV and FFmpeg adapters.  A deterministic scanner may be injected only by a
test runtime.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path

from ac_platform.application.settings import Settings
from ac_platform.media.clamav_scanner import ClamAVContentScanner, ClamAVScannerConfig
from ac_platform.media.config import MediaProviderConfig
from ac_platform.media.errors import MediaConfigurationError
from ac_platform.media.processing import FFmpegMediaProcessor, ProcessingQuota
from ac_platform.media.runtime import MediaRuntime, create_media_runtime
from ac_platform.media.scanner import ContentScanner, SignatureContentScanner
from ac_platform.media.service import MediaService
from ac_platform.media.studio_video_completion import (
    StudioCompletionSessionFactory,
    StudioVideoCompletion,
)
from ac_platform.media.studio_video_processing import StudioVideoProcessing
from ac_platform.media.studio_video_worker import StudioVideoJobWorker
from ac_platform.media.video_file_storage import VideoFileStorage


@dataclass(frozen=True, slots=True)
class StudioVideoRuntime:
    """One instance graph for admission, bytes, scan, encode and finalization."""

    settings: Settings
    sessions: StudioCompletionSessionFactory
    scanner_config: ClamAVScannerConfig
    scanner: ContentScanner
    storage: VideoFileStorage
    service: MediaService
    completion: StudioVideoCompletion
    processing: StudioVideoProcessing
    worker: StudioVideoJobWorker
    max_source_bytes: int

    def __post_init__(self) -> None:
        self.validate()

    def validate(self) -> None:
        """Recheck the mutable service graph at application startup."""

        if (
            self.settings.environment not in {"local", "test", "staging", "production"}
            or (
                self.settings.environment in {"staging", "production"}
                and not self.settings.media_filesystem_enabled
            )
            or type(self.storage) is not VideoFileStorage
            or self.service.storage is not self.storage
            or self.service.scanner is not self.scanner
            or type(self.service.processor) is not FFmpegMediaProcessor
            or self.service.processor.quota != self.service.processing_quota
            or self.completion.sessions is not self.sessions
            or self.completion.service is not self.service
            or self.completion.storage is not self.storage
            or self.processing.service is not self.service
            or self.worker.pipeline is not self.processing
            or self.worker._session_factory is not self.sessions
            or type(self.scanner_config) is not ClamAVScannerConfig
            or (
                self.settings.environment == "local"
                and (
                    type(self.scanner) is not ClamAVContentScanner
                    or self.scanner._config is not self.scanner_config
                )
            )
            or (
                self.settings.environment == "test"
                and type(self.scanner) not in {ClamAVContentScanner, SignatureContentScanner}
            )
            or type(self.max_source_bytes) is not int
            or self.max_source_bytes
            != min(
                self.storage.max_object_bytes,
                self.scanner_config.max_content_bytes,
                self.service.max_upload_bytes,
                self.service.processing_quota.max_source_bytes,
            )
        ):
            raise MediaConfigurationError("The Studio video runtime instance graph is invalid.")


def _compose_studio_video_runtime(
    settings: Settings,
    runtime: MediaRuntime,
    *,
    sessions: StudioCompletionSessionFactory,
    root: Path,
    max_store_bytes: int,
    scanner_config: ClamAVScannerConfig,
    max_objects: int = 16_384,
    ffmpeg_binary: str = "ffmpeg",
    testing_scanner: ContentScanner | None = None,
    filesystem_runtime: bool = False,
) -> MediaRuntime:
    """Add an opt-in same-host Studio pipeline without activating it by default.

    ``testing_scanner`` exists solely for deterministic test composition.  A
    runnable local application always receives the real clamd INSTREAM adapter.
    This factory does not attest the daemon's operational policy; deployment
    promotion still requires the separate proof documented by that adapter.
    """

    if filesystem_runtime:
        if not settings.media_filesystem_enabled or settings.environment not in {
            "test",
            "staging",
            "production",
        }:
            raise MediaConfigurationError("Filesystem Studio video composition is not enabled.")
    elif settings.environment not in {"local", "test"}:
        raise MediaConfigurationError("Studio video composition is local/test only.")
    if runtime.environment != settings.environment:
        raise MediaConfigurationError("Studio video and base media environments must match.")
    if runtime.studio_video_runtime is not None:
        raise MediaConfigurationError("Studio video composition may be installed only once.")
    if settings.media_provider_enabled:
        raise MediaConfigurationError(
            "Studio video local storage cannot activate a media provider."
        )
    if testing_scanner is not None and settings.environment != "test":
        raise MediaConfigurationError("A test scanner cannot be used by a local Studio runtime.")
    if testing_scanner is not None and type(testing_scanner) is not SignatureContentScanner:
        raise MediaConfigurationError("Studio test composition requires its deterministic scanner.")
    if type(scanner_config) is not ClamAVScannerConfig:
        raise MediaConfigurationError("Studio video composition requires bounded ClamAV settings.")

    config = MediaProviderConfig.from_settings(settings)
    max_source_bytes = min(config.max_upload_bytes, scanner_config.max_content_bytes)
    quota = ProcessingQuota(
        max_source_bytes=config.max_upload_bytes,
        max_output_bytes=config.max_processing_output_bytes,
        max_renditions=config.max_renditions,
        max_caption_bytes=config.max_processing_caption_bytes,
    )
    processor = FFmpegMediaProcessor(ffmpeg_binary=ffmpeg_binary, quota=quota)
    scanner = (
        testing_scanner if testing_scanner is not None else ClamAVContentScanner(scanner_config)
    )
    storage = VideoFileStorage(
        root=root,
        max_object_bytes=max_source_bytes,
        max_store_bytes=max_store_bytes,
        max_objects=max_objects,
    )
    service = create_media_runtime(
        settings,
        storage=storage,
        scanner=scanner,
        processor=processor,
        filesystem_runtime=filesystem_runtime,
    ).service
    processing = StudioVideoProcessing(service)
    completion = StudioVideoCompletion(sessions, service, storage)
    worker = StudioVideoJobWorker(sessions, processing)
    studio = StudioVideoRuntime(
        settings=settings,
        sessions=sessions,
        scanner_config=scanner_config,
        scanner=scanner,
        storage=storage,
        service=service,
        completion=completion,
        processing=processing,
        worker=worker,
        max_source_bytes=min(
            storage.max_object_bytes,
            scanner_config.max_content_bytes,
            service.max_upload_bytes,
            service.processing_quota.max_source_bytes,
        ),
    )
    return replace(runtime, studio_video_runtime=studio)


def compose_local_studio_video_runtime(
    settings: Settings,
    runtime: MediaRuntime,
    *,
    sessions: StudioCompletionSessionFactory,
    root: Path,
    max_store_bytes: int,
    scanner_config: ClamAVScannerConfig,
    max_objects: int = 16_384,
    ffmpeg_binary: str = "ffmpeg",
    testing_scanner: ContentScanner | None = None,
) -> MediaRuntime:
    """Add the explicit local/test Studio pipeline."""

    return _compose_studio_video_runtime(
        settings,
        runtime,
        sessions=sessions,
        root=root,
        max_store_bytes=max_store_bytes,
        scanner_config=scanner_config,
        max_objects=max_objects,
        ffmpeg_binary=ffmpeg_binary,
        testing_scanner=testing_scanner,
    )


def compose_filesystem_studio_video_runtime(
    settings: Settings,
    runtime: MediaRuntime,
    *,
    sessions: StudioCompletionSessionFactory,
    root: Path,
    max_store_bytes: int,
    scanner_config: ClamAVScannerConfig,
    max_objects: int = 16_384,
    ffmpeg_binary: str = "ffmpeg",
) -> MediaRuntime:
    """Compose the bounded source-owned filesystem profile for deployment."""

    if settings.environment in {"staging", "production"} and scanner_config.unix_socket is None:
        raise MediaConfigurationError("Deployment Studio video requires the mounted ClamAV socket.")
    return _compose_studio_video_runtime(
        settings,
        runtime,
        sessions=sessions,
        root=root,
        max_store_bytes=max_store_bytes,
        scanner_config=scanner_config,
        max_objects=max_objects,
        ffmpeg_binary=ffmpeg_binary,
        filesystem_runtime=True,
    )


__all__ = [
    "StudioVideoRuntime",
    "compose_filesystem_studio_video_runtime",
    "compose_local_studio_video_runtime",
]
