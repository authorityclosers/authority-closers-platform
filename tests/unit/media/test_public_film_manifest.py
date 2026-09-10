"""Hermetic package verification; structural doubles are not codec/VPS proof."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from ac_platform.application import release_identity
from ac_platform.application.release_identity import ReleaseIdentityError
from ac_platform.media import public_film_manifest as public
from ac_platform.media import staging_fixture_manifest as staging
from ac_platform.media.errors import (
    MediaConfigurationError,
    MediaProcessingError,
    MediaStorageUnavailable,
)
from ac_platform.media.models import CaptionKind, MediaPurpose
from ac_platform.media.processing import CaptionPassthrough
from ac_platform.media.storage import UnconfiguredPrivateObjectStorage
from tests.unit.media.test_staging_fixture_import import artifact_factory as artifact_factory

RELEASE = "a" * 40
PUBLIC_TEMPLATE = json.loads(public.MANIFEST_PATH.read_bytes())


@pytest.fixture
def public_artifact_factory(artifact_factory, monkeypatch: pytest.MonkeyPatch):
    """Reuse old byte doubles; only tests can substitute either package manifest."""

    def make(*, mutate=None, mutate_manifest=None, tenant_id=None):
        old = artifact_factory(mutate=mutate, tenant_id=tenant_id)
        payload = json.loads(json.dumps(PUBLIC_TEMPLATE))
        payload["clips"] = old.payload["clips"]
        if mutate_manifest:
            mutate_manifest(payload)
        raw = json.dumps(payload).encode()
        path = old.root / "test-only-public-film-manifest.json"
        path.write_bytes(raw)
        digest = hashlib.sha256(raw).hexdigest()
        monkeypatch.setattr(public, "MANIFEST_PATH", path)
        monkeypatch.setattr(public, "MANIFEST_SHA256", digest)
        return SimpleNamespace(
            root=old.root,
            payload=payload,
            manifest=path,
            digest=digest,
            tenant_id=old.tenant_id,
            old=old,
        )

    return make


def load_public(artifact, **overrides):
    arguments = {
        "environment": "test",
        "release_id": RELEASE,
        "tenant_id": artifact.tenant_id,
        "root": artifact.root,
        "expected_manifest_sha256": artifact.digest,
    }
    arguments.update(overrides)
    return public.load_verified_public_film_pack(**arguments)


def process(pack, **overrides):
    clip = pack.clips[0]
    arguments = {
        "storage": pack.storage,
        "version_id": clip.version_id,
        "purpose": MediaPurpose.VIDEO,
        "source_key": clip.source_key,
        "content_type": "video/mp4",
        "crop": None,
    }
    arguments.update(overrides)
    return public.VerifiedPublicFilmProcessor(pack).process(**arguments)


def test_package_has_new_identity_and_exact_historical_bytes_and_attribution():
    raw = public.MANIFEST_PATH.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == public.MANIFEST_SHA256
    manifest = public.PublicFilmManifest.model_validate_json(raw)
    old_raw = staging.MANIFEST_PATH.read_bytes()
    old = json.loads(old_raw)
    assert hashlib.sha256(old_raw).hexdigest() == public.SOURCE_INVENTORY_SHA256
    assert old["production_enabled"] is False
    assert old["course_content"] is False
    assert old["clips"] == json.loads(raw)["clips"]
    assert sum(len(clip.objects) for clip in manifest.clips) == 30
    assert [clip.duration_seconds for clip in manifest.clips] == [12.032, 12.032]
    assert manifest.instructional_content is False
    assert manifest.full_films is False
    assert manifest.provider_activation is False
    assert [item.license for item in manifest.provenance] == [
        "Creative Commons Attribution 3.0",
        "Creative Commons Attribution 4.0",
    ]
    assert all("not film dialogue" in item.modifications for item in manifest.provenance)


@pytest.mark.parametrize("film_id", ["bbb-4k-30-normal", "caminandes-gran-dillama-1080p"])
def test_reserved_identity_recognizes_either_half_without_io(monkeypatch, film_id):
    tenant = uuid4()
    asset, version = public.public_film_media_identity(tenant, public.MANIFEST_SHA256, film_id)
    monkeypatch.setattr(public, "MANIFEST_PATH", None)
    assert public.is_public_film_media_identity(tenant, asset, version)
    assert public.is_public_film_media_identity(tenant, asset, uuid4())
    assert public.is_public_film_media_identity(tenant, uuid4(), version)
    assert not public.is_public_film_media_identity(uuid4(), asset, version)
    assert not public.is_public_film_media_identity(tenant, uuid4(), uuid4())
    old_asset, old_version = staging.fixture_media_identity(
        tenant, staging.MANIFEST_SHA256, film_id
    )
    assert not public.is_public_film_media_identity(tenant, old_asset, old_version)


@pytest.mark.parametrize("environment", ["local", "development", "preview", "Production", ""])
def test_environment_denied_before_file_access(monkeypatch, environment):
    monkeypatch.setattr(public, "MANIFEST_PATH", None)
    with pytest.raises(MediaConfigurationError, match="only named deployments"):
        public.load_verified_public_film_pack(
            environment=environment,
            release_id=RELEASE,
            tenant_id=uuid4(),
            root=Path("unopened"),
            expected_manifest_sha256=public.MANIFEST_SHA256,
        )


@pytest.mark.parametrize("release", [None, "a" * 39, "A" * 40, "b" * 41, "a" * 40 + "\n"])
def test_full_release_required_before_file_access(monkeypatch, release):
    monkeypatch.setattr(public, "MANIFEST_PATH", None)
    with pytest.raises(MediaConfigurationError, match="full release SHA"):
        public.require_public_film_scope("test", release)


@pytest.mark.parametrize("environment", ["staging", "production"])
@pytest.mark.parametrize("marker", [None, "b" * 40 + "\n", RELEASE, "invalid\n"])
def test_deployment_requires_real_matching_baked_release(
    public_artifact_factory, monkeypatch, environment, marker
):
    artifact = public_artifact_factory()
    path = artifact.root / "release-marker"
    if marker is not None:
        path.write_text(marker, encoding="ascii")
    monkeypatch.setattr(release_identity, "BAKED_RELEASE_ID_PATH", path)
    with pytest.raises(ReleaseIdentityError):
        load_public(artifact, environment=environment)


@pytest.mark.parametrize("environment", ["staging", "production"])
def test_deployment_scope_checks_baked_marker_again_on_processing(
    public_artifact_factory, monkeypatch, environment
):
    artifact = public_artifact_factory()
    path = artifact.root / "release-marker"
    path.write_text(RELEASE + "\n", encoding="ascii")
    monkeypatch.setattr(release_identity, "BAKED_RELEASE_ID_PATH", path)
    pack = load_public(artifact, environment=environment)
    assert process(pack).duration_seconds == 12.032
    path.write_text("b" * 40 + "\n", encoding="ascii")
    with pytest.raises(ReleaseIdentityError):
        process(pack)


def test_test_scope_does_not_read_deployed_marker(public_artifact_factory, monkeypatch):
    artifact = public_artifact_factory()
    monkeypatch.setattr(release_identity, "BAKED_RELEASE_ID_PATH", None)
    assert load_public(artifact).environment == "test"


@pytest.mark.parametrize("tenant_id", [UUID(int=0), "not-a-uuid", None])
def test_invalid_tenant_is_rejected(public_artifact_factory, tenant_id):
    artifact = public_artifact_factory()
    with pytest.raises(MediaConfigurationError, match="nonzero tenant"):
        load_public(artifact, tenant_id=tenant_id)


def test_caller_cannot_replace_package_digest_or_manifest_bytes(public_artifact_factory):
    artifact = public_artifact_factory()
    with pytest.raises(MediaConfigurationError, match="package-owned manifest hash"):
        load_public(artifact, expected_manifest_sha256="0" * 64)
    artifact.manifest.write_bytes(artifact.manifest.read_bytes() + b" ")
    with pytest.raises(MediaConfigurationError, match="manifest bytes do not match"):
        load_public(artifact)


@pytest.mark.parametrize(
    "change",
    [
        lambda value: value.update(schema_version="ac-alpha-staging-films.v1"),
        lambda value: value.update(provider_activation=True),
        lambda value: value.update(full_films=True),
        lambda value: value.update(instructional_content=True),
        lambda value: value.update(source_inventory_manifest_sha256="0" * 64),
        lambda value: value.update(fixture_registry_sha256="0" * 64),
        lambda value: value.update(clips=list(reversed(value["clips"]))),
        lambda value: value["provenance"][0].update(source_url="https://example.test/video.mp4"),
        lambda value: value["provenance"][0].update(license="CC0"),
        lambda value: value["provenance"][0].update(modifications="Complete instruction"),
        lambda value: value["clips"][0]["objects"][0].update(path="bbb-12s/../outside.mp4"),
    ],
)
def test_even_rehashed_test_manifests_must_obey_exact_schema(public_artifact_factory, change):
    artifact = public_artifact_factory(mutate_manifest=change)
    with pytest.raises(MediaConfigurationError, match="manifest is unavailable or invalid"):
        load_public(artifact)


def test_new_identity_is_tenant_pinned_and_separate_from_old_staging(public_artifact_factory):
    artifact = public_artifact_factory()
    pack = load_public(artifact)
    old_pack = staging.load_verified_staging_fixture_pack(
        environment="test",
        release_id=RELEASE,
        tenant_id=artifact.tenant_id,
        root=artifact.root,
        expected_manifest_sha256=artifact.old.digest,
    )
    for old_clip, new_clip in zip(old_pack.clips, pack.clips, strict=True):
        expected_old = staging.fixture_media_identity(
            artifact.tenant_id, artifact.old.digest, old_clip.spec.fixture_id
        )
        assert (old_clip.asset_id, old_clip.version_id) == expected_old
        assert all(
            key.startswith(old_clip.source_key + "/renditions/")
            for key in old_clip.processing_result.object_keys
        )
        assert (new_clip.asset_id, new_clip.version_id) != expected_old
        assert (new_clip.asset_id, new_clip.version_id) != staging.fixture_media_identity(
            artifact.tenant_id, artifact.digest, new_clip.spec.fixture_id
        )
        assert (new_clip.asset_id, new_clip.version_id) != public.public_film_media_identity(
            uuid4(), artifact.digest, new_clip.spec.fixture_id
        )
    result = process(pack)
    assert [item.protocol for item in result.renditions] == ["progressive", "hls"]
    assert result.width == 3840 and result.height == 2160
    assert result.duration_seconds == 12.032
    assert result.captions[0].language == "en"
    assert all(
        key.startswith(pack.clips[0].source_key + "/renditions/") for key in result.object_keys
    )
    assert not any(key.endswith("probe.json") for key in result.object_keys)
    with pytest.raises(MediaConfigurationError, match="only staging"):
        staging.require_staging_scope("production", RELEASE)


@pytest.mark.parametrize(
    "kind",
    ["seal", "tenant", "release", "digest", "clips", "clip-seal", "clip-id", "source", "storage"],
)
def test_forged_or_mismatched_pack_scope_is_rejected(public_artifact_factory, kind):
    pack = load_public(public_artifact_factory())
    changes = {
        "seal": {"_seal": object()},
        "tenant": {"tenant_id": uuid4()},
        "release": {"release_id": "b" * 40},
        "digest": {"manifest_sha256": "0" * 64},
        "clips": {"clips": ()},
        "clip-seal": {"clips": (replace(pack.clips[0], _seal=object()), pack.clips[1])},
        "clip-id": {"clips": (replace(pack.clips[0], asset_id=uuid4()), pack.clips[1])},
        "source": {"clips": (replace(pack.clips[0], source_key="other"), pack.clips[1])},
        "storage": {"storage": UnconfiguredPrivateObjectStorage()},
    }
    altered = replace(pack, **changes[kind])
    with pytest.raises(MediaConfigurationError):
        altered.require_scope(environment="test", release_id=RELEASE, tenant_id=pack.tenant_id)


@pytest.mark.parametrize(
    "overrides",
    [
        {"storage": UnconfiguredPrivateObjectStorage()},
        {"version_id": UUID(int=1)},
        {"purpose": MediaPurpose.AVATAR},
        {"source_key": "unapproved"},
        {"content_type": "video/webm"},
        {"crop": {}},
        {"captions": (CaptionPassthrough("en", CaptionKind.CAPTIONS, "text/vtt", "other"),)},
    ],
)
def test_processor_does_not_accept_arbitrary_sources_or_purposes(
    public_artifact_factory, overrides
):
    pack = load_public(public_artifact_factory())
    with pytest.raises(MediaConfigurationError):
        process(pack, **overrides)


def test_changed_file_after_verification_is_denied(public_artifact_factory):
    artifact = public_artifact_factory()
    pack = load_public(artifact)
    path = artifact.root / pack.clips[0].spec.progressive_path
    path.write_bytes(b"changed")
    with pytest.raises(MediaStorageUnavailable):
        process(pack)


@pytest.mark.parametrize(
    "fault",
    [
        "codec",
        "dimensions",
        "duration",
        "audio",
        "external-hls",
        "long-timeline",
        "orphan-hls",
        "mp4",
    ],
)
def test_shared_byte_probe_and_complete_hls_graph_validation(public_artifact_factory, fault):
    def mutate(_clip, files):
        if fault in {"codec", "dimensions", "duration", "audio"}:
            probe = json.loads(files["probe.json"])
            if fault == "codec":
                probe["streams"][0]["codec_name"] = "hevc"
            elif fault == "dimensions":
                probe["streams"][0]["width"] = 1
            elif fault == "duration":
                probe["format"]["duration"] = "20"
            else:
                probe["streams"][1]["codec_name"] = "opus"
            files["probe.json"] = json.dumps(probe).encode()
        elif fault == "external-hls":
            files["hls/master.m3u8"] = files["hls/master.m3u8"].replace(
                b"360p/index.m3u8", b"https://example.test/foreign.m3u8"
            )
        elif fault == "long-timeline":
            files["hls/360p/index.m3u8"] = files["hls/360p/index.m3u8"].replace(
                b"#EXTINF:4,", b"#EXTINF:3,"
            )
        elif fault == "orphan-hls":
            files["hls/360p/orphan.ts"] = b"unreferenced"
        else:
            files["progressive.mp4"] = b"not-an-mp4"

    artifact = public_artifact_factory(mutate=mutate)
    with pytest.raises((MediaConfigurationError, MediaProcessingError)):
        load_public(artifact)
