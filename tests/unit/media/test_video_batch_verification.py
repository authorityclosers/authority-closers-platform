from __future__ import annotations

import hashlib
import subprocess
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from queue import Queue
from threading import Thread

import pytest

from ac_platform.media import video_file_storage as module
from ac_platform.media.errors import MediaConflict, MediaStorageUnavailable
from ac_platform.media.video_file_storage import CHUNK_BYTES, VideoFileStorage

KEY = (
    "tenants/11111111-1111-4111-8111-111111111111/media/video/"
    "22222222-2222-4222-8222-222222222222/33333333-3333-4333-8333-333333333333/original"
)
DATA = b"batch-verification-video"


def store(root: Path) -> VideoFileStorage:
    return VideoFileStorage(
        root=root,
        max_object_bytes=8 * CHUNK_BYTES,
        max_store_bytes=16 * CHUNK_BYTES,
    )


def write(adapter: VideoFileStorage, *, key: str = KEY, data: bytes = DATA) -> None:
    adapter.put_stream(
        object_key=key,
        chunks=(data[i : i + 7] for i in range(0, len(data), 7)),
        content_type="video/mp4",
        content_length=len(data),
        checksum_sha256=hashlib.sha256(data).hexdigest(),
    )


def _stripe(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()[:2]


def _same_stripe_key(key: str, *, prefix: str = "batch-collision") -> str:
    stripe = _stripe(key)
    for index in range(65536):
        candidate = f"{key}/attempts/{prefix}-{index}/video.mp4"
        if _stripe(candidate) == stripe:
            return candidate
    raise AssertionError("could not find a same-stripe key")


def _different_stripe_key(key: str) -> str:
    stripe = _stripe(key)
    for index in range(65536):
        candidate = f"{key}/attempts/batch-other-{index}/video.mp4"
        if _stripe(candidate) != stripe:
            return candidate
    raise AssertionError("could not find a different-stripe key")


def test_batch_verification_acquires_sorted_unique_stripes_before_inspection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    adapter = store(tmp_path / "video-objects")
    same_key = _same_stripe_key(KEY)
    other_key = _different_stripe_key(KEY)
    for key in (KEY, same_key, other_key):
        write(adapter, key=key)

    acquired: list[str] = []
    inspected: list[tuple[str, tuple[str, ...]]] = []
    original_lock = adapter._lock
    original_inspect = adapter._inspect

    @contextmanager
    def observed_lock(name: str) -> Iterator[None]:
        acquired.append(name)
        with original_lock(name):
            yield

    def observed_inspect(key: str):
        inspected.append((key, tuple(acquired)))
        return original_inspect(key)

    monkeypatch.setattr(adapter, "_lock", observed_lock)
    monkeypatch.setattr(adapter, "_inspect", observed_inspect)
    keys = (other_key, KEY, same_key)
    with adapter.hold_verifications(keys) as leases:
        assert tuple(lease.metadata.object_key for lease in leases) == keys
        assert all(lease.active for lease in leases)
        for lease, key in zip(leases, keys, strict=True):
            assert adapter.require_verification(lease, object_key=key) == lease.metadata

    assert acquired == sorted(set(acquired))
    assert len(acquired) == 2
    assert [key for key, _ in inspected] == list(keys)
    assert all(held == tuple(acquired) for _, held in inspected)
    assert all(not lease.active for lease in leases)
    write(adapter, key=KEY)


@pytest.mark.parametrize(
    "object_keys",
    [
        (),
        [KEY],
        (KEY, KEY),
        (KEY, ""),
        tuple(f"{KEY}/attempts/batch-bound-{index}/video.mp4" for index in range(4097)),
    ],
    ids=["empty", "not-tuple", "duplicate", "empty-key", "over-bound"],
)
def test_batch_verification_rejects_invalid_shape_before_locking(
    tmp_path: Path, object_keys: object
) -> None:
    adapter = store(tmp_path / "video-objects")
    before = tuple(adapter.root.glob("*.lock"))
    with (
        pytest.raises(MediaStorageUnavailable),
        adapter.hold_verifications(  # type: ignore[arg-type]
            object_keys
        ),
    ):
        pass
    assert tuple(adapter.root.glob("*.lock")) == before


def test_batch_verification_validates_every_lease_and_invalidates_all_on_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    adapter = store(tmp_path / "video-objects")
    same_key = _same_stripe_key(KEY)
    write(adapter)
    write(adapter, key=same_key)
    original_validate = adapter._validate_verification
    checked: list[str] = []

    def fail_first(lease) -> None:
        checked.append(lease.metadata.object_key)
        original_validate(lease)
        if lease.metadata.object_key == KEY:
            raise MediaStorageUnavailable("synthetic final validation failure")

    monkeypatch.setattr(adapter, "_validate_verification", fail_first)
    leases = ()
    with (
        pytest.raises(MediaStorageUnavailable, match="synthetic final validation failure"),
        adapter.hold_verifications((KEY, same_key)) as active_leases,
    ):
        leases = active_leases
        assert all(lease.active for lease in active_leases)
    assert checked == [KEY, same_key]
    assert all(not lease.active for lease in leases)
    write(adapter)
    write(adapter, key=same_key)


def test_batch_verification_invalidates_all_leases_when_body_fails(tmp_path: Path) -> None:
    adapter = store(tmp_path / "video-objects")
    same_key = _same_stripe_key(KEY)
    write(adapter)
    write(adapter, key=same_key)
    leases = ()
    with (
        pytest.raises(RuntimeError, match="synthetic body failure"),
        adapter.hold_verifications((KEY, same_key)) as active_leases,
    ):
        leases = active_leases
        raise RuntimeError("synthetic body failure")
    assert all(not lease.active for lease in leases)
    write(adapter)
    write(adapter, key=same_key)


def test_batch_verification_releases_partially_acquired_stripes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    adapter = store(tmp_path / "video-objects")
    other_key = _different_stripe_key(KEY)
    write(adapter)
    write(adapter, key=other_key)
    original_lock = adapter._lock
    calls = 0

    @contextmanager
    def fail_second_lock(name: str) -> Iterator[None]:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise MediaStorageUnavailable("synthetic lock acquisition failure")
        with original_lock(name):
            yield

    monkeypatch.setattr(adapter, "_lock", fail_second_lock)
    with (
        pytest.raises(MediaStorageUnavailable, match="lock acquisition"),
        adapter.hold_verifications((KEY, other_key)),
    ):
        pass
    assert calls == 2
    write(adapter)
    write(adapter, key=other_key)


_HELD_BATCH_SCRIPT = """
import sys
from pathlib import Path
from ac_platform.media.video_file_storage import CHUNK_BYTES, VideoFileStorage

root, first_key, second_key = sys.argv[1:]
adapter = VideoFileStorage(
    root=Path(root), max_object_bytes=8 * CHUNK_BYTES, max_store_bytes=16 * CHUNK_BYTES
)
with adapter.hold_verifications((first_key, second_key)) as leases:
    print(len(leases), flush=True)
    if sys.stdin.readline() != "release\\n":
        raise RuntimeError("batch lock release was not requested")
"""


@pytest.mark.parametrize("operation", ["write", "delete"])
def test_batch_verification_blocks_cross_process_write_or_delete_until_release(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, operation: str
) -> None:
    adapter = store(tmp_path / "video-objects")
    same_key = _same_stripe_key(KEY, prefix=f"process-{operation}")
    write(adapter)
    write(adapter, key=same_key)
    target_key = (
        same_key
        if operation == "delete"
        else _same_stripe_key(KEY, prefix=f"process-{operation}-target")
    )
    monkeypatch.setattr(module, "_GUARD_WAIT_SECONDS", 0.1)
    monkeypatch.setattr(module, "_GUARD_RETRY_SECONDS", 0.005)
    with subprocess.Popen(  # noqa: S603 - fixed Python helper and bounded local test inputs
        [sys.executable, "-c", _HELD_BATCH_SCRIPT, str(adapter.root), KEY, same_key],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        shell=False,
        creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
    ) as worker:
        assert worker.stdout is not None
        ready: Queue[str] = Queue(maxsize=1)
        reader = Thread(target=lambda: ready.put(worker.stdout.readline()), daemon=True)
        reader.start()
        try:
            assert ready.get(timeout=15) == "2\n"
            if operation == "write":
                with pytest.raises((MediaConflict, MediaStorageUnavailable)):
                    write(adapter, key=target_key, data=b"different")
            else:
                with pytest.raises((MediaConflict, MediaStorageUnavailable)):
                    adapter.delete(target_key)
            assert worker.poll() is None
            assert worker.stdin is not None
            output, error = worker.communicate("release\n", timeout=15)
            assert worker.returncode == 0, error
            assert output.strip() == ""
        finally:
            if worker.poll() is None:
                if worker.stdin is not None:
                    worker.stdin.write("release\n")
                    worker.stdin.flush()
                try:
                    worker.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    worker.kill()
                    worker.wait(timeout=5)
            reader.join(timeout=5)
            assert not reader.is_alive()
    if operation == "write":
        write(adapter, key=target_key, data=b"different")
        assert adapter.read(target_key) == b"different"
    else:
        adapter.delete(target_key)
        assert adapter.head(target_key) is None
