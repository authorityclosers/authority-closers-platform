"""Local delivery opt-in cannot change deployed/provider authorization."""

from dataclasses import replace
from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import ValidationError

import ac_platform.media.staging_fixture_runtime as composition
from ac_platform.application.settings import Settings
from ac_platform.media.errors import MediaConfigurationError
from ac_platform.media.policy import SignedMediaDeliveryPort
from ac_platform.media.runtime import create_default_media_runtime, create_media_runtime
from ac_platform.media.signing import MediaSigner
from ac_platform.media.storage import InMemoryPrivateObjectStorage


def local_settings(tmp_path, **overrides):
    return Settings(
        _env_file=None,
        **{
            "environment": "local",
            "release_id": "a" * 40,
            "public_app_url": "http://learner.localhost:3100",
            "public_learner_tenant_id": uuid4(),
            "operations_tenant_id": uuid4(),
            "media_stress_fixtures_enabled": True,
            "media_stress_fixtures_cache_root": str(tmp_path),
            "media_local_public_films_delivery_enabled": True,
            **overrides,
        },
    )


@pytest.mark.parametrize("environment", ["production", "staging", "test", "development"])
def test_local_flag_cannot_be_activated_in_other_environments(tmp_path, environment):
    with pytest.raises(ValidationError):
        local_settings(tmp_path, environment=environment)


@pytest.mark.parametrize(
    "overrides",
    [
        {"media_stress_fixtures_enabled": False},
        {"media_provider_enabled": True},
        {"public_learner_tenant_id": None},
        {"media_staging_public_films_delivery_enabled": True},
        {"media_local_public_films_delivery_enabled": False},
    ],
)
def test_local_opt_in_remains_explicit_and_separate(tmp_path, overrides):
    with pytest.raises(ValidationError):
        local_settings(tmp_path, **overrides)


@pytest.mark.parametrize(
    "origin",
    [
        "http://remote.example:3100",
        "http://127.0.0.1.remote.example:3100",
        "http://learner.localhost:3100/path",
        "http://learner.localhost:3100?redirect=elsewhere",
        "http://learner.localhost:3100#fragment",
        "http://username@learner.localhost:3100",
        "https://staging.authorityclosers.com",
        "http://learner.localhost",
    ],
)
def test_nonlocal_or_ambiguous_origins_fail_before_file_io(tmp_path, monkeypatch, origin):
    def unexpected(**_kwargs):
        pytest.fail("Invalid configuration must not read a pack.")

    monkeypatch.setattr(composition, "load_verified_staging_fixture_pack", unexpected)
    with pytest.raises(MediaConfigurationError):
        create_default_media_runtime(local_settings(tmp_path, public_app_url=origin))


def test_local_adapter_preserves_pinned_inventory_and_database_authorization(tmp_path, monkeypatch):
    settings = local_settings(tmp_path)
    calls = []
    scope_checks = []
    storage = InMemoryPrivateObjectStorage(MediaSigner(b"local-test-signing-key-at-least-32-bytes"))
    pack = SimpleNamespace(
        tenant_id=settings.public_learner_tenant_id,
        clips=tuple(SimpleNamespace(asset_id=uuid4(), version_id=uuid4()) for _ in range(2)),
        storage=storage,
        require_scope=lambda **kwargs: scope_checks.append(kwargs),
    )

    def load(**kwargs):
        calls.append(kwargs)
        return pack

    monkeypatch.setattr(composition, "load_verified_staging_fixture_pack", load)
    runtime = create_default_media_runtime(settings)
    assert calls[0]["environment"] == "test"
    assert calls[0]["expected_manifest_sha256"] == composition.MANIFEST_SHA256
    assert scope_checks == [
        {
            "environment": "test",
            "release_id": settings.release_id,
            "tenant_id": settings.public_learner_tenant_id,
        }
    ]
    assert runtime.environment == "local"
    assert runtime.media_delivery.delivery_origin == "http://learner.localhost:3100"
    assert runtime.authenticated_delivery_handler_factory is not None
    assert runtime.activity_media_resolver is not None
    assert not runtime.provider_activation_verified
    assert runtime.playback_policy_resolver is None  # films are not official lesson evidence
    with pytest.raises(MediaConfigurationError):
        composition.compose_local_fixture_delivery(
            settings, replace(runtime, environment="staging")
        )
    with pytest.raises(MediaConfigurationError):
        composition.compose_staging_fixture_delivery(settings, create_media_runtime(settings))


def test_signed_delivery_is_https_by_default_and_http_opt_in_is_loopback_only():
    signer = MediaSigner(b"local-test-signing-key-at-least-32-bytes")
    with pytest.raises(ValueError):
        SignedMediaDeliveryPort(signer=signer, delivery_origin="http://learner.localhost:3100")
    assert (
        SignedMediaDeliveryPort(
            signer=signer, delivery_origin="http://learner.localhost:3100", allow_loopback_http=True
        ).delivery_origin
        == "http://learner.localhost:3100"
    )
    for origin in ("http://remote.example", "http://localhost.evil", "https://ok.example?query=x"):
        with pytest.raises(ValueError):
            SignedMediaDeliveryPort(signer=signer, delivery_origin=origin, allow_loopback_http=True)
