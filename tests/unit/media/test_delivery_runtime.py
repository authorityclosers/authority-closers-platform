"""Application composition of request-bound delivery, never provider activation."""

from __future__ import annotations

from dataclasses import replace
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

import ac_platform.http.app as app_module
from ac_platform.application.settings import Settings
from ac_platform.http.learning import _default_activity_resolver
from ac_platform.kernel.authz import ActorContext
from ac_platform.media.config import MediaProviderConfig
from ac_platform.media.database_delivery_authorizer import DatabaseMediaDeliveryAuthorizer
from ac_platform.media.errors import MediaConfigurationError
from ac_platform.media.lifecycle import InMemoryMediaLifecycleHooks, MediaRetentionPolicy
from ac_platform.media.policy import SignedMediaDeliveryPort
from ac_platform.media.runtime import MediaRuntime, create_media_runtime
from ac_platform.media.signing import MediaSigner
from ac_platform.media.storage import InMemoryPrivateObjectStorage


class ExplicitTestVerifier:
    """Only a test double; not a deployment approval mechanism."""

    def __init__(self, fingerprint: str) -> None:
        self.fingerprint = fingerprint

    def verify(
        self, *, config_fingerprint: str, governance_reference: str, media_gap_reference: str
    ) -> bool:
        return (
            config_fingerprint == self.fingerprint
            and governance_reference == "AC-GOV-AUD-001"
            and media_gap_reference == "GAP-MEDIA-001"
        )


def configured_runtime(
    *, origin: str = "https://app.test", resolver: bool = True
) -> tuple[Settings, MediaRuntime]:
    settings = Settings(
        environment="test",
        public_app_url="https://app.test",
        media_provider_enabled=True,
        media_provider="minio",
        media_storage_endpoint="https://minio.test",
        media_storage_approved_endpoint_hosts="minio.test",
        media_storage_bucket="ac-media",
        media_storage_region="us-east-1",
        media_storage_access_key_id="test-access-key",
        media_storage_secret_access_key="x" * 32,
        media_delivery_origin=origin,
        media_cors_origins="https://app.test",
        media_governance_reference="AC-GOV-AUD-001",
        media_gap_reference="GAP-MEDIA-001",
    )
    config = MediaProviderConfig.from_settings(settings)
    signer = MediaSigner(b"explicit-unit-test-delivery-key-only")
    runtime = create_media_runtime(
        settings,
        storage=InMemoryPrivateObjectStorage(signer),
        lifecycle_hooks=InMemoryMediaLifecycleHooks(),
        retention_policy=MediaRetentionPolicy("unit-test-only"),
        activation_verifier=ExplicitTestVerifier(config.activation_fingerprint),
        media_delivery_handler=SignedMediaDeliveryPort(signer=signer, delivery_origin=origin),
        delivery_activity_resolver=_default_activity_resolver if resolver else None,
    )
    return settings, runtime


def test_default_runtime_never_mounts_or_enables_file_or_signed_delivery() -> None:
    runtime = create_media_runtime(Settings(environment="test"))
    assert runtime.authenticated_delivery_handler_factory is None
    assert runtime.media_delivery is None
    assert not runtime.provider_activation_verified


def test_authenticated_runtime_requires_canonical_activity_resolver() -> None:
    _, runtime = configured_runtime(resolver=False)
    assert runtime.authenticated_delivery_handler_factory is None


def test_authenticated_runtime_requires_same_origin_cookie_delivery() -> None:
    with pytest.raises(MediaConfigurationError, match="same origin"):
        configured_runtime(origin="https://media.test")


def test_factory_keeps_request_identity_and_grant_signer_separate() -> None:
    _, runtime = configured_runtime()
    factory = runtime.authenticated_delivery_handler_factory
    assert factory is not None
    assert runtime.media_delivery is not None
    first_actor = ActorContext(uuid4(), uuid4(), uuid4())
    second_actor = ActorContext(uuid4(), uuid4(), uuid4())
    with Session() as database:
        first = factory(database, first_actor)
        second = factory(database, second_actor)
        assert first is not second
        assert first.authorizer is not second.authorizer
        assert isinstance(first.authorizer, DatabaseMediaDeliveryAuthorizer)
        assert isinstance(second.authorizer, DatabaseMediaDeliveryAuthorizer)
        assert first.authorizer.actor == first_actor
        assert second.authorizer.actor == second_actor
        assert first.authorizer.signer is runtime.service.signer
        assert first.signer is runtime.media_delivery.signer
        assert first.storage is runtime.service.storage


def test_explicit_test_application_mounts_only_authenticated_delivery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings, runtime = configured_runtime()
    monkeypatch.setattr(app_module, "settings", settings)
    application = app_module.create_app(media_runtime=runtime)
    paths = application.openapi()["paths"]
    assert set(paths["/v1/media/{kind}/{object_key}"]) == {"get", "head", "options"}
    # Issuing playable media must not silently enable completion/evidence policy.
    assert "/v1/activities/{activity_id}/playback/start" not in paths


def test_application_rejects_handler_factory_without_cors_policy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings, runtime = configured_runtime()
    monkeypatch.setattr(app_module, "settings", settings)
    with pytest.raises(RuntimeError, match="exact-origin policy"):
        app_module.create_app(media_runtime=replace(runtime, media_cors_policy=None))


def test_non_local_runtime_cannot_enable_itself_by_resolver_injection() -> None:
    with pytest.raises(MediaConfigurationError, match="non-local"):
        create_media_runtime(
            Settings(environment="development"),
            delivery_activity_resolver=_default_activity_resolver,
        )
