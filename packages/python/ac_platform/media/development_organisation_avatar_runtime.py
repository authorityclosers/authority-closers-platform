"""Opt-in persistent dev organisation logos, with no generic media activation."""

from __future__ import annotations

import os
import stat
from dataclasses import replace
from pathlib import Path

from ac_platform.application.settings import Settings
from ac_platform.media.clamav_scanner import ClamAVContentScanner, ClamAVScannerConfig
from ac_platform.media.errors import MediaConfigurationError, MediaStorageUnavailable
from ac_platform.media.local_avatar_processing import MAX_LOGO_BYTES
from ac_platform.media.local_avatar_runtime import LocalAvatarMediaService, LocalAvatarRuntime
from ac_platform.media.local_avatar_storage import LocalAvatarStorage, require_plain_path
from ac_platform.media.runtime import MediaRuntime, _derive
from ac_platform.media.signing import MediaSigner


def require_private_root(root: Path) -> None:
    """Root provisions the directory; the API may neither adopt nor repair it."""
    require_plain_path(root)
    try:
        info = root.stat()
    except OSError:
        raise MediaStorageUnavailable(
            "The private dev organisation avatar root is missing."
        ) from None
    if (
        not stat.S_ISDIR(info.st_mode)
        or info.st_uid != os.geteuid()
        or info.st_gid != os.getegid()
        or stat.S_IMODE(info.st_mode) != 0o700
        or not os.access(root, os.W_OK | os.X_OK)
    ):
        raise MediaStorageUnavailable("The private dev organisation avatar root is unsafe.")


def require_private_scanner(endpoint: Path) -> None:
    require_plain_path(endpoint)
    try:
        directory, socket = endpoint.parent.stat(), endpoint.stat()
    except OSError:
        raise MediaStorageUnavailable("The private dev organisation scanner is missing.") from None
    if (
        directory.st_uid != 100
        or directory.st_gid != 10001
        or stat.S_IMODE(directory.st_mode) != 0o2750
        or not stat.S_ISSOCK(socket.st_mode)
        or socket.st_uid != 100
        or socket.st_gid != 10001
        or stat.S_IMODE(socket.st_mode) != 0o666
    ):
        raise MediaStorageUnavailable("The private dev organisation scanner is unsafe.")


def compose_development_organisation_avatar_runtime(
    settings: Settings, base: MediaRuntime
) -> MediaRuntime:
    # Recheck admission at the composition boundary, including model_copy callers.
    settings._validate_development_organisation_avatar()
    if (
        not settings.media_development_organisation_avatar_enabled
        or base.environment != "development"
        or base.provider_activation_verified
        or any(
            value is not None
            for value in (
                base.local_avatar_runtime,
                base.filesystem_avatar_runtime,
                base.organisation_avatar_runtime,
                base.studio_video_runtime,
                base.media_delivery,
                base.playback_policy_resolver,
                base.authenticated_delivery_handler_factory,
            )
        )
    ):
        raise MediaConfigurationError("Dev organisation logos require their isolated opt-in.")
    root = Path(settings.media_development_organisation_avatar_root or "")
    require_private_root(root)
    require_private_scanner(
        Path(settings.media_development_organisation_avatar_scanner_socket or "")
    )
    storage = LocalAvatarStorage(
        root=root,
        signer=MediaSigner(
            _derive(settings.session_token_pepper.get_secret_value(), b"dev-organisation-logo-v1")
        ),
        fallback=base.service.storage,
        origin="https://salesxray-dev.authorityclosers.com",
        marker_name=".development-organisation-avatar-store",
        marker=b"AC private development organisation avatar objects v1\n",
    )
    scanner = ClamAVContentScanner(
        ClamAVScannerConfig(
            unix_socket=settings.media_development_organisation_avatar_scanner_socket,
            max_content_bytes=MAX_LOGO_BYTES,
            total_timeout_seconds=30.0,
        )
    )
    # Only the organisation routes receive this service. No upload URL, delivery
    # handler, learning resolver, video worker or provider graph is composed.
    service = LocalAvatarMediaService(
        storage=storage,
        signer=base.service.signer,
        webhook_secret=base.service.webhook_secret,
        scanner=scanner,
        max_upload_bytes=MAX_LOGO_BYTES,
    )
    return replace(base, organisation_avatar_runtime=LocalAvatarRuntime(storage, service))
