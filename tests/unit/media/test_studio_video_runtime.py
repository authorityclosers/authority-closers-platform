from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any, cast

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from ac_platform.application.settings import Settings
from ac_platform.media.clamav_scanner import ClamAVContentScanner, ClamAVScannerConfig
from ac_platform.media.errors import MediaConfigurationError
from ac_platform.media.processing import FFmpegMediaProcessor
from ac_platform.media.runtime import create_media_runtime
from ac_platform.media.scanner import SignatureContentScanner
from ac_platform.media.studio_video_delivery import compose_filesystem_studio_video_delivery
from ac_platform.media.studio_video_runtime import (
    compose_filesystem_studio_video_runtime,
    compose_local_studio_video_runtime,
)
from ac_platform.media.video_file_storage import VideoFileStorage


def _settings(environment: str = "test") -> Settings:
    return Settings(
        environment=environment,  # type: ignore[arg-type]
        media_max_upload_bytes=1024**2,
        media_max_processing_output_bytes=8 * 1024**2,
    )


def _scanner_config() -> ClamAVScannerConfig:
    return ClamAVScannerConfig(host="127.0.0.1", max_content_bytes=512 * 1024)


def _compose(tmp_path: Path, settings: Settings, *, testing_scanner=None):
    base = create_media_runtime(settings)
    sessions = async_sessionmaker()
    composed = compose_local_studio_video_runtime(
        settings,
        base,
        sessions=sessions,
        root=tmp_path / "video-objects",
        max_store_bytes=4 * 1024**2,
        scanner_config=_scanner_config(),
        testing_scanner=testing_scanner,
    )
    return base, composed, sessions


def test_explicit_test_composition_adds_one_exact_pipeline_without_replacing_base(
    tmp_path: Path,
) -> None:
    scanner = SignatureContentScanner()
    settings = _settings()
    plain_base = create_media_runtime(settings)
    existing_avatar = cast(Any, object())
    existing_policy = cast(Any, object())
    base = replace(
        plain_base,
        local_avatar_runtime=existing_avatar,
        playback_policy_resolver=existing_policy,
    )
    sessions = async_sessionmaker()
    composed = compose_local_studio_video_runtime(
        settings,
        base,
        sessions=sessions,
        root=tmp_path / "video-objects",
        max_store_bytes=4 * 1024**2,
        scanner_config=_scanner_config(),
        testing_scanner=scanner,
    )
    studio = composed.studio_video_runtime

    assert studio is not None
    assert composed.service is base.service
    assert composed.local_avatar_runtime is existing_avatar
    assert composed.media_delivery is base.media_delivery
    assert composed.activity_media_resolver is base.activity_media_resolver
    assert composed.playback_policy_resolver is existing_policy
    assert type(studio.storage) is VideoFileStorage
    assert studio.storage is studio.service.storage
    assert studio.service.scanner is scanner
    assert type(studio.service.processor) is FFmpegMediaProcessor
    assert studio.service.processor.quota == studio.service.processing_quota
    assert studio.completion.sessions is sessions
    assert studio.processing.service is studio.service
    assert studio.worker.pipeline is studio.processing
    assert studio.max_source_bytes == 512 * 1024


def test_local_composition_uses_real_clamav_and_rejects_test_scanner(tmp_path: Path) -> None:
    settings = _settings("local")
    base = create_media_runtime(settings)

    with pytest.raises(MediaConfigurationError, match="test scanner"):
        compose_local_studio_video_runtime(
            settings,
            base,
            sessions=async_sessionmaker(),
            root=tmp_path / "video-objects",
            max_store_bytes=4 * 1024**2,
            scanner_config=_scanner_config(),
            testing_scanner=SignatureContentScanner(),
        )

    real_root = tmp_path / "real"
    real_root.mkdir()
    composed = compose_local_studio_video_runtime(
        settings,
        base,
        sessions=async_sessionmaker(),
        root=real_root / "video-objects",
        max_store_bytes=4 * 1024**2,
        scanner_config=_scanner_config(),
    )
    studio = composed.studio_video_runtime
    assert studio is not None and type(studio.service.scanner) is ClamAVContentScanner


def test_composition_rejects_nonlocal_mismatch_and_duplicate(tmp_path: Path) -> None:
    test_settings = _settings()
    base, composed, sessions = _compose(
        tmp_path, test_settings, testing_scanner=SignatureContentScanner()
    )
    arguments = {
        "sessions": sessions,
        "root": tmp_path / "another-video-objects",
        "max_store_bytes": 4 * 1024**2,
        "scanner_config": _scanner_config(),
        "testing_scanner": SignatureContentScanner(),
    }
    with pytest.raises(MediaConfigurationError, match="only once"):
        compose_local_studio_video_runtime(test_settings, composed, **arguments)

    development = _settings("development")
    with pytest.raises(MediaConfigurationError, match="local/test only"):
        compose_local_studio_video_runtime(
            development,
            create_media_runtime(development),
            **{key: value for key, value in arguments.items() if key != "testing_scanner"},
        )
    with pytest.raises(MediaConfigurationError, match="environments must match"):
        compose_local_studio_video_runtime(
            _settings("local"),
            base,
            **{key: value for key, value in arguments.items() if key != "testing_scanner"},
        )


def test_explicit_filesystem_profile_composes_deployment_graph(tmp_path: Path) -> None:
    settings = _settings(
        "test",
    ).model_copy(
        update={
            "media_filesystem_enabled": True,
            "media_filesystem_root": str(tmp_path / "video-objects"),
            "media_filesystem_avatar_root": str(tmp_path / "avatar-objects"),
            "media_scanner_unix_socket": "/run/ac-media-safety/clamd.sock",
            "media_max_upload_bytes": 2_000_000_000,
        }
    )
    base = create_media_runtime(settings, filesystem_runtime=True)
    runtime = compose_filesystem_studio_video_runtime(
        settings,
        base,
        sessions=async_sessionmaker(),
        root=tmp_path / "video-objects",
        max_store_bytes=8 * 1024**3,
        scanner_config=ClamAVScannerConfig(
            unix_socket="/run/ac-media-safety/clamd.sock",
            max_content_bytes=2_000_000_000,
            total_timeout_seconds=1800,
        ),
    )
    delivered = compose_filesystem_studio_video_delivery(settings, runtime)
    assert delivered.studio_video_runtime is not None
    assert delivered.studio_video_runtime.max_source_bytes == 2_000_000_000
    assert delivered.studio_video_runtime.storage.max_store_bytes == 8 * 1024**3
    assert delivered.authenticated_delivery_handler_factory is not None


def test_filesystem_profile_rejects_unmounted_tcp_scanner(tmp_path: Path) -> None:
    settings = _settings("test").model_copy(
        update={
            "media_filesystem_enabled": True,
            "media_filesystem_root": str(tmp_path / "video-objects"),
            "media_filesystem_avatar_root": str(tmp_path / "avatar-objects"),
            "media_scanner_unix_socket": None,
            "media_scanner_host": "127.0.0.1",
            "media_max_upload_bytes": 2_000_000_000,
        }
    )
    object.__setattr__(settings, "environment", "staging")
    with pytest.raises(ValueError, match="Unix socket"):
        # model_copy does not rerun model validators; call the same explicit
        # profile guard after changing only the environment discriminator.
        settings._validate_filesystem_media()
