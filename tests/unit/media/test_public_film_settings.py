"""The production film package has its own explicit, non-provider admission."""

from pathlib import Path
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from ac_platform.application.settings import Settings


def public_film_settings(root: Path, **overrides: object) -> Settings:
    values = {
        "environment": "test",
        "release_id": "b" * 40,
        "public_app_url": "https://learner.authorityclosers.com",
        "public_learner_tenant_id": uuid4(),
        "operations_tenant_id": uuid4(),
        "media_public_films_delivery_enabled": True,
        "media_public_films_root": str(root),
    }
    return Settings.model_validate(values | overrides)


def test_default_keeps_both_public_films_and_provider_off():
    settings = Settings(environment="test")
    assert not settings.media_public_films_delivery_enabled
    assert settings.media_public_films_root is None
    assert not settings.media_provider_enabled


@pytest.mark.parametrize(
    "origin",
    ["https://learner.authorityclosers.com", "https://learner-staging.authorityclosers.com"],
)
def test_explicit_isolated_test_accepts_pinned_origin_without_fixture_or_provider(tmp_path, origin):
    settings = public_film_settings(tmp_path, public_app_url=origin)
    assert settings.media_public_films_delivery_enabled
    assert not settings.media_stress_fixtures_enabled
    assert not settings.media_provider_enabled
    assert settings.media_public_films_root == str(tmp_path)


@pytest.mark.parametrize(
    "change",
    [
        {"release_id": "local-unreleased"},
        {"release_id": "A" * 40},
        {"public_learner_tenant_id": None},
        {"public_learner_tenant_id": UUID(int=0)},
        {"environment": "local"},
        {"environment": "development"},
        {"media_provider_enabled": True},
        {"media_stress_fixtures_enabled": True},
        {"media_local_public_films_delivery_enabled": True},
        {"media_staging_public_films_delivery_enabled": True},
        {"media_local_avatar_enabled": True},
        {"media_public_films_delivery_enabled": False},
    ],
)
def test_conflicting_or_incomplete_scope_is_rejected(tmp_path, change):
    with pytest.raises(ValidationError):
        public_film_settings(tmp_path, **change)


@pytest.mark.parametrize(
    "root",
    [
        None,
        "",
        "relative",
        "../media",
        "https://files.test/media",
        "//server/share",
        "\\\\server\\share",
        " /media",
        "/media\x00",
    ],
)
def test_storage_must_be_an_explicit_local_absolute_directory(tmp_path, root):
    with pytest.raises(ValidationError, match="absolute local directory"):
        public_film_settings(tmp_path, media_public_films_root=root)


@pytest.mark.parametrize(
    "origin",
    [
        "http://learner.localhost:3100",
        "https://admin.authorityclosers.com",
        "https://coach.authorityclosers.com",
        "https://learner.authorityclosers.com.evil.test",
        "https://app.authorityclosers.com",
        "https://learner.authorityclosers.com/path",
        "https://learner.authorityclosers.com:8443",
        "https://learner.authorityclosers.com?x=1",
    ],
)
def test_no_other_surface_or_origin_can_receive_delivery(tmp_path, origin):
    with pytest.raises(ValidationError, match="exact learner origin"):
        public_film_settings(tmp_path, public_app_url=origin)
