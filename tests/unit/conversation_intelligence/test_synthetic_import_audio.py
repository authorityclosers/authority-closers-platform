"""Synthetic provenance, retention restart and narrow transport-limit proof."""

import hashlib
from copy import deepcopy
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI, Request
from pydantic import ValidationError

from ac_platform.conversation_intelligence.checkpoints import content_hash
from ac_platform.conversation_intelligence.storage import PrivateLocalRecordingStorage, StorageError
from ac_platform.conversation_intelligence.synthetic_import_audio import (
    SyntheticAudioManifest,
    media_key,
    retain_audio,
)
from ac_platform.conversation_intelligence.synthetic_import_contracts import SyntheticCallBundle
from ac_platform.http.request_limits import RequestBodyLimitMiddleware
from tests.unit.conversation_intelligence.test_synthetic_import_contracts import bundle


def media_bundle(payload: bytes = b"fictional-transport-only"):
    data = bundle()
    data["metadata"].update(
        audio_file="audio.mp3", audio_status="verified", timing_source="spool_exact"
    )
    line = data["transcript"]["lines"][0]
    line.update(speaker="rep", playable=True, timing_source="spool_exact")
    call_id = data["metadata"]["call_id"]
    timing = {
        "id": call_id,
        "duration": 1.0,
        "segments": [{"n": 0, "speaker": "rep", "text": line["text"], "start": 0.0, "end": 1.0}],
    }
    manifest = {
        "schema": "synthetic-call-audio/1",
        "synthetic": True,
        "call_id": call_id,
        "call_bundle_sha256": content_hash(data),
        "audio_sha256": hashlib.sha256(payload).hexdigest(),
        "audio_bytes": len(payload),
        "content_type": "audio/mpeg",
        "duration_ms": 1000,
        "timing_file_sha256": "b" * 64,
        "timing": timing,
        "verification": {
            "call_id": call_id,
            "request_id": call_id,
            "status": "verified",
            "canonical_text_matches_audio": True,
            "media_decode_complete": True,
            "codec": "mp3",
            "duration_ms": 1000,
            "timing_source": "spool_exact",
            "audio_sha256": hashlib.sha256(payload).hexdigest(),
            "timing_sha256": "b" * 64,
        },
    }
    return data, manifest


def test_exact_timing_text_and_authoring_hash_bind_media_to_one_call():
    data, body = media_bundle()
    manifest = SyntheticAudioManifest.model_validate(body)
    parsed = SyntheticCallBundle.model_validate(data)
    manifest.require_bundle(parsed)
    changed = deepcopy(data)
    changed["transcript"]["lines"][0]["text"] += " changed"
    with pytest.raises(ValueError, match="exact authored"):
        manifest.require_bundle(SyntheticCallBundle.model_validate(changed))
    changed = deepcopy(body)
    changed["timing"]["segments"][0]["text"] += " changed"
    with pytest.raises(ValueError, match="every canonical"):
        SyntheticAudioManifest.model_validate(changed).require_bundle(parsed)


@pytest.mark.parametrize(
    "field,value",
    [
        ("canonical_text_matches_audio", False),
        ("media_decode_complete", False),
        ("status", "legacy_verified"),
        ("audio_sha256", "c" * 64),
        ("codec", "wav"),
        ("timing_source", "estimated_reading"),
    ],
)
def test_unverified_or_legacy_provenance_is_refused(field, value):
    _, body = media_bundle()
    body["verification"][field] = value
    with pytest.raises(ValidationError):
        SyntheticAudioManifest.model_validate(body)


def test_atomic_object_published_before_database_commit_replays_without_overwrite(tmp_path):
    payload = b"fictional-transport-only"
    _, body = media_bundle(payload)
    manifest = SyntheticAudioManifest.model_validate(body)
    tenant = uuid4()
    key = media_key(tenant, manifest)
    assert key != media_key(uuid4(), manifest)
    storage = PrivateLocalRecordingStorage(tmp_path / "private-media")
    retain_audio(storage, key, manifest, [payload])
    # A fresh adapter represents a process restart after publication/DB rollback.
    fresh = PrivateLocalRecordingStorage(storage.root)
    retain_audio(fresh, key, manifest, [payload])
    assert b"".join(fresh.iter_bytes(key, expected_sha256=manifest.audio_sha256)) == payload
    with pytest.raises(StorageError, match="digest_mismatch"):
        retain_audio(fresh, key, manifest, [b"x" * len(payload)])


@pytest.mark.parametrize(
    "enabled,path,method,expected",
    [
        (
            True,
            "/v1/conversation/acquisition/imports/sandbox/calls/syn-fixture-call/source",
            "PUT",
            200,
        ),
        (
            False,
            "/v1/conversation/acquisition/imports/sandbox/calls/syn-fixture-call/source",
            "PUT",
            413,
        ),
        (True, "/v1/conversation/acquisition/imports/sandbox/calls/real-call/source", "PUT", 413),
        (
            True,
            "/v1/conversation/acquisition/imports/sandbox/calls/syn-fixture-call/source",
            "POST",
            413,
        ),
    ],
)
async def test_large_media_requires_the_existing_enabled_byte_cap_and_exact_path(
    enabled, path, method, expected
):
    app = FastAPI()

    @app.api_route("/{path:path}", methods=["PUT", "POST"])
    async def consume(request: Request):
        return {"size": len(await request.body())}

    bounded = RequestBodyLimitMiddleware(
        app, acquisition_upload_max_bytes=2 * 1024 * 1024 if enabled else None
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=bounded), base_url="http://test"
    ) as client:
        response = await client.request(method, path, content=b"x" * (1024 * 1024 + 1))
        assert response.status_code == expected
