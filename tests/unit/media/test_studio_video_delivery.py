"""Composition/routing tests; persisted access is exercised by the PG journey."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import UUID

import pytest
from sqlalchemy.exc import MultipleResultsFound
from sqlalchemy.ext.asyncio import async_sessionmaker

from ac_platform.application.settings import Settings
from ac_platform.kernel.authz import ActorContext
from ac_platform.media.api_contracts import ActivityMediaDescriptorResponse
from ac_platform.media.clamav_scanner import ClamAVScannerConfig
from ac_platform.media.contracts import (
    MediaAssetId,
    MediaAssetVersion,
    MediaVersionId,
    create_media_authorization_context,
)
from ac_platform.media.delivery import PrivateMediaDeliveryHandler
from ac_platform.media.errors import MediaConfigurationError, MediaForbidden
from ac_platform.media.policy import MediaCorsPolicy, RangeMode, SignedMediaDeliveryPort
from ac_platform.media.runtime import create_media_runtime
from ac_platform.media.scanner import SignatureContentScanner
from ac_platform.media.signing import MediaSigner
from ac_platform.media.storage import InMemoryPrivateObjectStorage
from ac_platform.media.studio_video_delivery import (
    _matches_upload_program,
    _owns_key,
    _upload_program,
    compose_local_studio_video_delivery,
)
from ac_platform.media.studio_video_runtime import compose_local_studio_video_runtime

TENANT = UUID("974dfb42-f52c-49b8-bb07-34eec759468e")
ASSET = UUID("63c2fbee-9c13-4005-af4a-075a738da57b")
VERSION = UUID("f6d7132f-0766-4689-91a8-c3d98a816fcc")
PROGRAM = UUID("0708fb30-85a6-4518-8ad7-b0a8d42d1c27")
ACTOR = ActorContext(UUID(int=5), UUID(int=6), TENANT)
ROOT = f"tenants/{TENANT}/media/video/{ASSET}/{VERSION}/original"
ORIGIN = "http://learner.localhost:3100"
PLAYBACK, READ, CORRUPT = "playback", "read", "corrupt"


def _settings(**overrides):
    return Settings(
        environment="test",
        public_app_url=ORIGIN,
        media_max_upload_bytes=1024**2,
        media_max_processing_output_bytes=8 * 1024**2,
        **overrides,
    )


def _runtime(tmp_path, settings=None, **base_overrides):
    settings = settings or _settings()
    base = replace(create_media_runtime(settings), **base_overrides)
    uploaded = compose_local_studio_video_runtime(
        settings,
        base,
        sessions=async_sessionmaker(),
        root=tmp_path / "video-objects",
        max_store_bytes=4 * 1024**2,
        scanner_config=ClamAVScannerConfig(host="127.0.0.1", max_content_bytes=512 * 1024),
        testing_scanner=SignatureContentScanner(),
    )
    return settings, uploaded


def test_composition_preserves_existing_services_policy_and_avatar(tmp_path):
    avatar, policy = object(), Mock()
    settings, base = _runtime(
        tmp_path, local_avatar_runtime=avatar, playback_policy_resolver=policy
    )
    composed = compose_local_studio_video_delivery(settings, base)
    assert composed.service is base.service
    assert composed.local_avatar_runtime is avatar
    assert composed.playback_policy_resolver is policy
    assert composed.studio_video_runtime is base.studio_video_runtime
    assert composed.media_delivery.delivery_origin == ORIGIN
    assert composed.media_delivery.playback_ttl == base.studio_video_runtime.service.playback_ttl
    assert composed.media_cors_policy.allowed_origins == (ORIGIN,)
    assert (
        composed.authenticated_delivery_handler_factory.service.storage
        is base.studio_video_runtime.storage
    )
    assert not composed.provider_activation_verified


@pytest.mark.parametrize("enabled", [True, False])
def test_delivery_respects_configured_range_policy(tmp_path, enabled):
    settings, base = _runtime(tmp_path, _settings(media_allow_range_requests=enabled))
    composed = compose_local_studio_video_delivery(settings, base)
    policy = composed.authenticated_delivery_handler_factory.port.range_policy
    assert policy.mode == (RangeMode.SINGLE if enabled else RangeMode.DENY)
    assert policy.max_bytes == base.studio_video_runtime.storage.max_object_bytes


def test_missing_mismatched_or_duplicate_graph_is_rejected(tmp_path):
    settings, uploaded = _runtime(tmp_path)
    with pytest.raises(MediaConfigurationError, match="exact local/test"):
        compose_local_studio_video_delivery(settings, create_media_runtime(settings))
    with pytest.raises(MediaConfigurationError, match="exact local/test"):
        compose_local_studio_video_delivery(_settings(), uploaded)
    with pytest.raises(MediaConfigurationError, match="exact local/test"):
        compose_local_studio_video_delivery(settings, replace(uploaded, environment="staging"))
    composed = compose_local_studio_video_delivery(settings, uploaded)
    with pytest.raises(MediaConfigurationError, match="exact local/test"):
        compose_local_studio_video_delivery(settings, composed)


@pytest.mark.parametrize("environment", ["development", "staging", "production"])
def test_delivery_cannot_activate_nonlocal_environment(tmp_path, environment):
    settings, uploaded = _runtime(tmp_path)
    changed = settings.model_copy(update={"environment": environment})
    with pytest.raises(MediaConfigurationError, match="exact local/test"):
        compose_local_studio_video_delivery(changed, replace(uploaded, environment=environment))


def test_enabled_provider_is_rejected_before_composition(tmp_path):
    settings, uploaded = _runtime(tmp_path)
    settings.media_provider_enabled = True
    with pytest.raises(MediaConfigurationError, match="exact local/test"):
        compose_local_studio_video_delivery(settings, uploaded)


@pytest.mark.parametrize("url", ["http://remote.test", ORIGIN + "/nested", ORIGIN + "?scope=x"])
def test_unsafe_learner_origin_is_rejected(tmp_path, url):
    settings, uploaded = _runtime(tmp_path)
    # Isolate the delivery check even if Settings later adds earlier validation.
    object.__setattr__(settings, "public_app_url", url)
    with pytest.raises(MediaConfigurationError, match="exact learner origin"):
        compose_local_studio_video_delivery(settings, uploaded)


def test_prior_delivery_origin_and_cors_cannot_be_widened(tmp_path):
    settings, uploaded = _runtime(tmp_path)
    signer = MediaSigner("test-only-prior-delivery-signer-32-bytes")
    foreign_port = SignedMediaDeliveryPort(signer=signer, delivery_origin="https://other.test")
    with pytest.raises(MediaConfigurationError, match="exact learner origin"):
        compose_local_studio_video_delivery(
            settings, replace(uploaded, media_delivery=foreign_port)
        )
    with pytest.raises(MediaConfigurationError, match="exact learner origin"):
        compose_local_studio_video_delivery(
            settings,
            replace(uploaded, media_cors_policy=MediaCorsPolicy((ORIGIN, "https://other.test"))),
        )


@pytest.mark.parametrize(
    "key",
    [
        ROOT,
        ROOT + "/attempts/64a14d8c-32ec-4a2b-989f-f3ed9ea9eb03/renditions/master.m3u8",
        ROOT + "/renditions/progressive.mp4",
    ],
)
def test_route_uses_immutable_upload_provenance_not_readiness(key):
    database = Mock()
    database.execute.return_value.scalar_one_or_none.return_value = PROGRAM
    assert _owns_key(database, ACTOR, key)
    query = str(database.execute.call_args.args[0])
    assert "studio_video_uploads" in query
    assert "media_upload_intents.asset_id" in query
    assert "media_upload_intents.version_id" in query
    assert "state" not in query
    database.execute.return_value.scalar_one_or_none.return_value = None
    assert not _owns_key(database, ACTOR, key)


@pytest.mark.parametrize(
    "key",
    [
        ROOT.replace(str(TENANT), str(UUID(int=100))),
        ROOT.replace(str(ASSET), str(ASSET).upper()),
        ROOT.replace("/video/", "/avatar/"),
        ROOT.replace("/original", "/renditions/master.m3u8"),
        "not-an-object",
    ],
)
def test_unowned_keys_do_not_query_upload_provenance(key):
    database = Mock()
    assert not _owns_key(database, ACTOR, key)
    database.execute.assert_not_called()


def test_binding_must_belong_to_the_uploaded_course():
    binding = SimpleNamespace(
        tenant_id=TENANT,
        program_scope="tenant",
        program_owner_key=TENANT,
        program_id=PROGRAM,
        asset_id=ASSET,
        version_id=VERSION,
    )
    assert _matches_upload_program(binding, TENANT, PROGRAM)
    binding.program_id = UUID(int=91)
    assert not _matches_upload_program(binding, TENANT, PROGRAM)
    binding.program_id, binding.program_scope = PROGRAM, "platform"
    assert not _matches_upload_program(binding, TENANT, PROGRAM)


def test_bad_studio_token_does_not_read_storage_or_fallback(tmp_path, monkeypatch):
    previous = Mock()
    settings, base = _runtime(tmp_path, authenticated_delivery_handler_factory=previous)
    composed = compose_local_studio_video_delivery(settings, base)
    database = Mock()
    database.execute.return_value.scalar_one_or_none.return_value = PROGRAM
    storage_head = Mock(side_effect=AssertionError("unauthorized storage read"))
    monkeypatch.setattr(base.studio_video_runtime.storage, "head", storage_head)
    handler = composed.authenticated_delivery_handler_factory(database, ACTOR)
    with pytest.raises(MediaForbidden):
        handler.serve(token=CORRUPT, token_type=PLAYBACK, object_key=ROOT)
    previous.assert_not_called()
    storage_head.assert_not_called()


@pytest.mark.parametrize("value", [str(PROGRAM), UUID(int=0), 42])
def test_malformed_provenance_never_looks_like_nonstudio_media(value):
    database = Mock()
    database.execute.return_value.scalar_one_or_none.return_value = value
    with pytest.raises(MediaForbidden, match="provenance"):
        _upload_program(database, TENANT, ASSET, VERSION)


def test_ambiguous_provenance_is_terminal():
    database = Mock()
    database.execute.return_value.scalar_one_or_none.side_effect = MultipleResultsFound()
    with pytest.raises(MediaForbidden, match="ambiguous"):
        _upload_program(database, TENANT, ASSET, VERSION)


@pytest.mark.asyncio
async def test_known_studio_video_in_other_course_never_uses_prior_descriptor(tmp_path):
    previous = AsyncMock()
    settings, base = _runtime(tmp_path, media_descriptor_resolver=previous)
    composed = compose_local_studio_video_delivery(settings, base)
    access = SimpleNamespace(
        activity=SimpleNamespace(
            media_asset_id=ASSET,
            media_version_id=VERSION,
            program_id=UUID(int=99),
            program_scope="tenant",
            program_owner_key=TENANT,
        )
    )
    database = AsyncMock()
    database.run_sync.return_value = PROGRAM
    result = await composed.media_descriptor_resolver(database, ACTOR, access)
    assert result.state == "unavailable"
    previous.assert_not_awaited()


def test_known_studio_binding_in_other_course_never_uses_prior_resolver(tmp_path, monkeypatch):
    previous = Mock()
    settings, base = _runtime(tmp_path, activity_media_resolver=previous)
    composed = compose_local_studio_video_delivery(settings, base)
    binding = SimpleNamespace(
        tenant_id=TENANT,
        asset_id=ASSET,
        version_id=VERSION,
        program_id=UUID(int=99),
        program_scope="tenant",
        program_owner_key=TENANT,
    )
    monkeypatch.setattr(
        "ac_platform.media.studio_video_delivery.resolve_activity_media_binding_for_learning",
        Mock(return_value=binding),
    )
    database = Mock()
    database.execute.return_value.scalar_one_or_none.return_value = PROGRAM
    assert composed.activity_media_resolver(database, TENANT, object(), object()) is None
    previous.assert_not_called()


def test_unowned_private_media_keeps_its_real_handler_and_policy(tmp_path):
    signer = MediaSigner("test-only-existing-avatar-signer-32-bytes")
    storage = InMemoryPrivateObjectStorage(signer)
    port = SignedMediaDeliveryPort(signer=signer, delivery_origin=ORIGIN, allow_loopback_http=True)
    cors = MediaCorsPolicy((ORIGIN,))
    old = PrivateMediaDeliveryHandler(
        storage=storage,
        signer=signer,
        delivery_port=port,
        cors_policy=cors,
        authorizer=lambda _claims, kind: kind == "read",
    )
    previous = Mock(return_value=old)
    settings, base = _runtime(
        tmp_path,
        media_delivery=port,
        media_cors_policy=cors,
        authenticated_delivery_handler_factory=previous,
    )
    composed = compose_local_studio_video_delivery(settings, base)
    assert composed.media_delivery is port and composed.media_cors_policy is cors
    key = f"tenants/{TENANT}/media/avatar/{ASSET}/{VERSION}/original"
    storage.put(object_key=key, body=b"private-avatar-fixture", content_type="image/png")
    now = datetime.now(UTC)
    signed = port.issue(
        authorization=create_media_authorization_context(
            tenant_id=str(TENANT),
            person_id=str(ACTOR.person_id),
            session_id=str(ACTOR.session_id),
        ),
        activity_id="avatar",
        activity_version="v1",
        media_version=MediaAssetVersion(MediaAssetId(str(ASSET)), MediaVersionId(str(VERSION))),
        object_key=key,
        now=now,
        kind="read",
        supports_range=False,
    )
    database = Mock()
    handler = composed.authenticated_delivery_handler_factory(database, ACTOR)
    response = handler.serve(token=signed.token, token_type=READ, object_key=key, now=now)
    assert b"".join(response.body) == b"private-avatar-fixture"
    previous.assert_called_once_with(database, ACTOR)
    database.scalar.assert_not_called()
    # Existing handler denial propagates; Studio must not retry it.
    with pytest.raises(MediaForbidden):
        handler.serve(token=CORRUPT, token_type=READ, object_key=key, now=now)
    assert previous.call_count == 2


@pytest.mark.asyncio
async def test_existing_descriptor_is_preserved_and_unavailable_stays_unavailable(tmp_path):
    response = ActivityMediaDescriptorResponse(state="unavailable", reason="test_film_not_ready")
    previous = AsyncMock(return_value=response)
    settings, base = _runtime(tmp_path, media_descriptor_resolver=previous)
    composed = compose_local_studio_video_delivery(settings, base)
    access = SimpleNamespace(activity=SimpleNamespace(media_asset_id=None, media_version_id=None))
    database = AsyncMock()
    assert await composed.media_descriptor_resolver(database, ACTOR, access) is response
    previous.assert_awaited_once_with(database, ACTOR, access)
    database.run_sync.assert_not_called()
    without_prior = compose_local_studio_video_delivery(
        settings, replace(base, media_descriptor_resolver=None)
    )
    assert (
        await without_prior.media_descriptor_resolver(database, ACTOR, access)
    ).state == "unavailable"
    with pytest.raises(MediaForbidden, match="tenant"):
        await composed.media_descriptor_resolver(database, replace(ACTOR, tenant_id=None), access)
