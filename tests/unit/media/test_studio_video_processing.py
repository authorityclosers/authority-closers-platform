"""Processing-boundary tests with explicitly injected encoder/probe fixtures.

These do not prove codec validity or canonical admission. The real FFmpeg +
PostgreSQL suite exercises those boundaries separately.
"""

from dataclasses import replace
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

from ac_platform.media.errors import MediaConflict, MediaForbidden, MediaProcessingError
from ac_platform.media.processing import FFmpegMediaProcessor, ProcessingResult
from ac_platform.media.service import MediaService
from ac_platform.media.signing import MediaSigner
from ac_platform.media.studio_video_processing import PreparedStudioVideo, StudioVideoProcessing
from ac_platform.media.video_file_storage import VideoFileStorage
from tests.unit.media.test_video_processing_attempts import _processor


@pytest.fixture
def pipeline(tmp_path):
    storage = VideoFileStorage(
        root=tmp_path / "video-objects", max_object_bytes=1024**2, max_store_bytes=8 * 1024**2
    )
    processor = _processor()
    service = MediaService(
        storage=storage,
        processor=processor,
        processing_quota=processor.quota,
        signer=MediaSigner("synthetic-processing-unit-test-signing-key-long"),
        webhook_secret="synthetic-processing-unit-test-webhook-key-long",  # noqa: S106
    )  # noqa: S106
    pipeline = StudioVideoProcessing(service)
    tenant, asset, version = uuid4(), uuid4(), uuid4()
    key = f"tenants/{tenant}/media/video/{asset}/{version}/original"
    head = storage.put(object_key=key, body=b"synthetic-source", content_type="video/mp4")
    prepared = PreparedStudioVideo(
        uuid4(),
        tenant,
        uuid4(),
        uuid4(),
        asset,
        version,
        uuid4(),
        key,
        "video/mp4",
        head.content_length,
        head.checksum_sha256,
        head.storage_version_id,
        uuid4(),
        1,
        pipeline._seal,
    )
    return pipeline, prepared


def test_guarded_result_release_preserves_outputs_and_cannot_be_discarded_later(pipeline):
    owner, prepared = pipeline
    verified = owner.process(prepared, attempt_id=uuid4())
    with pytest.raises(MediaConflict):
        owner.storage.delete(verified.result.object_keys[0])
    with pytest.raises(MediaConflict):
        owner.storage.delete(prepared.object_key)
    with pytest.raises(MediaForbidden):
        owner._require_verified(prepared, replace(verified, result=ProcessingResult()))
    owner.release(verified)
    with pytest.raises(MediaForbidden):
        owner.discard(verified)
    with pytest.raises(MediaForbidden):
        owner._require_verified(prepared, verified)
    assert all(owner.storage.head(key) is not None for key in verified.result.object_keys)


def test_failed_attempt_discard_is_exact_and_preserves_previously_committed_outputs(pipeline):
    owner, prepared = pipeline
    previous = owner.process(prepared, attempt_id=uuid4())
    owner.release(previous)
    current = owner.process(prepared, attempt_id=uuid4())
    owner.discard(current)
    assert all(owner.storage.head(key) is None for key in current.result.object_keys)
    assert all(owner.storage.head(key) is not None for key in previous.result.object_keys)
    assert owner.storage.read(prepared.object_key) == b"synthetic-source"


@pytest.mark.parametrize(
    "field,value",
    [
        ("checksum_sha256", "a" * 64),
        ("storage_version_id", "b" * 64),
        ("source_bytes", 999),
        ("content_type", "video/webm"),
    ],
)
def test_source_envelope_mismatch_never_starts_encoder(pipeline, monkeypatch, field, value):
    owner, prepared = pipeline

    def forbidden(**kwargs):
        pytest.fail("encoder must not run for a changed source")

    monkeypatch.setattr(owner.processor, "process", forbidden)
    with pytest.raises(MediaConflict):
        owner.process(replace(prepared, **{field: value}), attempt_id=uuid4())
    assert owner.storage.list_prefix(prepared.object_key) == (prepared.object_key,)


@pytest.mark.parametrize(
    "fault", ["duration", "dimensions", "bytes", "inventory", "protocol", "foreign"]
)
def test_unverified_outputs_are_rejected_and_only_owned_inventory_is_cleaned(
    pipeline, monkeypatch, fault
):
    owner, prepared = pipeline
    real_process = owner.processor.process
    attempt_id = uuid4()
    foreign_key = f"{prepared.object_key}/attempts/{uuid4()}/untouched.mp4"
    owner.storage.put(
        object_key=foreign_key, body=b"existing-other-attempt", content_type="video/mp4"
    )

    def invalid(**kwargs):
        result = real_process(**kwargs)
        if fault == "duration":
            return replace(result, duration_seconds=None)
        if fault == "dimensions":
            return replace(result, width=None, height=None)
        if fault == "bytes":
            return replace(result, output_bytes=1)
        if fault == "inventory":
            return replace(result, object_keys=result.object_keys[:-1])
        if fault == "protocol":
            return replace(
                result, renditions=tuple(r for r in result.renditions if r.protocol == "hls")
            )
        return replace(result, object_keys=(*result.object_keys, foreign_key))

    monkeypatch.setattr(owner.processor, "process", invalid)
    with pytest.raises((MediaProcessingError, MediaConflict)):
        owner.process(prepared, attempt_id=attempt_id)
    assert owner.storage.read(foreign_key) == b"existing-other-attempt"
    assert owner.storage.read(prepared.object_key) == b"synthetic-source"
    assert not owner._verified


def test_source_changed_during_encoding_is_rejected(pipeline, monkeypatch):
    owner, prepared = pipeline
    real_process = owner.processor.process

    def changed(**kwargs):
        result = real_process(**kwargs)
        owner.storage.delete(prepared.object_key)
        owner.storage.put(
            object_key=prepared.object_key, body=b"changed-source", content_type="video/mp4"
        )
        return result

    monkeypatch.setattr(owner.processor, "process", changed)
    attempt = uuid4()
    with pytest.raises(MediaConflict):
        owner.process(prepared, attempt_id=attempt)
    assert owner.storage.list_prefix(f"{prepared.object_key}/attempts/{attempt}/") == ()


def test_pipeline_composition_rejects_fake_processor_and_changed_quota(pipeline):
    owner, prepared = pipeline
    owner.service.processor = object()
    with pytest.raises(ValueError, match="FFmpeg"):
        StudioVideoProcessing(owner.service)
    with pytest.raises(MediaForbidden, match="composition"):
        owner.process(prepared, attempt_id=uuid4())
    owner.service.processor = FFmpegMediaProcessor()
    with pytest.raises(ValueError, match="quotas"):
        StudioVideoProcessing(owner.service)


@pytest.mark.parametrize("outcome", ["commit", "rollback", "commit_unknown", "nested_commit"])
def test_cleanup_rights_follow_exact_outer_transaction_not_caller_claim(pipeline, outcome):
    owner, prepared = pipeline
    verified = owner.process(prepared, attempt_id=uuid4())
    engine = create_engine("sqlite:///:memory:")
    try:
        with Session(engine) as session:
            transaction = session.begin()
            owner._begin_finalization(SimpleNamespace(sync_session=session), verified)
            with pytest.raises(MediaForbidden):
                owner.discard(verified)
            with pytest.raises(MediaForbidden):
                owner.release(verified)
            if outcome == "nested_commit":
                with session.begin_nested():
                    pass
                assert verified._lifecycle.phase == "finalizing"
                transaction.rollback()
            elif outcome == "commit_unknown":

                def ambiguous(current):
                    raise RuntimeError("synthetic ambiguous commit")

                event.listen(session, "before_commit", ambiguous)
                with pytest.raises(RuntimeError):
                    transaction.commit()
                transaction.rollback()
                assert verified._lifecycle.phase == "uncertain"
            elif outcome == "rollback":
                transaction.rollback()
            else:
                transaction.commit()
            if outcome in {"rollback", "nested_commit"}:
                owner.discard(verified)
                assert all(owner.storage.head(key) is None for key in verified.result.object_keys)
            else:
                with pytest.raises(MediaForbidden):
                    owner.discard(verified)
                owner.release(verified)
                assert all(
                    owner.storage.head(key) is not None for key in verified.result.object_keys
                )
            assert not owner._verified
    finally:
        engine.dispose()
