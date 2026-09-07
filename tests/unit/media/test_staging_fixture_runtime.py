"""Composition negatives; real pack/import and DB grant tests live separately."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy.orm import Session

import ac_platform.http.app as app_module
import ac_platform.media.staging_fixture_runtime as composition
from ac_platform.application.settings import Settings
from ac_platform.catalog.models import GLOBAL_CATALOG_OWNER_KEY, Activity, ProgramVersion
from ac_platform.kernel.authz import ActorContext
from ac_platform.media.database_delivery_authorizer import DatabaseMediaDeliveryAuthorizer
from ac_platform.media.errors import (
    MediaConfigurationError,
    MediaForbidden,
    MediaStorageUnavailable,
)
from ac_platform.media.runtime import create_default_media_runtime, create_media_runtime
from ac_platform.media.signing import MediaSigner
from ac_platform.media.storage import InMemoryPrivateObjectStorage
from ac_platform.seed.technical_media_fixture_v2 import (
    FILM_ACTIVITY_PROMPTS,
    FILM_ACTIVITY_TITLES,
    technical_media_identity,
    technical_media_seed,
)

RELEASE = "b" * 40


def fixture_settings(tmp_path: Path, **overrides: object) -> Settings:
    values: dict[str, object] = {
        "environment": "test",
        "release_id": RELEASE,
        "public_app_url": "https://staging.authorityclosers.com",
        "public_learner_tenant_id": uuid4(),
        "operations_tenant_id": uuid4(),
        "media_stress_fixtures_enabled": True,
        "media_stress_fixtures_cache_root": str(tmp_path),
        "media_staging_public_films_delivery_enabled": True,
    }
    return Settings.model_validate(values | overrides)


@pytest.fixture
def composed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    settings = fixture_settings(tmp_path)
    calls: list[dict[str, object]] = []
    storage = InMemoryPrivateObjectStorage(MediaSigner(b"fixture-test-only-key-32-bytes-long"))
    clips = tuple(SimpleNamespace(asset_id=uuid4(), version_id=uuid4()) for _ in range(2))

    def require_scope(**values: object) -> None:
        assert values == {
            "environment": "test",
            "release_id": RELEASE,
            "tenant_id": settings.public_learner_tenant_id,
        }

    def load(**values: object) -> SimpleNamespace:
        calls.append(values)
        return SimpleNamespace(
            storage=storage,
            clips=clips,
            tenant_id=settings.public_learner_tenant_id,
            require_scope=require_scope,
        )

    monkeypatch.setattr(composition, "load_verified_staging_fixture_pack", load)
    runtime = create_default_media_runtime(settings)
    return settings, runtime, calls, clips


def catalog_pair(index: int = 0) -> tuple[Activity, ProgramVersion]:
    program, version, module, activities = technical_media_identity(RELEASE)
    seed = technical_media_seed(RELEASE)
    return (
        Activity(
            id=activities[index],
            program_id=program,
            program_version_id=version,
            module_id=module,
            scope="global",
            owner_key=GLOBAL_CATALOG_OWNER_KEY,
            tenant_id=None,
            kind="VIDEO",
            title=FILM_ACTIVITY_TITLES[index],
            prompt=FILM_ACTIVITY_PROMPTS[index],
            position=index + 1,
            is_required=True,
        ),
        ProgramVersion(
            id=version,
            program_id=program,
            scope="global",
            owner_key=GLOBAL_CATALOG_OWNER_KEY,
            tenant_id=None,
            content_digest=seed.content_digest,
            content_source_ref=seed.source_ref,
            content_seed_kind="technical-validation",
            status="published",
        ),
    )


def test_default_and_fixture_cache_alone_never_load_delivery(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def unexpected(**_values: object) -> None:
        pytest.fail("diagnostic cache settings must not activate delivery")

    monkeypatch.setattr(composition, "load_verified_staging_fixture_pack", unexpected)
    for settings in (
        Settings(environment="test"),
        fixture_settings(tmp_path, media_staging_public_films_delivery_enabled=False),
    ):
        runtime = create_default_media_runtime(settings)
        assert runtime.media_delivery is None
        assert runtime.authenticated_delivery_handler_factory is None


@pytest.mark.parametrize("environment", ["production", "development", "local"])
def test_settings_refuse_other_environments_before_any_io(tmp_path: Path, environment: str):
    with pytest.raises(ValidationError, match="staging public-film delivery"):
        fixture_settings(
            tmp_path,
            environment=environment,
            public_app_url=(
                "https://app.authorityclosers.com"
                if environment == "production"
                else "https://staging.authorityclosers.com"
            ),
        )


@pytest.mark.parametrize(
    "overrides",
    [
        {"public_learner_tenant_id": None},
        {"media_stress_fixtures_enabled": False},
        {"media_provider_enabled": True},
    ],
)
def test_settings_require_separate_explicit_scope(tmp_path: Path, overrides):
    with pytest.raises(ValidationError, match="staging public-film delivery"):
        fixture_settings(tmp_path, **overrides)


def test_loader_pins_release_tenant_and_package_without_general_activation(composed):
    settings, runtime, calls, _clips = composed
    assert calls == [
        {
            "environment": "test",
            "release_id": RELEASE,
            "tenant_id": settings.public_learner_tenant_id,
            "root": Path(settings.media_stress_fixtures_cache_root),
            "expected_manifest_sha256": composition.MANIFEST_SHA256,
        }
    ]
    assert not runtime.provider_activation_verified
    assert not runtime.learning_playback_composed
    assert runtime.playback_policy_resolver is None
    assert runtime.media_delivery.playback_ttl.total_seconds() == 300
    assert runtime.media_cors_policy.allowed_origins == ("https://staging.authorityclosers.com",)


@pytest.mark.parametrize("origin", ["https://evil.test", "http://localhost:3100"])
def test_composition_refuses_cross_origin_before_loading(tmp_path: Path, monkeypatch, origin):
    def unexpected(**_values: object) -> None:
        pytest.fail("invalid origin must precede filesystem IO")

    monkeypatch.setattr(composition, "load_verified_staging_fixture_pack", unexpected)
    with pytest.raises(MediaConfigurationError, match="exact learner origin"):
        create_default_media_runtime(fixture_settings(tmp_path, public_app_url=origin))


def test_real_loader_refuses_missing_pack_instead_of_mounting_empty_storage(tmp_path: Path):
    with pytest.raises(MediaStorageUnavailable, match="inventory is unavailable"):
        create_default_media_runtime(fixture_settings(tmp_path))


@pytest.mark.parametrize("index", [0, 1])
def test_both_exact_catalog_videos_use_shared_learning_facts(composed, index):
    _settings, runtime, _calls, _clips = composed
    row, version = catalog_pair(index)
    definition = runtime.service.delivery_activity_resolver(row, version)
    assert definition.id == row.id
    assert definition.version == f"activity:{row.id}"
    assert definition.video_duration_seconds is None  # binding supplies observed duration


@pytest.mark.parametrize(
    "field,value",
    [
        ("id", uuid4()),
        ("module_id", uuid4()),
        ("program_version_id", uuid4()),
        ("program_id", uuid4()),
        ("scope", "tenant"),
        ("owner_key", uuid4()),
        ("tenant_id", uuid4()),
        ("kind", "REFLECTION"),
        ("title", "Actual lesson"),
        ("prompt", "Edited attribution"),
    ],
)
def test_other_or_modified_catalog_content_cannot_borrow_fixture_port(composed, field, value):
    _settings, runtime, _calls, _clips = composed
    row, version = catalog_pair()
    setattr(row, field, value)
    with pytest.raises(MediaForbidden, match="outside"):
        runtime.service.delivery_activity_resolver(row, version)


@pytest.mark.parametrize(
    "field,value",
    [
        ("content_digest", "f" * 64),
        ("content_source_ref", "other"),
        ("content_seed_kind", "instructional"),
        ("tenant_id", uuid4()),
    ],
)
def test_version_provenance_is_required(composed, field, value):
    _settings, runtime, _calls, _clips = composed
    row, version = catalog_pair()
    setattr(version, field, value)
    with pytest.raises(MediaForbidden):
        runtime.service.delivery_activity_resolver(row, version)


def test_cross_tenant_binding_stops_before_database_read(composed):
    _settings, runtime, _calls, _clips = composed
    row, version = catalog_pair()
    with Session() as database:
        assert runtime.activity_media_resolver(database, uuid4(), row, version) is None


def test_factory_preserves_request_identity_and_independent_signers(composed):
    settings, runtime, _calls, _clips = composed
    actor = ActorContext(uuid4(), uuid4(), settings.public_learner_tenant_id)
    with Session() as database:
        handler = runtime.authenticated_delivery_handler_factory(database, actor)
        assert isinstance(handler.authorizer, DatabaseMediaDeliveryAuthorizer)
        assert handler.authorizer.actor == actor
        assert handler.authorizer.signer is runtime.service.signer
        assert handler.signer is runtime.media_delivery.signer
        assert handler.signer is not runtime.service.signer
        with pytest.raises(MediaForbidden, match="tenant"):
            runtime.authenticated_delivery_handler_factory(
                database, replace(actor, tenant_id=uuid4())
            )


def test_default_app_mounts_authenticated_delivery_but_not_watch_completion(composed, monkeypatch):
    settings, _runtime, _calls, _clips = composed
    monkeypatch.setattr(app_module, "settings", settings)
    application = app_module.create_app()
    paths = application.openapi()["paths"]
    assert set(paths["/v1/media/{kind}/{object_key}"]) == {"get", "head", "options"}
    assert "/v1/activities/{activity_id}/playback/start" not in paths


def test_direct_internal_composition_still_refuses_forged_production_settings(tmp_path):
    settings = fixture_settings(tmp_path).model_copy(update={"environment": "production"})
    base = create_media_runtime(Settings(environment="test"))
    with pytest.raises(MediaConfigurationError, match="configuration"):
        composition.compose_staging_fixture_delivery(settings, base)
