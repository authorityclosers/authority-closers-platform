"""Composition contracts; real package and database proofs are tested separately."""

from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

import ac_platform.media.public_film_runtime as composition
from ac_platform.catalog.models import Activity, ProgramVersion
from ac_platform.kernel.authz import ActorContext
from ac_platform.media.database_delivery_authorizer import DatabaseMediaDeliveryAuthorizer
from ac_platform.media.errors import MediaConfigurationError, MediaForbidden
from ac_platform.media.runtime import create_default_media_runtime, create_media_runtime
from ac_platform.media.signing import MediaSigner
from ac_platform.media.storage import InMemoryPrivateObjectStorage
from tests.unit.media.test_public_film_settings import public_film_settings


@pytest.fixture
def composed(tmp_path, monkeypatch):
    settings = public_film_settings(tmp_path)
    base = create_media_runtime(settings)
    storage = InMemoryPrivateObjectStorage(MediaSigner(b"public-film-test-only-signer-32-bytes"))
    clips = tuple(SimpleNamespace(asset_id=uuid4(), version_id=uuid4()) for _ in range(2))
    rows = tuple(Activity(id=uuid4()) for _ in clips)
    version = ProgramVersion(id=uuid4())
    catalog = SimpleNamespace(
        activity_ids=tuple(row.id for row in rows),
        program_version_id=version.id,
        matches_catalog=lambda row, candidate: row in rows and candidate is version,
    )
    calls = []
    scopes = []
    pack = SimpleNamespace(
        storage=storage,
        clips=clips,
        tenant_id=settings.public_learner_tenant_id,
        require_scope=lambda **kwargs: scopes.append(kwargs),
    )

    def load(**kwargs):
        calls.append(kwargs)
        return pack

    monkeypatch.setattr(composition, "load_verified_public_film_pack", load)
    monkeypatch.setattr(
        composition, "public_film_catalog", lambda loaded: catalog if loaded is pack else None
    )
    runtime = composition.compose_public_film_delivery(settings, base)
    return SimpleNamespace(
        settings=settings,
        base=base,
        runtime=runtime,
        storage=storage,
        clips=clips,
        rows=rows,
        version=version,
        calls=calls,
        scopes=scopes,
    )


def test_pins_package_release_tenant_and_local_root_without_provider_or_evidence(composed):
    h = composed
    assert h.calls == [
        {
            "environment": "test",
            "release_id": h.settings.release_id,
            "tenant_id": h.settings.public_learner_tenant_id,
            "root": composition.Path(h.settings.media_public_films_root),
            "expected_manifest_sha256": composition.MANIFEST_SHA256,
        }
    ]
    assert h.scopes == [
        {
            "environment": "test",
            "release_id": h.settings.release_id,
            "tenant_id": h.settings.public_learner_tenant_id,
        }
    ]
    assert h.runtime.media_cors_policy.allowed_origins == ("https://learner.authorityclosers.com",)
    assert h.runtime.media_delivery.delivery_origin == "https://learner.authorityclosers.com"
    assert h.runtime.media_delivery.playback_ttl.total_seconds() == 300
    assert h.runtime.service.storage is h.storage
    assert not h.runtime.provider_activation_verified
    assert not h.runtime.learning_playback_composed
    assert h.runtime.playback_policy_resolver is None


def test_default_factory_selects_new_package_only_with_explicit_admission(composed):
    runtime = create_default_media_runtime(composed.settings)
    assert runtime.authenticated_delivery_handler_factory is not None
    assert runtime.playback_policy_resolver is None
    assert len(composed.calls) == 2


@pytest.mark.parametrize(
    "updates",
    [
        {"environment": "local"},
        {"environment": "development"},
        {"media_public_films_delivery_enabled": False},
        {"media_provider_enabled": True},
        {"media_stress_fixtures_enabled": True},
        {"media_local_public_films_delivery_enabled": True},
        {"media_staging_public_films_delivery_enabled": True},
        {"release_id": "short"},
        {"public_learner_tenant_id": None},
        {"media_public_films_root": None},
        {"media_public_films_root": "relative"},
        {"public_app_url": "https://coach.authorityclosers.com"},
    ],
)
def test_forged_settings_cannot_bypass_admission_before_filesystem_reads(composed, updates):
    h = composed
    with pytest.raises(MediaConfigurationError):
        composition.compose_public_film_delivery(h.settings.model_copy(update=updates), h.base)
    assert len(h.calls) == 1


def test_existing_delivery_or_different_environment_is_not_overridden(composed):
    h = composed
    for base in [h.runtime, replace(h.base, environment="local")]:
        with pytest.raises(MediaConfigurationError):
            composition.compose_public_film_delivery(h.settings, base)
    assert len(h.calls) == 1


def test_catalog_or_tenant_mismatch_stops_before_database_read(composed):
    h = composed
    with Session() as database:
        for tenant, row, version in [
            (uuid4(), h.rows[0], h.version),
            (h.settings.public_learner_tenant_id, Activity(id=uuid4()), h.version),
            (h.settings.public_learner_tenant_id, h.rows[0], ProgramVersion(id=uuid4())),
        ]:
            assert h.runtime.activity_media_resolver(database, tenant, row, version) is None
    with pytest.raises(MediaForbidden):
        h.runtime.service.delivery_activity_resolver(Activity(id=uuid4()), h.version)


@pytest.mark.parametrize("index", [0, 1])
def test_only_exact_pack_media_pair_is_admitted_for_each_catalog_activity(
    composed, monkeypatch, index
):
    h = composed
    clip = h.clips[index]
    binding = SimpleNamespace(asset_id=clip.asset_id, version_id=clip.version_id)
    monkeypatch.setattr(
        composition, "resolve_activity_media_binding_for_learning", lambda *args: binding
    )
    with Session() as database:
        args = (database, h.settings.public_learner_tenant_id, h.rows[index], h.version)
        assert h.runtime.activity_media_resolver(*args) is binding
        binding.version_id = uuid4()
        assert h.runtime.activity_media_resolver(*args) is None
        binding.version_id = clip.version_id
        binding.asset_id = uuid4()
        assert h.runtime.activity_media_resolver(*args) is None


def test_handler_preserves_request_identity_and_database_grant_authorization(composed):
    h = composed
    actor = ActorContext(uuid4(), uuid4(), h.settings.public_learner_tenant_id)
    with Session() as database:
        handler = h.runtime.authenticated_delivery_handler_factory(database, actor)
        assert isinstance(handler.authorizer, DatabaseMediaDeliveryAuthorizer)
        assert handler.authorizer.database is database
        assert handler.authorizer.actor is actor
        assert handler.storage is h.storage
        assert handler.signer is h.runtime.media_delivery.signer
        assert handler.authorizer.signer is h.runtime.service.signer
        assert handler.signer is not handler.authorizer.signer
        with pytest.raises(MediaForbidden):
            h.runtime.authenticated_delivery_handler_factory(
                database, replace(actor, tenant_id=uuid4())
            )


@pytest.mark.asyncio
async def test_other_courses_keep_base_descriptor_without_borrowing_film_grants(composed):
    h = composed
    actor = ActorContext(uuid4(), uuid4(), h.settings.public_learner_tenant_id)
    activity = SimpleNamespace(
        id=h.rows[0].id, media_asset_id=h.clips[0].asset_id, media_version_id=h.clips[0].version_id
    )
    access = SimpleNamespace(
        activity=activity, tenant_id=actor.tenant_id, program_version_id=h.version.id
    )
    base = AsyncMock(return_value="inert descriptor")
    film = AsyncMock(return_value="authorized film descriptor")
    h.base.service.resolve_activity_media_descriptor_for_learner = base
    h.runtime.service.resolve_activity_media_descriptor_for_learner = film
    database = object()
    assert (
        await h.runtime.media_descriptor_resolver(database, actor, access)
        == "authorized film descriptor"
    )
    activity.media_asset_id = uuid4()
    assert await h.runtime.media_descriptor_resolver(database, actor, access) == "inert descriptor"
    assert film.await_count == base.await_count == 1
