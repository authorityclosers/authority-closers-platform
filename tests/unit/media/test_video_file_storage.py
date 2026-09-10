from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from queue import Queue
from threading import Event, Thread, current_thread
from uuid import uuid4

import pytest

from ac_platform.media import video_file_storage as module
from ac_platform.media.errors import MediaConflict, MediaForbidden, MediaStorageUnavailable
from ac_platform.media.storage import PrivateObjectStorage
from ac_platform.media.video_file_storage import CHUNK_BYTES, VideoFileStorage

KEY = (
    "tenants/11111111-1111-4111-8111-111111111111/media/video/"
    "22222222-2222-4222-8222-222222222222/33333333-3333-4333-8333-333333333333/original"
)
DATA = b"\x00\x00\x00\x18ftypmp42" + b"video-bytes" * 300


def store(root: Path, **kwargs) -> VideoFileStorage:
    return VideoFileStorage(
        root=root,
        max_object_bytes=kwargs.pop("max_object_bytes", 8 * CHUNK_BYTES),
        max_store_bytes=kwargs.pop("max_store_bytes", 16 * CHUNK_BYTES),
        **kwargs,
    )


def write(adapter: VideoFileStorage, *, key=KEY, data=DATA):
    return adapter.put_stream(
        object_key=key,
        chunks=(data[i : i + 37] for i in range(0, len(data), 37)),
        content_type="video/mp4",
        content_length=len(data),
        checksum_sha256=hashlib.sha256(data).hexdigest(),
    )


def write_create_only(adapter: VideoFileStorage, *, key=KEY, data=DATA):
    return adapter.put_stream(
        object_key=key,
        chunks=(data[i : i + 37] for i in range(0, len(data), 37)),
        content_type="video/mp4",
        content_length=len(data),
        checksum_sha256=hashlib.sha256(data).hexdigest(),
        create_only=True,
    )


@pytest.mark.parametrize("existing", [False, True])
def test_fresh_authority_is_required_before_private_publish_or_replay(tmp_path, existing):
    adapter = store(tmp_path / "video-objects")
    if existing:
        write(adapter)
    calls = []

    def rejected():
        calls.append("reauthorized")
        raise MediaForbidden("The upload permission was revoked.")

    with pytest.raises(MediaForbidden):
        adapter.put_stream(
            object_key=KEY,
            chunks=iter((DATA,)),
            content_type="video/mp4",
            content_length=len(DATA),
            checksum_sha256=hashlib.sha256(DATA).hexdigest(),
            before_publish=rejected,
        )
    assert calls == ["reauthorized"]
    assert not list(adapter.root.glob("*.part"))
    assert (adapter.head(KEY) is not None) is existing
    # Rejection never deletes an immutable existing object. A later authorized
    # retry can still succeed without a new version or duplicate reservation.
    assert write(adapter).content_length == len(DATA)


def test_authority_callback_runs_after_all_input_but_before_object_visibility(tmp_path):
    adapter = store(tmp_path / "video-objects")
    observed = []

    def chunks():
        observed.append("streaming")
        yield DATA
        observed.append("complete")

    def reauthorize():
        assert observed == ["streaming", "complete"]
        assert adapter.head(KEY) is None
        observed.append("reauthorized")

    adapter.put_stream(
        object_key=KEY,
        chunks=chunks(),
        content_type="video/mp4",
        content_length=len(DATA),
        checksum_sha256=hashlib.sha256(DATA).hexdigest(),
        before_publish=reauthorize,
    )
    assert observed[-1] == "reauthorized"
    assert adapter.read(KEY) == DATA


def test_real_disk_roundtrip_restart_copy_ranges_and_immutable_retry(tmp_path):
    root = tmp_path / "video-objects"
    adapter = store(root)
    metadata = write(adapter)
    assert metadata.content_length == len(DATA)
    assert metadata.checksum_sha256 == hashlib.sha256(DATA).hexdigest()
    assert adapter.read(KEY) == DATA
    assert adapter.read_prefix(KEY, max_bytes=7) == DATA[:7]
    assert b"".join(adapter.iter_range(KEY, start=17, end=69, chunk_size=9)) == DATA[17:70]
    restarted = store(root)
    assert restarted.head(KEY) == metadata
    assert restarted.read(KEY) == DATA
    assert write(restarted) == metadata
    with pytest.raises(MediaConflict):
        write(restarted, data=b"different")
    derived = KEY + "/attempts/one/progressive.mp4"
    copy = restarted.copy(source_key=KEY, destination_key=derived, content_type="video/mp4")
    assert copy.checksum_sha256 == metadata.checksum_sha256
    assert copy.storage_version_id != metadata.storage_version_id
    assert restarted.list_prefix(KEY) == (KEY, derived)
    restarted.delete(derived)
    assert restarted.head(derived) is None
    assert restarted.read(KEY) == DATA


def test_create_only_rejects_existing_objects_and_default_replay_is_unchanged(tmp_path):
    adapter = store(tmp_path / "video-objects")
    metadata = write(adapter)
    assert write(adapter) == metadata
    with pytest.raises(MediaConflict, match="destination already exists"):
        write_create_only(adapter)
    assert adapter.read(KEY) == DATA

    put_key = KEY + "/attempts/put/progressive.mp4"
    put_metadata = adapter.put(object_key=put_key, body=DATA, content_type="video/mp4")
    assert adapter.put(object_key=put_key, body=DATA, content_type="video/mp4") == put_metadata
    with pytest.raises(MediaConflict, match="destination already exists"):
        adapter.put(
            object_key=put_key,
            body=DATA,
            content_type="video/mp4",
            create_only=True,
        )
    assert adapter.read(put_key) == DATA

    copy_key = KEY + "/attempts/copy/progressive.mp4"
    copy_metadata = adapter.copy(source_key=KEY, destination_key=copy_key, content_type="video/mp4")
    assert (
        adapter.copy(source_key=KEY, destination_key=copy_key, content_type="video/mp4")
        == copy_metadata
    )
    with pytest.raises(MediaConflict, match="destination already exists"):
        adapter.copy(
            source_key=KEY,
            destination_key=copy_key,
            content_type="video/mp4",
            create_only=True,
        )
    assert adapter.read(copy_key) == DATA


def test_create_only_same_key_race_has_one_winner_without_overwriting_bytes(tmp_path):
    root = tmp_path / "video-objects"
    first, second = store(root), store(root)
    first_data, second_data = b"first-writer", b"second-writer"
    entered, release, second_done = Event(), Event(), Event()
    first_results, second_results = Queue(), Queue()

    def hold_before_publish():
        entered.set()
        assert release.wait(5)

    first_thread = Thread(
        target=_record_operation,
        args=(
            lambda: first.put_stream(
                object_key=KEY,
                chunks=iter((first_data,)),
                content_type="video/mp4",
                content_length=len(first_data),
                checksum_sha256=hashlib.sha256(first_data).hexdigest(),
                before_publish=hold_before_publish,
                create_only=True,
            ),
            first_results,
            Event(),
        ),
        daemon=True,
    )
    second_thread = Thread(
        target=_record_operation,
        args=(
            lambda: write_create_only(second, data=second_data),
            second_results,
            second_done,
        ),
        daemon=True,
    )
    try:
        first_thread.start()
        assert entered.wait(5)
        second_thread.start()
        assert second_done.wait(5)
        conflict = second_results.get_nowait()
        assert isinstance(conflict, MediaConflict)
    finally:
        release.set()
        first_thread.join(timeout=5)
        if second_thread.ident is not None:
            second_thread.join(timeout=5)
        assert not first_thread.is_alive() and not second_thread.is_alive()

    winner = first_results.get_nowait()
    assert not isinstance(winner, BaseException)
    assert first.read(KEY) == first_data
    assert second.read(KEY) == first_data


def test_create_only_rejects_non_boolean_for_every_write_entry_point(tmp_path):
    adapter = store(tmp_path / "video-objects")
    write(adapter)
    destination = KEY + "/attempts/invalid/progressive.mp4"

    with pytest.raises(MediaStorageUnavailable, match="write contract"):
        adapter.put_stream(
            object_key=destination,
            chunks=iter((DATA,)),
            content_type="video/mp4",
            content_length=len(DATA),
            checksum_sha256=hashlib.sha256(DATA).hexdigest(),
            create_only=1,  # type: ignore[arg-type]
        )
    with pytest.raises(MediaStorageUnavailable, match="write contract"):
        adapter.put(
            object_key=destination,
            body=DATA,
            content_type="video/mp4",
            create_only=1,  # type: ignore[arg-type]
        )
    with pytest.raises(MediaStorageUnavailable, match="copy contract"):
        adapter.copy(
            source_key=KEY,
            destination_key=destination,
            content_type="video/mp4",
            create_only=1,  # type: ignore[arg-type]
        )
    assert adapter.head(destination) is None


def test_large_stream_is_bounded_and_requires_streaming_read(tmp_path):
    adapter = store(tmp_path / "video-objects")
    chunk = b"v" * CHUNK_BYTES
    digest = hashlib.sha256(chunk * 3).hexdigest()
    adapter.put_stream(
        object_key=KEY,
        chunks=iter((chunk, chunk, chunk)),
        content_type="video/mp4",
        content_length=3 * CHUNK_BYTES,
        checksum_sha256=digest,
    )
    with pytest.raises(MediaStorageUnavailable, match="streaming"):
        adapter.read(KEY)
    lengths = [len(part) for part in adapter.iter_range(KEY)]
    assert lengths == [CHUNK_BYTES] * 3
    assert adapter.read_prefix(KEY, max_bytes=CHUNK_BYTES + 1) == chunk + b"v"


@pytest.mark.parametrize(
    "chunks,length,digest",
    [
        ([b"short"], 6, hashlib.sha256(b"short").hexdigest()),
        ([b"too long"], 3, hashlib.sha256(b"too").hexdigest()),
        ([b"bytes"], 5, "a" * 64),
        ([b""], 1, "a" * 64),
        ([bytearray(b"x")], 1, "a" * 64),
        ([b"x" * (CHUNK_BYTES + 1)], CHUNK_BYTES + 1, "a" * 64),
    ],
)
def test_invalid_bytes_never_publish_or_leave_partial(tmp_path, chunks, length, digest):
    adapter = store(tmp_path / "video-objects")
    with pytest.raises(MediaStorageUnavailable):
        adapter.put_stream(
            object_key=KEY,
            chunks=chunks,
            content_type="video/mp4",
            content_length=length,
            checksum_sha256=digest,
        )
    assert adapter.head(KEY) is None
    assert not tuple(adapter.root.glob("*.part"))
    assert not tuple(adapter.root.glob("*.object"))


def test_cancelled_iterator_releases_reserved_file(tmp_path):
    adapter = store(tmp_path / "video-objects")

    def interrupted():
        yield b"abc"
        raise RuntimeError("synthetic disconnected upload")

    with pytest.raises(RuntimeError):
        adapter.put_stream(
            object_key=KEY,
            chunks=interrupted(),
            content_type="video/mp4",
            content_length=100,
            checksum_sha256="a" * 64,
        )
    assert not tuple(adapter.root.glob("*.part"))
    assert adapter.head(KEY) is None
    assert write(adapter).content_length == len(DATA)


def test_reservation_charges_incomplete_writes_before_consuming_input(tmp_path):
    adapter = store(tmp_path / "video-objects", max_object_bytes=100, max_store_bytes=4300)
    other = store(adapter.root, max_object_bytes=100, max_store_bytes=4300)
    second_key = KEY + "/attempts/other/video.mp4"

    def first():
        assert tuple(adapter.root.glob("*.part"))[0].stat().st_size == 4196
        with pytest.raises(MediaStorageUnavailable, match="full"):
            write(other, key=second_key, data=b"v" * 100)
        assert other.head(KEY) is None
        yield b"v" * 100

    adapter.put_stream(
        object_key=KEY,
        chunks=first(),
        content_type="video/mp4",
        content_length=100,
        checksum_sha256=hashlib.sha256(b"v" * 100).hexdigest(),
    )
    assert adapter.read(KEY) == b"v" * 100


def test_crash_leftovers_remain_charged_not_automatically_deleted(tmp_path):
    adapter = store(tmp_path / "video-objects", max_object_bytes=100, max_store_bytes=4300)
    leftover = adapter.root / f"{uuid4().hex}.part"
    leftover.write_bytes(b"x" * 4196)
    restarted = store(adapter.root, max_object_bytes=100, max_store_bytes=4300)
    with pytest.raises(MediaStorageUnavailable, match="full"):
        write(restarted, data=b"x" * 100)
    assert leftover.exists()
    assert restarted.head(KEY) is None


@pytest.mark.parametrize(
    "key",
    [
        "../secret",
        KEY + "/../bad",
        KEY + "/x/../../bad",
        KEY.replace("video", "avatar"),
        KEY + "/bad\\path",
        KEY + "/stream?token=x",
        KEY + "/bad.",
        KEY + "/double//part",
        KEY.upper(),
        "",
        None,
    ],
)
def test_namespace_rejected(tmp_path, key):
    adapter = store(tmp_path / "video-objects")
    with pytest.raises(MediaStorageUnavailable):
        adapter.head(key)
    assert adapter.list_prefix(key) == ()


@pytest.mark.parametrize(
    "kwargs",
    [
        {"max_object_bytes": True},
        {"max_object_bytes": 0},
        {"max_store_bytes": 100},
        {"max_objects": False},
        {"max_objects": 0},
        {"max_objects": 65537},
    ],
)
def test_invalid_limits_rejected(tmp_path, kwargs):
    with pytest.raises(MediaStorageUnavailable):
        store(tmp_path / "video-objects", **kwargs)


def test_unmarked_nonempty_root_preserved(tmp_path):
    root = tmp_path / "video-objects"
    root.mkdir()
    existing = root / "personal-file.txt"
    existing.write_text("preserve")
    with pytest.raises(MediaStorageUnavailable, match="unmarked"):
        store(root)
    assert existing.read_text() == "preserve"


def test_corruption_rejected_after_cache_and_restart(tmp_path):
    adapter = store(tmp_path / "video-objects")
    write(adapter)
    with next(adapter.root.glob("*.object")).open("r+b") as stream:
        stream.seek(4096)
        stream.write(b"bad!")
    with pytest.raises(MediaStorageUnavailable, match="checksum"):
        adapter.head(KEY)
    with pytest.raises(MediaStorageUnavailable, match="checksum"):
        store(adapter.root).head(KEY)


@pytest.mark.parametrize("operation", ["head", "prefix", "range", "retry"])
def test_same_stat_identity_cannot_hide_changed_bytes(tmp_path, monkeypatch, operation):
    adapter = store(tmp_path / "video-objects")
    write(adapter)
    path = next(adapter.root.glob("*.object"))
    before = path.stat()
    identity = module._identity(before)
    # Model Windows' unchanged identity tuple independently of filesystem clock
    # resolution, but actually corrupt the file and preserve its size/mtime.
    monkeypatch.setattr(module, "_identity", lambda info: identity)
    assert adapter.head(KEY) is not None
    with path.open("r+b", buffering=0) as stream:
        stream.seek(4096)
        stream.write(b"bad!")
    os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))
    assert module._identity(path.stat()) == identity
    with pytest.raises(MediaStorageUnavailable, match="checksum"):
        if operation == "head":
            adapter.head(KEY)
        elif operation == "prefix":
            adapter.read_prefix(KEY)
        elif operation == "range":
            list(adapter.iter_range(KEY, start=0, end=7))
        else:
            write(adapter)


class _ControlledFile:
    """Alter only a real file's write/truncate operations for failure tests."""

    def __init__(self, stream, *, write=None, truncate=None):
        self.stream, self.write_override, self.truncate_override = stream, write, truncate

    def __getattr__(self, name):
        return getattr(self.stream, name)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return self.stream.__exit__(*args)

    def write(self, data):
        return self.write_override(self.stream, data)

    def truncate(self, size):
        if self.truncate_override is not None:
            return self.truncate_override(self.stream, size)
        return self.stream.truncate(size)


def test_short_writes_finish_marker_header_and_payload_on_real_disk(tmp_path, monkeypatch):
    original_open = Path.open
    writes = []

    def open_file(path, mode="r", *args, **kwargs):
        stream = original_open(path, mode, *args, **kwargs)
        if mode not in {"xb", "r+b"}:
            return stream

        def short_write(target, data):
            actual = target.write(data[:7])
            writes.append((path.name, len(data), actual))
            return actual

        return _ControlledFile(stream, write=short_write)

    monkeypatch.setattr(Path, "open", open_file)
    adapter = store(tmp_path / "video-objects")
    metadata = write(adapter)
    assert adapter.read(KEY) == DATA
    assert store(adapter.root).head(KEY) == metadata
    assert any(
        name == ".video-store-v1" and requested > actual for name, requested, actual in writes
    )
    assert any(requested == 4096 and actual == 7 for _, requested, actual in writes)
    assert any(requested == 37 and actual == 7 for _, requested, actual in writes)
    assert not tuple(adapter.root.glob("*.part"))


@pytest.mark.parametrize("returned", [0, None, -1, True])
def test_nonprogressing_writes_never_publish_and_release_reservation(
    tmp_path, monkeypatch, returned
):
    adapter = store(tmp_path / "video-objects")
    original_open = Path.open

    def open_file(path, mode="r", *args, **kwargs):
        stream = original_open(path, mode, *args, **kwargs)
        if path.suffix == ".part" and mode == "r+b":
            return _ControlledFile(stream, write=lambda target, data: returned)
        return stream

    with monkeypatch.context() as patch:
        patch.setattr(Path, "open", open_file)
        with pytest.raises(MediaStorageUnavailable, match="progress"):
            write(adapter)
    assert adapter.head(KEY) is None
    assert not tuple(adapter.root.glob("*.part"))
    assert write(adapter).content_length == len(DATA)


@pytest.mark.parametrize("stage", ["payload", "header", "fsync", "link"])
def test_io_failures_clean_only_this_attempt_and_allow_retry(tmp_path, monkeypatch, stage):
    adapter = store(tmp_path / "video-objects")
    preserved_key = KEY + "/attempts/preserved/video.mp4"
    write(adapter, key=preserved_key)
    original_open = Path.open

    def failing_write(target, data):
        if stage == "header" and target.tell() > 0:
            return target.write(data)
        target.write(data[:3])
        raise OSError("synthetic disk failure")

    def open_file(path, mode="r", *args, **kwargs):
        stream = original_open(path, mode, *args, **kwargs)
        if path.suffix == ".part" and mode == "r+b":
            return _ControlledFile(stream, write=failing_write)
        return stream

    def fail(*args):
        raise OSError("synthetic disk failure")

    with monkeypatch.context() as patch:
        if stage in {"payload", "header"}:
            patch.setattr(Path, "open", open_file)
        else:
            patch.setattr(os, stage, fail)
        with pytest.raises(MediaStorageUnavailable):
            write(adapter)
    assert adapter.head(KEY) is None
    assert not tuple(adapter.root.glob("*.part"))
    assert adapter.read(preserved_key) == DATA
    assert write(adapter).content_length == len(DATA)


def test_truncate_failure_removes_its_created_reservation(tmp_path, monkeypatch):
    adapter = store(tmp_path / "video-objects")
    original_open = Path.open

    def open_file(path, mode="r", *args, **kwargs):
        stream = original_open(path, mode, *args, **kwargs)
        if path.suffix != ".part" or mode != "xb":
            return stream

        def fail_truncate(target, size):
            target.truncate(17)
            raise OSError("synthetic reservation failure")

        return _ControlledFile(stream, truncate=fail_truncate)

    with monkeypatch.context() as patch:
        patch.setattr(Path, "open", open_file)
        with pytest.raises(MediaStorageUnavailable):
            write(adapter)
    assert not tuple(adapter.root.glob("*.part"))
    assert adapter.head(KEY) is None
    assert write(adapter).content_length == len(DATA)


def test_failed_exclusive_reservation_does_not_delete_existing_leftover(tmp_path, monkeypatch):
    adapter = store(tmp_path / "video-objects")
    identifier = uuid4()
    leftover = adapter.root / f"{identifier.hex}.part"
    leftover.write_bytes(b"preserve")
    monkeypatch.setattr(module, "uuid4", lambda: identifier)
    with pytest.raises(MediaStorageUnavailable):
        write(adapter)
    assert leftover.read_bytes() == b"preserve"
    assert adapter.head(KEY) is None


@pytest.mark.parametrize("content_type", [None, [], {}, 123, True])
def test_content_type_requires_a_string_before_reserving(tmp_path, content_type):
    adapter = store(tmp_path / "video-objects")
    with pytest.raises(MediaStorageUnavailable, match="contract"):
        adapter.put(object_key=KEY, body=DATA, content_type=content_type)
    assert not tuple(adapter.root.glob("*.part"))


def test_non_string_envelope_content_type_is_rejected(tmp_path):
    adapter = store(tmp_path / "video-objects")
    write(adapter)
    path = next(adapter.root.glob("*.object"))
    with path.open("r+b") as stream:
        header = json.loads(stream.read(4096))
        header["content_type"] = []
        stream.seek(0)
        stream.write(json.dumps(header).encode().ljust(4095, b" ") + b"\n")
    with pytest.raises(MediaStorageUnavailable, match="envelope"):
        adapter.head(KEY)


def test_read_detects_midstream_mutation(tmp_path):
    adapter = store(tmp_path / "video-objects")
    write(adapter)
    chunks = adapter.iter_range(KEY, chunk_size=16)
    assert next(chunks) == DATA[:16]
    with next(adapter.root.glob("*.object")).open("r+b") as stream:
        stream.seek(4096 + 32)
        stream.write(b"changed")
    with pytest.raises(MediaStorageUnavailable, match="changed"):
        next(chunks)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"start": -1},
        {"start": True},
        {"end": len(DATA)},
        {"end": -1},
        {"start": 5, "end": 2},
        {"chunk_size": 0},
        {"chunk_size": CHUNK_BYTES + 1},
        {"chunk_size": True},
    ],
)
def test_invalid_ranges_rejected(tmp_path, kwargs):
    adapter = store(tmp_path / "video-objects")
    write(adapter)
    with pytest.raises(MediaStorageUnavailable):
        list(adapter.iter_range(KEY, **kwargs))


_HELD_WRITE_SCRIPT = """
import hashlib
import sys
from pathlib import Path
from ac_platform.media.video_file_storage import CHUNK_BYTES, VideoFileStorage

root, key, encoded_data = sys.argv[1:]
data = bytes.fromhex(encoded_data)
adapter = VideoFileStorage(
    root=Path(root), max_object_bytes=8 * CHUNK_BYTES, max_store_bytes=16 * CHUNK_BYTES
)

def chunks():
    print("reserved", flush=True)
    if sys.stdin.readline() != "finish\\n":
        raise RuntimeError("The bounded test control message was not received.")
    yield data

result = adapter.put_stream(
    object_key=key,
    chunks=chunks(),
    content_type="video/mp4",
    content_length=len(data),
    checksum_sha256=hashlib.sha256(data).hexdigest(),
)
print(result.checksum_sha256, flush=True)
"""


def test_distinct_failed_writes_and_deletes_keep_at_most_256_lockfiles(tmp_path):
    adapter = store(tmp_path / "video-objects", max_objects=1)
    for index in range(260):
        key = KEY + f"/attempts/failed-{index}/video.mp4"
        if index % 2:
            adapter.delete(key)
            continue
        with pytest.raises(MediaStorageUnavailable):
            adapter.put_stream(
                object_key=key,
                chunks=(b"",),
                content_type="video/mp4",
                content_length=1,
                checksum_sha256="a" * 64,
            )
    locks = tuple(adapter.root.glob("*.lock"))
    assert 1 < len(locks) <= 256
    assert all(len(path.stem) == 2 and int(path.stem, 16) < 256 for path in locks)
    assert not tuple(adapter.root.glob("*.part"))
    assert not tuple(adapter.root.glob("*.object"))
    assert write(adapter).content_length == len(DATA)


def test_legacy_per_key_lockfiles_are_preserved_without_silent_migration(tmp_path):
    adapter = store(tmp_path / "video-objects")
    legacy = adapter.root / (hashlib.sha256(KEY.encode()).hexdigest() + ".lock")
    legacy.write_bytes(b"preserve")
    restarted = store(adapter.root)
    with pytest.raises(MediaStorageUnavailable, match="unexpected"):
        write(restarted)
    assert legacy.read_bytes() == b"preserve"


@pytest.mark.parametrize("same_key", [True, False], ids=["same-key", "same-stripe-cross-key"])
def test_separate_process_same_key_is_serialized_without_partial_exposure(tmp_path, same_key):
    adapter = store(tmp_path / "video-objects")
    stripe = hashlib.sha256(KEY.encode()).hexdigest()[:2]
    competing_key = (
        KEY
        if same_key
        else next(
            key
            for index in range(65536)
            if hashlib.sha256(
                (key := KEY + f"/attempts/collision-{index}/video.mp4").encode()
            ).hexdigest()[:2]
            == stripe
        )
    )
    # A standalone program imports only the installed application, not this
    # importlib-mode pytest module. This works for pytest and python -m pytest.
    with subprocess.Popen(  # noqa: S603 - fixed Python helper and bounded synthetic test inputs
        [sys.executable, "-c", _HELD_WRITE_SCRIPT, str(adapter.root), KEY, DATA.hex()],
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
            assert ready.get(timeout=15) == "reserved\n"
            assert adapter.head(KEY) is None
            assert adapter.head(competing_key) is None
            with pytest.raises((MediaConflict, MediaStorageUnavailable)):
                write(adapter, key=competing_key)
            with pytest.raises((MediaConflict, MediaStorageUnavailable)):
                adapter.delete(competing_key)
            output, error = worker.communicate("finish\n", timeout=15)
            assert worker.returncode == 0, error
            assert output.strip() == hashlib.sha256(DATA).hexdigest()
            assert adapter.read(KEY) == DATA
            assert write(adapter, key=competing_key).content_length == len(DATA)
        finally:
            if worker.poll() is None:
                worker.kill()
            worker.wait(timeout=5)
            reader.join(timeout=5)
            assert not reader.is_alive()


def _other_stripe_key():
    stripe = hashlib.sha256(KEY.encode()).hexdigest()[:2]
    return next(
        key
        for index in range(65536)
        if hashlib.sha256((key := KEY + f"/attempts/other-{index}/video.mp4").encode()).hexdigest()[
            :2
        ]
        != stripe
    )


def _record_operation(action, results, done):
    try:
        results.put(action())
    except BaseException as error:
        results.put(error)
    finally:
        done.set()


def test_publication_overlap_is_hidden_from_concurrent_exact_budget_scan(tmp_path, monkeypatch):
    adapter = store(
        tmp_path / "video-objects", max_object_bytes=100, max_store_bytes=8400, max_objects=2
    )
    other = store(adapter.root, max_object_bytes=100, max_store_bytes=8400, max_objects=2)
    second_key = _other_stripe_key()
    linked, release, scanning = Event(), Event(), Event()
    first_done, second_done = Event(), Event()
    first_results, second_results = Queue(), Queue()
    original_unlink, original_lock = Path.unlink, other._lock

    def paused_unlink(path, *args, **kwargs):
        if path.suffix == ".part" and current_thread().name == "video-publication":
            # The final hard link and its reservation coexist at this exact point.
            assert len(tuple(adapter.root.glob("*.object"))) == 1
            linked.set()
            assert release.wait(5)
        return original_unlink(path, *args, **kwargs)

    @contextmanager
    def observed_lock(name):
        if name == ".guard":
            scanning.set()
        with original_lock(name):
            yield

    monkeypatch.setattr(Path, "unlink", paused_unlink)
    monkeypatch.setattr(other, "_lock", observed_lock)
    first = Thread(
        target=_record_operation,
        args=(lambda: write(adapter, data=b"a" * 100), first_results, first_done),
        name="video-publication",
        daemon=True,
    )
    second = Thread(
        target=_record_operation,
        args=(lambda: write(other, key=second_key, data=b"b" * 100), second_results, second_done),
        daemon=True,
    )
    try:
        first.start()
        assert linked.wait(5)
        second.start()
        assert scanning.wait(5)
        assert not second_done.wait(0.1)
    finally:
        release.set()
        first.join(timeout=5)
        if second.ident is not None:
            second.join(timeout=5)
        assert not first.is_alive() and not second.is_alive()
    assert not isinstance(first_results.get_nowait(), BaseException)
    assert not isinstance(second_results.get_nowait(), BaseException)
    assert not tuple(adapter.root.glob("*.part"))
    objects = tuple(adapter.root.glob("*.object"))
    assert len(objects) == 2 and sum(path.stat().st_size for path in objects) == 8392
    assert adapter.read(KEY) == b"a" * 100
    assert other.read(second_key) == b"b" * 100


def test_failed_upload_cleanup_cannot_remove_a_reservation_during_budget_scan(
    tmp_path, monkeypatch
):
    adapter = store(
        tmp_path / "video-objects", max_object_bytes=100, max_store_bytes=8400, max_objects=2
    )
    other = store(adapter.root, max_object_bytes=100, max_store_bytes=8400, max_objects=2)
    second_key = _other_stripe_key()
    reserved, interrupt, scanning, release_scan, cleaning = (Event() for _ in range(5))
    first_done, second_done = Event(), Event()
    first_results, second_results = Queue(), Queue()
    original_check, original_lock = module._check_path, adapter._lock
    partials = []

    def interrupted_chunks():
        partials.extend(adapter.root.glob("*.part"))
        reserved.set()
        assert interrupt.wait(5)
        raise RuntimeError("synthetic original upload failure")
        yield b""  # pragma: no cover - define an iterator which fails before its first chunk

    def paused_check(path):
        if partials and path == partials[0] and current_thread().name == "video-budget-scan":
            scanning.set()
            assert release_scan.wait(5)
        return original_check(path)

    @contextmanager
    def observed_lock(name):
        if name == ".guard" and interrupt.is_set():
            cleaning.set()
        with original_lock(name):
            yield

    monkeypatch.setattr(module, "_check_path", paused_check)
    monkeypatch.setattr(adapter, "_lock", observed_lock)
    first = Thread(
        target=_record_operation,
        args=(
            lambda: adapter.put_stream(
                object_key=KEY,
                chunks=interrupted_chunks(),
                content_type="video/mp4",
                content_length=100,
                checksum_sha256="a" * 64,
            ),
            first_results,
            first_done,
        ),
        daemon=True,
    )
    second = Thread(
        target=_record_operation,
        args=(lambda: write(other, key=second_key, data=b"b" * 100), second_results, second_done),
        name="video-budget-scan",
        daemon=True,
    )
    try:
        first.start()
        assert reserved.wait(5)
        second.start()
        assert scanning.wait(5)
        interrupt.set()
        assert cleaning.wait(5)
        assert not first_done.wait(0.1)
        assert partials[0].stat().st_size == 4196
    finally:
        interrupt.set()
        release_scan.set()
        first.join(timeout=5)
        if second.ident is not None:
            second.join(timeout=5)
        assert not first.is_alive() and not second.is_alive()
    failure = first_results.get_nowait()
    assert isinstance(failure, RuntimeError)
    assert str(failure) == "synthetic original upload failure"
    assert not isinstance(second_results.get_nowait(), BaseException)
    assert not tuple(adapter.root.glob("*.part"))
    objects = tuple(adapter.root.glob("*.object"))
    assert len(objects) == 1 and objects[0].stat().st_size == 4196
    assert adapter.head(KEY) is None
    assert other.read(second_key) == b"b" * 100


def test_bounded_cleanup_guard_timeout_preserves_original_failure_and_charged_part(
    tmp_path, monkeypatch
):
    adapter = store(tmp_path / "video-objects", max_object_bytes=100, max_store_bytes=4300)
    other = store(adapter.root, max_object_bytes=100, max_store_bytes=4300)
    locked, release, done = Event(), Event(), Event()
    results = Queue()
    monkeypatch.setattr(module, "_GUARD_WAIT_SECONDS", 0.05)
    monkeypatch.setattr(module, "_GUARD_RETRY_SECONDS", 0.005)

    def hold_guard():
        with other._lock(".guard"):
            locked.set()
            assert release.wait(5)

    holder = Thread(target=_record_operation, args=(hold_guard, results, done), daemon=True)

    def interrupted_chunks():
        holder.start()
        assert locked.wait(5)
        raise RuntimeError("synthetic original upload failure")
        yield b""  # pragma: no cover

    try:
        with pytest.raises(RuntimeError, match="synthetic original upload failure") as caught:
            adapter.put_stream(
                object_key=KEY,
                chunks=interrupted_chunks(),
                content_type="video/mp4",
                content_length=100,
                checksum_sha256="a" * 64,
            )
        assert caught.value.__notes__ == [
            "An incomplete private video reservation remains charged."
        ]
        assert not done.is_set()
    finally:
        release.set()
        if holder.ident is not None:
            holder.join(timeout=5)
        assert not holder.is_alive()
    assert results.get_nowait() is None
    parts = tuple(adapter.root.glob("*.part"))
    assert len(parts) == 1 and parts[0].stat().st_size == 4196
    assert adapter.head(KEY) is None
    with pytest.raises(MediaStorageUnavailable, match="full"):
        write(other, key=_other_stripe_key(), data=b"b" * 100)
    assert parts[0].stat().st_size == 4196


def test_no_upload_url_or_malware_readiness_is_issued(tmp_path):
    adapter = store(tmp_path / "video-objects")
    assert isinstance(adapter, PrivateObjectStorage)
    with pytest.raises(MediaStorageUnavailable):
        adapter.create_upload_intent(
            object_key=KEY,
            content_type="video/mp4",
            content_length=len(DATA),
            checksum_sha256=hashlib.sha256(DATA).hexdigest(),
            expires_at=datetime.now(UTC),
        )
