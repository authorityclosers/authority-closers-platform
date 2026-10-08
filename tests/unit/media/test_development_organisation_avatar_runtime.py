"""Dev-only logo admission, persistent storage and unchanged default media graph."""

from dataclasses import replace
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from ac_platform.application import settings as settings_module
from ac_platform.application.settings import (
    DEVELOPMENT_ORGANISATION_AVATAR_ROOT,
    DEVELOPMENT_ORGANISATION_AVATAR_SOCKET,
    Settings,
)
from ac_platform.media import development_organisation_avatar_runtime as module
from ac_platform.media.clamav_scanner import ClamAVContentScanner
from ac_platform.media.errors import MediaConfigurationError, MediaStorageUnavailable
from ac_platform.media.runtime import create_default_media_runtime, create_media_runtime
from ac_platform.media.scanner import FailClosedScanner
from ac_platform.media.storage import UnconfiguredPrivateObjectStorage


def dev_values(**changes):
    return {
        "_env_file": None,
        "environment": "development",
        "media_development_organisation_avatar_enabled": True,
        "media_development_organisation_avatar_root": DEVELOPMENT_ORGANISATION_AVATAR_ROOT,
        "media_development_organisation_avatar_scanner_socket": (
            DEVELOPMENT_ORGANISATION_AVATAR_SOCKET
        ),
        **changes,
    }


@pytest.fixture
def dev_store(tmp_path, monkeypatch):
    root = tmp_path / "avatar-objects"
    root.mkdir(mode=0o700)
    # Only remap fixed host paths. All composition and store admission still runs.
    monkeypatch.setattr(settings_module, "DEVELOPMENT_ORGANISATION_AVATAR_ROOT", str(root))
    monkeypatch.setattr(module, "require_private_scanner", lambda path: None)
    return Settings(
        **dev_values(
            media_development_organisation_avatar_root=str(root),
        )
    )


@pytest.mark.parametrize("environment", ["local", "test", "development"])
def test_default_stays_inert(environment):
    runtime = create_default_media_runtime(Settings(_env_file=None, environment=environment))
    assert runtime.organisation_avatar_runtime is None
    assert isinstance(runtime.service.scanner, FailClosedScanner)


@pytest.mark.parametrize("environment", ["local", "test", "staging", "production"])
def test_dev_activation_refuses_other_environments(environment):
    with pytest.raises(ValidationError, match="require environment=development"):
        Settings(**dev_values(environment=environment))


@pytest.mark.parametrize(
    "changes",
    [
        {"media_development_organisation_avatar_enabled": False},
        {"media_development_organisation_avatar_root": None},
        {"media_development_organisation_avatar_root": "/tmp/avatar-objects"},  # noqa: S108
        {"media_development_organisation_avatar_root": DEVELOPMENT_ORGANISATION_AVATAR_ROOT + "/"},
        {
            "media_development_organisation_avatar_root": (
                "/srv/authority-closers/sales-xray/staging/avatar-objects"
            )
        },
        {"media_development_organisation_avatar_scanner_socket": None},
        {"media_development_organisation_avatar_scanner_socket": "/run/ac-media-safety/clamd.sock"},
    ],
)
def test_paths_and_activation_are_exact(changes):
    with pytest.raises(ValidationError, match="organisation avatar"):
        Settings(**dev_values(**changes))


def test_rechecks_settings_and_base_environment(dev_store):
    base = create_media_runtime(dev_store)
    with pytest.raises(MediaConfigurationError):
        module.compose_development_organisation_avatar_runtime(
            dev_store, replace(base, environment="staging")
        )
    with pytest.raises(ValueError, match="exact private dev paths"):
        module.compose_development_organisation_avatar_runtime(
            dev_store.model_copy(update={"media_development_organisation_avatar_root": "/tmp"}),  # noqa: S108
            base,
        )
    with pytest.raises(ValueError, match="cannot share media activation"):
        module.compose_development_organisation_avatar_runtime(
            dev_store.model_copy(update={"media_filesystem_enabled": True}), base
        )


def test_logo_composition_is_persistent_and_does_not_activate_generic_media(dev_store):
    runtime = create_default_media_runtime(dev_store)
    logo = runtime.organisation_avatar_runtime
    assert logo is not None and isinstance(logo.service.scanner, ClamAVContentScanner)
    assert logo.service.scanner._config.max_content_bytes == 2 * 1024 * 1024
    assert logo.service.scanner._config.total_timeout_seconds == 30.0
    assert isinstance(runtime.service.storage, UnconfiguredPrivateObjectStorage)
    assert runtime.studio_video_runtime is None
    assert runtime.local_avatar_runtime is runtime.filesystem_avatar_runtime is None
    assert runtime.media_delivery is runtime.authenticated_delivery_handler_factory is None
    assert not runtime.provider_activation_verified and not runtime.learning_playback_composed
    key = (
        "tenants/11111111-1111-4111-8111-111111111111/media/avatar/"
        "11111111-1111-4111-8111-111111111111/"
        "22222222-2222-4222-8222-222222222222/original/avatar/512"
    )
    logo.storage.put(object_key=key, body=b"fictional image", content_type="image/webp")
    reopened = create_default_media_runtime(dev_store).organisation_avatar_runtime
    assert reopened.storage.read(key) == b"fictional image"
    with pytest.raises(MediaStorageUnavailable):
        reopened.storage.read("tenants/foreign/media/video/asset/version/original")


def test_private_root_refuses_missing_permissions_and_links(tmp_path):
    root = tmp_path / "avatar-objects"
    with pytest.raises(MediaStorageUnavailable):
        module.require_private_root(root)
    root.mkdir(mode=0o755)
    root.chmod(0o755)  # Keep the unsafe fixture independent of the runner's umask.
    with pytest.raises(MediaStorageUnavailable, match="unsafe"):
        module.require_private_root(root)
    root.chmod(0o700)
    module.require_private_root(root)
    link = tmp_path / "link"
    link.symlink_to(root, target_is_directory=True)
    with pytest.raises(MediaStorageUnavailable, match="links"):
        module.require_private_root(link)


@pytest.mark.parametrize("identity", ["geteuid", "getegid"])
def test_foreign_owner_and_group_are_refused(tmp_path, monkeypatch, identity):
    root = tmp_path / "avatar-objects"
    root.mkdir(mode=0o700)
    wrong = getattr(module.os, identity)() + 1
    monkeypatch.setattr(module.os, identity, lambda: wrong)
    with pytest.raises(MediaStorageUnavailable, match="unsafe"):
        module.require_private_root(root)


def test_existing_local_or_deployment_store_is_not_adopted(dev_store):
    from pathlib import Path

    (
        Path(dev_store.media_development_organisation_avatar_root) / ".filesystem-avatar-store"
    ).write_text("AC private filesystem avatar objects v1\n")
    with pytest.raises(MediaStorageUnavailable, match="unmarked"):
        create_default_media_runtime(dev_store)


def test_existing_dev_marker_must_match(dev_store):
    from pathlib import Path

    (
        Path(dev_store.media_development_organisation_avatar_root)
        / ".development-organisation-avatar-store"
    ).write_text("foreign marker")
    with pytest.raises(MediaStorageUnavailable, match="marker is invalid"):
        create_default_media_runtime(dev_store)


def test_root_must_be_writable(dev_store, monkeypatch):
    from pathlib import Path

    monkeypatch.setattr(module.os, "access", lambda *args: False)
    with pytest.raises(MediaStorageUnavailable, match="unsafe"):
        module.require_private_root(Path(dev_store.media_development_organisation_avatar_root))


def test_scanner_cannot_be_linked(tmp_path):
    endpoint = tmp_path / "socket"
    endpoint.symlink_to(tmp_path / "missing")
    with pytest.raises(MediaStorageUnavailable, match="links"):
        module.require_private_scanner(endpoint)


def test_private_scanner_refuses_missing_file_or_wrong_ownership(tmp_path):
    endpoint = tmp_path / "clamd.sock"
    with pytest.raises(MediaStorageUnavailable, match="missing"):
        module.require_private_scanner(endpoint)
    endpoint.touch()
    with pytest.raises(MediaStorageUnavailable, match="unsafe"):
        module.require_private_scanner(endpoint)


def test_app_composes_logos_without_opening_avatar_upload_routes(dev_store, monkeypatch):
    import ac_platform.http.app as app_module

    monkeypatch.setattr(app_module, "settings", dev_store)
    application = app_module.create_app()
    assert application.state.organisation_avatar_runtime is not None
    paths = application.openapi()["paths"]
    assert "/v1/organisation/logo" in paths
    assert not any(
        "filesystem-avatar-upload" in path or "local-avatar-upload" in path for path in paths
    )
    assert application.state.studio_video_worker is None
    with pytest.raises(RuntimeError, match="rejects injected media"):
        app_module.create_app(media_runtime=create_media_runtime(dev_store))


def test_exact_private_scanner_metadata_is_admitted(tmp_path, monkeypatch):
    endpoint = tmp_path / "clamd.sock"
    endpoint.touch()
    real_stat = module.Path.stat

    def metadata(path, **kwargs):
        if path in {endpoint, endpoint.parent}:
            return SimpleNamespace(
                st_uid=100,
                st_gid=10001,
                st_mode=(0o140666 if path == endpoint else 0o042750),
            )
        return real_stat(path, **kwargs)

    monkeypatch.setattr(module.Path, "stat", metadata)
    module.require_private_scanner(endpoint)


@pytest.mark.parametrize(
    "setting",
    [
        "media_provider_enabled",
        "media_filesystem_enabled",
        "media_local_avatar_enabled",
        "media_stress_fixtures_enabled",
        "media_public_films_delivery_enabled",
        "media_staging_public_films_delivery_enabled",
        "media_local_public_films_delivery_enabled",
    ],
)
def test_other_media_activation_is_refused(dev_store, setting):
    with pytest.raises(ValueError, match="cannot share media activation"):
        module.compose_development_organisation_avatar_runtime(
            dev_store.model_copy(update={setting: True}), create_media_runtime(dev_store)
        )


@pytest.mark.parametrize(
    "target,field,value",
    [
        ("directory", "st_uid", 101),
        ("directory", "st_gid", 100),
        ("directory", "st_mode", 0o042755),
        ("socket", "st_uid", 0),
        ("socket", "st_gid", 100),
        ("socket", "st_mode", 0o100666),
        ("socket", "st_mode", 0o140777),
    ],
)
def test_scanner_admission_refuses_each_unsafe_metadata_field(
    tmp_path, monkeypatch, target, field, value
):
    endpoint = tmp_path / "clamd.sock"
    endpoint.touch()
    real_stat = module.Path.stat

    def metadata(path, **kwargs):
        if path in {endpoint, endpoint.parent}:
            values = dict(st_uid=100, st_gid=10001, st_mode=0o042750)
            if path == endpoint:
                values["st_mode"] = 0o140666
            if path == (endpoint if target == "socket" else endpoint.parent):
                values[field] = value
            return SimpleNamespace(**values)
        return real_stat(path, **kwargs)

    monkeypatch.setattr(module.Path, "stat", metadata)
    with pytest.raises(MediaStorageUnavailable, match="unsafe"):
        module.require_private_scanner(endpoint)
