from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from queue import Queue
from threading import Barrier, Thread
from uuid import UUID

import pytest

from ac_platform.media.errors import MediaConflict, MediaStorageUnavailable
from ac_platform.media.lifecycle import (
    MediaLifecycleAction,
    MediaLifecycleEvent,
    MediaObjectDeletionWorker,
    MediaObjectReference,
)
from ac_platform.media.video_file_storage import VideoFileStorage

KEY = (
    "tenants/11111111-1111-4111-8111-111111111111/media/video/"
    "22222222-2222-4222-8222-222222222222/33333333-3333-4333-8333-333333333333/original"
)
DATA = b"resumable-browser-upload-proof" * 3


def _store(tmp_path):
    return VideoFileStorage(
        root=tmp_path / "video-objects",
        max_object_bytes=1024 * 1024,
        max_store_bytes=2 * 1024 * 1024,
    )


def _chunk(store, data, offset, body):
    return store.put_resumable_chunk(
        object_key=KEY,
        body=body,
        content_type="video/mp4",
        content_length=len(data),
        checksum_sha256=hashlib.sha256(data).hexdigest(),
        offset=offset,
        chunk_checksum_sha256=hashlib.sha256(body).hexdigest(),
    )


def _chunk_for(store, key, data, offset, body):
    return store.put_resumable_chunk(
        object_key=key,
        body=body,
        content_type="video/mp4",
        content_length=len(data),
        checksum_sha256=hashlib.sha256(data).hexdigest(),
        offset=offset,
        chunk_checksum_sha256=hashlib.sha256(body).hexdigest(),
    )


def test_chunks_resume_replay_and_publish_only_after_full_source(tmp_path):
    store = _store(tmp_path)
    first, second = DATA[:17], DATA[17:]

    assert _chunk(store, DATA, 0, first).uploaded_bytes == len(first)
    assert store.head(KEY) is None
    # A lost response can safely replay the exact same request.
    assert _chunk(store, DATA, 0, first).uploaded_bytes == len(first)
    result = _chunk(store, DATA, len(first), second)

    assert result.uploaded_bytes == len(DATA)
    assert result.metadata is not None
    assert store.read(KEY) == DATA


def test_chunks_reject_gaps_overlap_and_tampered_replays(tmp_path):
    store = _store(tmp_path)
    first = DATA[:17]
    _chunk(store, DATA, 0, first)

    with pytest.raises(MediaConflict, match="gap"):
        _chunk(store, DATA, len(first) + 1, DATA[18:25])
    with pytest.raises(MediaConflict, match="overlaps"):
        _chunk(store, DATA, len(first) - 1, DATA[16:25])
    with pytest.raises(MediaConflict, match="does not match"):
        _chunk(store, DATA, 0, b"different-replay")


def test_final_chunk_replay_publishes_after_an_authority_retry(tmp_path):
    store = _store(tmp_path)
    first = DATA[:17]
    _chunk(store, DATA, 0, first)
    calls = []

    def denied():
        calls.append("checked")
        raise RuntimeError("authority temporarily unavailable")

    with pytest.raises(RuntimeError):
        store.put_resumable_chunk(
            object_key=KEY,
            body=DATA[17:],
            content_type="video/mp4",
            content_length=len(DATA),
            checksum_sha256=hashlib.sha256(DATA).hexdigest(),
            offset=17,
            chunk_checksum_sha256=hashlib.sha256(DATA[17:]).hexdigest(),
            before_publish=denied,
        )
    assert calls == ["checked"]
    assert store.head(KEY) is None
    restarted = VideoFileStorage(
        root=tmp_path / "video-objects",
        max_object_bytes=1024 * 1024,
        max_store_bytes=2 * 1024 * 1024,
    )
    result = restarted.put_resumable_chunk(
        object_key=KEY,
        body=DATA[17:],
        content_type="video/mp4",
        content_length=len(DATA),
        checksum_sha256=hashlib.sha256(DATA).hexdigest(),
        offset=17,
        chunk_checksum_sha256=hashlib.sha256(DATA[17:]).hexdigest(),
    )
    assert result.metadata is not None
    assert restarted.read(KEY) == DATA


def test_checksum_failure_cannot_be_recovered_by_replaying_final_chunk(tmp_path):
    store = _store(tmp_path)
    first = DATA[:17]
    wrong_checksum = hashlib.sha256(DATA + b"tampered").hexdigest()
    store.put_resumable_chunk(
        object_key=KEY,
        body=first,
        content_type="video/mp4",
        content_length=len(DATA),
        checksum_sha256=wrong_checksum,
        offset=0,
        chunk_checksum_sha256=hashlib.sha256(first).hexdigest(),
    )
    final = DATA[17:]
    for _attempt in range(2):
        with pytest.raises(MediaStorageUnavailable, match="checksum"):
            store.put_resumable_chunk(
                object_key=KEY,
                body=final,
                content_type="video/mp4",
                content_length=len(DATA),
                checksum_sha256=wrong_checksum,
                offset=17,
                chunk_checksum_sha256=hashlib.sha256(final).hexdigest(),
            )
        assert store.head(KEY) is None


def test_exact_delete_removes_expired_reservation_without_listing_partial(tmp_path):
    store = _store(tmp_path)
    _chunk(store, DATA, 0, DATA[:17])
    partials = tuple(store.root.glob("*.part"))
    assert len(partials) == 1
    assert store.list_prefix(KEY) == ()
    assert store.head(KEY) is None

    store.delete(KEY)

    assert not partials[0].exists()
    assert store.list_prefix(KEY) == ()
    assert store.head(KEY) is None


def test_delete_keeps_other_ready_objects_and_rejects_unowned_paths(tmp_path):
    store = _store(tmp_path)
    other = KEY.replace(
        "33333333-3333-4333-8333-333333333333",
        "44444444-4444-4444-8444-444444444444",
    )
    _chunk(store, DATA, 0, DATA[:17])
    _chunk_for(store, other, DATA, 0, DATA)
    assert store.list_prefix(KEY) == ()
    assert store.head(other) is not None

    with pytest.raises(MediaStorageUnavailable):
        store.delete("not-a-private-object")
    store.delete(KEY)
    assert store.head(other) is not None


def test_lifecycle_delete_due_retires_a_crashed_or_expired_partial(tmp_path):
    store = _store(tmp_path)
    _chunk(store, DATA, 0, DATA[:17])
    now = datetime.now(UTC)
    reference = MediaObjectReference(
        tenant_id=UUID("11111111-1111-4111-8111-111111111111"),
        asset_id=UUID("22222222-2222-4222-8222-222222222222"),
        version_id=UUID("33333333-3333-4333-8333-333333333333"),
        object_key=KEY,
    )
    event = MediaLifecycleEvent(
        action=MediaLifecycleAction.DELETE_SCHEDULED,
        reference=reference,
        occurred_at=now - timedelta(minutes=1),
        not_before=now - timedelta(seconds=1),
    )

    completed = MediaObjectDeletionWorker(store).delete_due((event,), now=now)

    assert len(completed) == 1
    assert completed[0].action is MediaLifecycleAction.DELETE_COMPLETED
    assert store.head(KEY) is None
    assert not tuple(store.root.glob("*.part"))


def test_different_resumable_keys_share_the_global_quota_guard(tmp_path):
    store = VideoFileStorage(
        root=tmp_path / "video-objects",
        max_object_bytes=1,
        max_store_bytes=8193,
        max_objects=2,
    )
    key2 = KEY.replace(
        "33333333-3333-4333-8333-333333333333",
        "44444444-4444-4444-8444-444444444444",
    )
    barrier = Barrier(2)
    results = Queue()

    def run(key):
        try:
            barrier.wait(timeout=5)
            results.put((key, _chunk_for(store, key, b"x", 0, b"x")))
        except BaseException as error:
            results.put((key, error))

    threads = [Thread(target=run, args=(key,), daemon=True) for key in (KEY, key2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5)
    assert all(not thread.is_alive() for thread in threads)
    outcomes = [results.get_nowait() for _ in threads]
    assert sum(not isinstance(result, BaseException) for _, result in outcomes) == 1
    assert sum(isinstance(result, MediaStorageUnavailable) for _, result in outcomes) == 1
