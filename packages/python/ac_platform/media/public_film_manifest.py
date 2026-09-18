"""Separate immutable package for two licensed 12-second technical demonstrations.

This package may be composed on staging/production only for its exact baked
release and tenant. It does not turn the old staging manifest into production
authority, accept source URLs, activate providers, or authorize learner access.
All media/probe/HLS verification is shared with the existing pinned validator.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal
from uuid import UUID, uuid5

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from ac_platform.application.release_identity import require_baked_release_id
from ac_platform.media.errors import MediaConfigurationError
from ac_platform.media.file_storage import FileMediaObject, ReadOnlyFileMediaStorage
from ac_platform.media.models import MediaPurpose
from ac_platform.media.processing import CaptionPassthrough, ProcessingResult
from ac_platform.media.staging_fixture_manifest import FixtureClip, _verify_clip
from ac_platform.media.storage import PrivateObjectStorage

MANIFEST_PATH = Path(__file__).parent / "data" / "public_films_technical_demo_12s_v1.json"
MANIFEST_SHA256 = "dc8f635df33432aee83c461535823881286ded1577a8f8a72dc5b10f0ad86b42"
PUBLIC_FILM_MANIFEST_ID = "public-films-technical-demo-12s-v1"
REGISTRY_SHA256 = "fc61c87d5428d53d35b82061a53fbdbd9967b8bf658c6d0425a78a07bc106290"
SOURCE_INVENTORY_SHA256 = "d693acc73dc3f66c1b13ad6e68d5e41cba8478dc719f4b68211ce829442b0222"
# The full source bytes and checksum were verified before being admitted by
# the ordinary Studio upload lifecycle. This lookup is deliberately exact;
# it does not inspect filenames, URLs, or client metadata.
BBB_SOURCE_SHA256 = "37f0ff251a606c2dcfa26c19fe6bf843234b4e7a8889cfab50bc26f644e55520"
BBB_SOURCE_BYTES = 633_016_449
_NAMESPACE = UUID("01883ebc-4166-42d5-9a70-6c5178c27bc9")
_SEAL = object()
_MAX_MANIFEST_BYTES = 2 * 1024**2
_MAX_PACK_BYTES = 512 * 1024**2
FilmId = Literal["bbb-4k-30-normal", "caminandes-gran-dillama-1080p"]
_FILM_IDS = ("bbb-4k-30-normal", "caminandes-gran-dillama-1080p")
_MODIFICATIONS = (
    "12-second technical excerpt; H.264/AAC re-encoding, adaptive HLS renditions, "
    "and synthetic English test captions, not film dialogue."
)
# Exact attribution retained from the historical, digest-pinned source registry.
# These URLs are provenance data; no loader performs network acquisition.
_PROVENANCE = {
    "bbb-4k-30-normal": (
        "Big Buck Bunny — Sunflower",
        "https://download.blender.org/demo/movies/BBB/bbb_sunflower_2160p_30fps_normal.mp4.zip",
        "https://peach.blender.org/about/",
        "Creative Commons Attribution 3.0",
        "https://creativecommons.org/licenses/by/3.0/",
        "Blender Foundation 2008, Janus Bager Kristensen 2013; Big Buck Bunny, Sunflower version",
    ),
    "caminandes-gran-dillama-1080p": (
        "Caminandes 2: Gran Dillama",
        "https://download.blender.org/demo/movies/caminandes_gran_dillama.mp4.zip",
        "https://studio.blender.org/projects/api/assets/2363/",
        "Creative Commons Attribution 4.0",
        "https://creativecommons.org/licenses/by/4.0/",
        "Blender Foundation / Blender Studio; Caminandes 2: Gran Dillama (2013), "
        "directed by Pablo Vazquez; studio.blender.org",
    ),
}


def technical_playback_provenance_for_checksum(
    checksum_sha256: str | None,
) -> PublicFilmProvenance | None:
    """Return the reviewed BBB record for one exact admitted source digest.

    The media service calls this only with a persisted, server-measured
    ``MediaVersion.checksum_sha256``. Unknown or malformed values never
    receive a provenance claim.
    """

    if not isinstance(checksum_sha256, str) or checksum_sha256.lower() != BBB_SOURCE_SHA256:
        return None
    title, source_url, source_page, license_name, license_url, attribution = _PROVENANCE[
        "bbb-4k-30-normal"
    ]
    return PublicFilmProvenance(
        fixture_id="bbb-4k-30-normal",
        title=title,
        source_url=source_url,
        source_page=source_page,
        license=license_name,
        license_url=license_url,
        attribution=attribution,
        modifications=_MODIFICATIONS,
    )


def _deny(message: str) -> MediaConfigurationError:
    return MediaConfigurationError(f"Public-film demonstration package refused: {message}")


def require_public_film_scope(environment: str, release_id: str) -> None:
    """Validate the deployment before opening media/manifest files or databases."""
    if environment not in {"staging", "production", "test"}:
        raise _deny("only named deployments or isolated test may use this package")
    if not isinstance(release_id, str) or re.fullmatch(r"[0-9a-f]{40}", release_id) is None:
        raise _deny("a full release SHA is required")
    if environment in {"staging", "production"}:
        require_baked_release_id(release_id)


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class PublicFilmProvenance(_Strict):
    fixture_id: FilmId
    title: str = Field(min_length=1, max_length=200)
    source_url: str = Field(min_length=1, max_length=300)
    source_page: str = Field(min_length=1, max_length=300)
    license: str = Field(min_length=1, max_length=100)
    license_url: str = Field(min_length=1, max_length=200)
    attribution: str = Field(min_length=1, max_length=500)
    modifications: str = Field(min_length=1, max_length=300)

    @model_validator(mode="after")
    def exact_provenance(self) -> PublicFilmProvenance:
        if (
            self.title,
            self.source_url,
            self.source_page,
            self.license,
            self.license_url,
            self.attribution,
        ) != _PROVENANCE[self.fixture_id] or self.modifications != _MODIFICATIONS:
            raise ValueError("the exact licensed source attribution and modifications are required")
        return self


class PublicFilmManifest(_Strict):
    schema_version: Literal["ac-public-film-demonstration-pack.v1"]
    manifest_id: Literal["public-films-technical-demo-12s-v1"]
    purpose: Literal["technical-playback-demonstration"]
    allowed_deployment_environments: tuple[Literal["staging"], Literal["production"]]
    instructional_content: Literal[False]
    full_films: Literal[False]
    provider_activation: Literal[False]
    source_inventory_manifest_sha256: str
    fixture_registry_sha256: str
    provenance: tuple[PublicFilmProvenance, PublicFilmProvenance]
    clips: tuple[FixtureClip, FixtureClip]

    @model_validator(mode="after")
    def exact_package(self) -> PublicFilmManifest:
        if (
            self.source_inventory_manifest_sha256 != SOURCE_INVENTORY_SHA256
            or self.fixture_registry_sha256 != REGISTRY_SHA256
            or tuple(clip.fixture_id for clip in self.clips) != _FILM_IDS
            or tuple(item.fixture_id for item in self.provenance) != _FILM_IDS
            or sum(item.content_length for clip in self.clips for item in clip.objects)
            > _MAX_PACK_BYTES
        ):
            raise ValueError("the bounded ordered two-film source inventory is required")
        return self


def public_film_media_identity(tenant_id: UUID, digest: str, fixture_id: str) -> tuple[UUID, UUID]:
    if (
        not isinstance(tenant_id, UUID)
        or tenant_id.int == 0
        or digest != MANIFEST_SHA256
        or fixture_id not in _FILM_IDS
    ):
        raise _deny("the exact manifest, film and nonzero tenant identity are required")
    scope = f"{tenant_id}:{digest}:{fixture_id}"
    return uuid5(_NAMESPACE, "asset:" + scope), uuid5(_NAMESPACE, "version:" + scope)


def is_public_film_media_identity(tenant_id: UUID, asset_id: UUID, version_id: UUID) -> bool:
    """Recognize either reserved identity without reading or activating media.

    Test films belong only to their sealed demonstration catalog. Checking
    each identity separately also prevents a caller from mixing a reserved
    asset with another version (or the reverse).
    """
    return any(
        asset_id == reserved_asset or version_id == reserved_version
        for reserved_asset, reserved_version in (
            public_film_media_identity(tenant_id, MANIFEST_SHA256, film_id) for film_id in _FILM_IDS
        )
    )


def _source_key(tenant_id: UUID, asset_id: UUID, version_id: UUID) -> str:
    return f"tenants/{tenant_id}/media/video/{asset_id}/{version_id}/original"


@dataclass(frozen=True, slots=True)
class VerifiedPublicFilmClip:
    spec: FixtureClip
    provenance: PublicFilmProvenance
    asset_id: UUID
    version_id: UUID
    source_key: str
    processing_result: ProcessingResult
    _seal: object = field(repr=False, compare=False)


@dataclass(frozen=True, slots=True)
class VerifiedPublicFilmPack:
    environment: str
    release_id: str
    tenant_id: UUID
    manifest_sha256: str
    storage: ReadOnlyFileMediaStorage
    clips: tuple[VerifiedPublicFilmClip, ...]
    _seal: object = field(repr=False, compare=False)

    def require_scope(self, *, environment: str, release_id: str, tenant_id: UUID) -> None:
        require_public_film_scope(environment, release_id)
        if (
            self._seal is not _SEAL
            or (environment, release_id, tenant_id)
            != (self.environment, self.release_id, self.tenant_id)
            or self.manifest_sha256 != MANIFEST_SHA256
            or not isinstance(self.storage, ReadOnlyFileMediaStorage)
            or tuple(clip.spec.fixture_id for clip in self.clips) != _FILM_IDS
        ):
            raise _deny("the verified package scope is invalid")
        for clip in self.clips:
            asset_id, version_id = public_film_media_identity(
                tenant_id, MANIFEST_SHA256, clip.spec.fixture_id
            )
            if (
                clip._seal is not _SEAL
                or clip.provenance.fixture_id != clip.spec.fixture_id
                or (clip.asset_id, clip.version_id) != (asset_id, version_id)
                or clip.source_key != _source_key(tenant_id, asset_id, version_id)
            ):
                raise _deny("the verified film identity is invalid")


def load_verified_public_film_pack(
    *,
    environment: str,
    release_id: str,
    tenant_id: UUID,
    root: Path,
    expected_manifest_sha256: str,
) -> VerifiedPublicFilmPack:
    require_public_film_scope(environment, release_id)
    if not isinstance(tenant_id, UUID) or tenant_id.int == 0:
        raise _deny("a nonzero tenant identity is required")
    if expected_manifest_sha256 != MANIFEST_SHA256:
        raise _deny("the package-owned manifest hash is required")
    try:
        with MANIFEST_PATH.open("rb") as source:
            raw = source.read(_MAX_MANIFEST_BYTES + 1)
        if len(raw) > _MAX_MANIFEST_BYTES or hashlib.sha256(raw).hexdigest() != MANIFEST_SHA256:
            raise _deny("the package-owned manifest bytes do not match")
        manifest = PublicFilmManifest.model_validate_json(raw)
    except (OSError, ValidationError) as error:
        raise _deny("the package-owned manifest is unavailable or invalid") from error
    inventory: list[FileMediaObject] = []
    for clip in manifest.clips:
        asset_id, version_id = public_film_media_identity(
            tenant_id, MANIFEST_SHA256, clip.fixture_id
        )
        source_key = _source_key(tenant_id, asset_id, version_id)
        for item in clip.objects:
            inventory.append(
                FileMediaObject(
                    f"{source_key}/renditions/{item.path.split('/', 1)[1]}",
                    item.path,
                    item.content_type,
                    item.content_length,
                    item.sha256,
                    item.sha256,
                )
            )
        progressive = next(item for item in clip.objects if item.path == clip.progressive_path)
        inventory.append(
            FileMediaObject(
                source_key,
                progressive.path,
                progressive.content_type,
                progressive.content_length,
                progressive.sha256,
                progressive.sha256,
            )
        )
    storage = ReadOnlyFileMediaStorage(root=root, inventory=inventory)
    clips = []
    for clip, provenance in zip(manifest.clips, manifest.provenance, strict=True):
        verified = _verify_clip(
            storage, tenant_id, MANIFEST_SHA256, clip, identity_factory=public_film_media_identity
        )
        clips.append(
            VerifiedPublicFilmClip(
                clip,
                provenance,
                verified.asset_id,
                verified.version_id,
                verified.source_key,
                verified.processing_result,
                _SEAL,
            )
        )
    return VerifiedPublicFilmPack(
        environment, release_id, tenant_id, MANIFEST_SHA256, storage, tuple(clips), _SEAL
    )


class VerifiedPublicFilmProcessor:
    """Return only independently reverified, preprocessed package renditions."""

    def __init__(self, pack: VerifiedPublicFilmPack) -> None:
        if not isinstance(pack, VerifiedPublicFilmPack):
            raise _deny("a verified public-film package is required")
        pack.require_scope(
            environment=pack.environment, release_id=pack.release_id, tenant_id=pack.tenant_id
        )
        self.pack = pack

    def process(
        self,
        *,
        storage: PrivateObjectStorage,
        version_id: UUID,
        purpose: MediaPurpose,
        source_key: str,
        content_type: str,
        crop: dict[str, object] | None,
        captions: Iterable[CaptionPassthrough] = (),
    ) -> ProcessingResult:
        self.pack.require_scope(
            environment=self.pack.environment,
            release_id=self.pack.release_id,
            tenant_id=self.pack.tenant_id,
        )
        if (
            storage is not self.pack.storage
            or purpose is not MediaPurpose.VIDEO
            or crop is not None
            or next(iter(captions), None) is not None
        ):
            raise _deny("the processor is outside its exact read-only video scope")
        clip = next((item for item in self.pack.clips if item.version_id == version_id), None)
        if clip is None or source_key != clip.source_key or content_type != "video/mp4":
            raise _deny("the processor received an unapproved source")
        return _verify_clip(
            self.pack.storage,
            self.pack.tenant_id,
            self.pack.manifest_sha256,
            clip.spec,
            identity_factory=public_film_media_identity,
        ).processing_result


__all__ = [
    "MANIFEST_PATH",
    "MANIFEST_SHA256",
    "PUBLIC_FILM_MANIFEST_ID",
    "REGISTRY_SHA256",
    "SOURCE_INVENTORY_SHA256",
    "BBB_SOURCE_BYTES",
    "BBB_SOURCE_SHA256",
    "PublicFilmManifest",
    "PublicFilmProvenance",
    "VerifiedPublicFilmClip",
    "VerifiedPublicFilmPack",
    "VerifiedPublicFilmProcessor",
    "is_public_film_media_identity",
    "load_verified_public_film_pack",
    "public_film_media_identity",
    "require_public_film_scope",
    "technical_playback_provenance_for_checksum",
]
