"""Sealed full-film checks; the large local-pack case is an actual codec probe."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from ac_platform.media import full_film_manifest as full
from ac_platform.media.errors import MediaConfigurationError
from ac_platform.media.processing import ProcessingResult

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
PACK_ROOT = (
    REPOSITORY_ROOT
    / "tools"
    / "media-player-stress"
    / ".artifacts"
    / "full-film"
    / "bbb-4k-30-normal"
)
TENANT_ID = UUID("11111111-1111-1111-1111-111111111111")


def _payload() -> dict[str, object]:
    return json.loads(full.MANIFEST_PATH.read_bytes())


def test_package_manifest_bytes_and_complete_inventory_are_exact() -> None:
    raw = full.MANIFEST_PATH.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == full.MANIFEST_SHA256
    manifest = full.FullFilmManifest.model_validate_json(raw)
    assert manifest.source.sha256 == (
        "37f0ff251a606c2dcfa26c19fe6bf843234b4e7a8889cfab50bc26f644e55520"
    )
    assert (manifest.source.width, manifest.source.height) == (3840, 2160)
    assert manifest.source.duration_seconds == 634.6
    assert manifest.progressive.video_mode == "copy"
    assert manifest.progressive.video_packet_count == manifest.source.video_packet_count
    assert [(item.id, item.width, item.height) for item in manifest.hls.renditions] == [
        ("2160p", 3840, 2160),
        ("720p", 1280, 720),
    ]
    assert all(
        item.video_packet_count == manifest.source.video_packet_count
        for item in manifest.hls.renditions
    )
    assert len(manifest.files) == 278
    assert sum(item.bytes for item in manifest.files) == 1_462_691_945
    assert not any(item.path.endswith((".vtt", ".srt", ".ttml")) for item in manifest.files)


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (
            lambda value: value["source"].update({"sha256": "0" * 64}),
            "native-4K source",
        ),
        (
            lambda value: value["progressive"].update({"video_mode": "transcode"}),
            "literal_error",
        ),
        (
            lambda value: value["hls"]["renditions"][0].update({"width": 7680}),
            "ordered complete HLS rendition",
        ),
        (
            lambda value: value["files"][0].update({"path": "../escaped.ts"}),
            "path or MIME",
        ),
        (
            lambda value: value["files"][0].update({"bytes": value["files"][0]["bytes"] + 1}),
            "bounded full-film inventory",
        ),
        (
            lambda value: value["commands"]["hls_2160p"].append("https://example.test"),
            "bounded full-film inventory",
        ),
        (
            lambda value: value.update({"captions": []}),
            "extra_forbidden",
        ),
    ],
)
def test_manifest_mutations_fail_closed(mutate, message: str) -> None:
    payload = deepcopy(_payload())
    mutate(payload)
    with pytest.raises(ValidationError, match=message):
        full.FullFilmManifest.model_validate_json(json.dumps(payload))


@pytest.mark.parametrize("tenant_id", [UUID(int=0), "not-a-uuid", None])
def test_media_identity_requires_nonzero_uuid(tenant_id: object) -> None:
    with pytest.raises(MediaConfigurationError, match="nonzero tenant"):
        full.full_film_media_identity(tenant_id)  # type: ignore[arg-type]


def test_media_identity_is_stable_and_tenant_scoped() -> None:
    assert full.full_film_media_identity(TENANT_ID) == full.full_film_media_identity(TENANT_ID)
    assert full.full_film_media_identity(TENANT_ID) != full.full_film_media_identity(uuid4())


def test_wrong_manifest_digest_is_rejected_before_root_access(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(full, "MANIFEST_PATH", None)
    with pytest.raises(MediaConfigurationError, match="package-owned manifest hash"):
        full.load_verified_full_film_pack(
            tenant_id=TENANT_ID,
            root=Path("not-opened"),
            expected_manifest_sha256="0" * 64,
        )


def test_actual_complete_pack_loads_with_hashes_probes_and_private_keys() -> None:
    if not PACK_ROOT.is_dir():
        pytest.skip("the ignored 1.46 GB full-film pack is not installed on this test host")
    pack = full.load_verified_full_film_pack(
        tenant_id=TENANT_ID,
        root=PACK_ROOT,
        expected_manifest_sha256=full.MANIFEST_SHA256,
    )
    pack.require_scope(tenant_id=TENANT_ID)
    with pytest.raises(MediaConfigurationError, match="scope"):
        pack.require_scope(tenant_id=uuid4())
    with pytest.raises(MediaConfigurationError, match="scope"):
        replace(pack, processing_result=ProcessingResult()).require_scope(tenant_id=TENANT_ID)
    assert pack.source_key.startswith(f"tenants/{TENANT_ID}/media/video/")
    assert pack.progressive_key.startswith(pack.source_key + "/renditions/progressive/")
    assert pack.hls_master_key == pack.source_key + "/renditions/hls/master.m3u8"
    assert pack.storage.head(pack.source_key) is not None
    assert pack.storage.read_prefix(pack.source_key, max_bytes=8)[4:8] == b"ftyp"
    result = pack.processing_result
    assert result.duration_seconds == 634.6
    assert (result.width, result.height) == (3840, 2160)
    assert result.captions == ()
    assert len(result.object_keys) == 278
    assert result.hls_manifest is not None
    assert len(result.hls_manifest.object_keys) == 277
    assert [(item.width, item.height) for item in result.hls_manifest.renditions] == [
        (3840, 2160),
        (1280, 720),
    ]
