from __future__ import annotations

import hashlib
import socket
import struct
import time
from collections.abc import Iterator
from dataclasses import replace
from threading import Thread
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from ac_platform.media import clamav_scanner as module
from ac_platform.media.clamav_scanner import ClamAVContentScanner, ClamAVScannerConfig
from ac_platform.media.errors import MediaScannerUnavailable
from ac_platform.media.scanner import ContentScanner, ScanResult
from ac_platform.media.signing import MediaSigner
from ac_platform.media.storage import InMemoryPrivateObjectStorage, StoredObjectMetadata

KEY = "tenants/example/media/video/asset/version/original"
MP4 = b"\x00\x00\x00\x18ftypmp42" + b"video" * 37


class FakeSocket:
    def __init__(self, replies: list[bytes] | None = None) -> None:
        self.replies = list(replies if replies is not None else [b"stream: OK\0", b""])
        self.sent: list[bytes] = []
        self.timeouts: list[float] = []
        self.received_sizes: list[int] = []
        self.closed = False

    def settimeout(self, value: float) -> None:
        self.timeouts.append(value)

    def sendall(self, body: bytes) -> None:
        self.sent.append(body)

    def recv(self, length: int) -> bytes:
        self.received_sizes.append(length)
        if not self.replies:
            return b""
        item = self.replies.pop(0)
        if len(item) > length:
            self.replies.insert(0, item[length:])
        return item[:length]

    def close(self) -> None:
        self.closed = True


def storage_fixture(
    body: bytes = MP4,
) -> tuple[InMemoryPrivateObjectStorage, StoredObjectMetadata]:
    storage = InMemoryPrivateObjectStorage(MediaSigner("clamav-unit-test-signing-key-32-bytes"))
    metadata = storage.put(object_key=KEY, body=body, content_type="video/mp4")
    return storage, metadata


def scan(
    scanner: ContentScanner,
    storage: InMemoryPrivateObjectStorage,
    metadata: StoredObjectMetadata,
) -> ScanResult:
    return scanner.scan(
        storage=storage,
        object_key=KEY,
        declared_content_type="video/mp4",
        content_length=metadata.content_length,
        checksum_sha256=metadata.checksum_sha256,
    )


@pytest.fixture
def connection(monkeypatch: pytest.MonkeyPatch) -> FakeSocket:
    connection = FakeSocket()
    monkeypatch.setattr(module, "_connect", Mock(return_value=connection))
    return connection


def scanner(**changes: object) -> ClamAVContentScanner:
    config = ClamAVScannerConfig(host="127.0.0.1")
    return ClamAVContentScanner(replace(config, **changes))  # type: ignore[arg-type]


def test_default_scanner_is_disabled_without_touching_storage_or_network(
    connection: FakeSocket,
) -> None:
    storage, metadata = storage_fixture()
    storage.head = Mock(side_effect=AssertionError("disabled"))  # type: ignore[method-assign]
    assert scan(ClamAVContentScanner(), storage, metadata) == ScanResult(
        False, "SCANNER_NOT_CONFIGURED"
    )
    assert not connection.sent


def test_streams_exact_framed_bytes_with_bounded_chunks_and_verified_digest(
    connection: FakeSocket,
) -> None:
    body = MP4 + b"x" * (3 * 1024 * 1024)
    storage, metadata = storage_fixture(body)
    storage.read = Mock(side_effect=AssertionError("unbounded read"))  # type: ignore[method-assign]
    storage.read_prefix = Mock(side_effect=AssertionError("separate prefix"))  # type: ignore[method-assign]
    stream = Mock(wraps=storage.iter_range)
    storage.iter_range = stream  # type: ignore[method-assign]
    assert scan(scanner(), storage, metadata) == ScanResult(
        True, verified_checksum_sha256=hashlib.sha256(body).hexdigest()
    )
    stream.assert_called_once_with(KEY, start=0, end=None, chunk_size=64 * 1024)
    assert connection.sent[0] == b"zINSTREAM\0"
    assert connection.sent[-1] == b"\0\0\0\0"
    digest = hashlib.sha256()
    for index in range(1, len(connection.sent) - 1, 2):
        chunk = connection.sent[index + 1]
        assert 1 <= len(chunk) <= 64 * 1024
        assert connection.sent[index] == struct.pack(">I", len(chunk))
        digest.update(chunk)
    assert digest.hexdigest() == metadata.checksum_sha256
    assert KEY.encode() not in b"".join(connection.sent)
    assert connection.closed
    assert max(connection.received_sizes) <= 2049


@pytest.mark.parametrize(
    "change",
    [
        {"object_key": "different"},
        {"content_type": "image/png"},
        {"content_type": None},
        {"content_length": True},
        {"content_length": 1.5},
        {"content_length": len(MP4) + 1},
        {"checksum_sha256": ""},
        {"checksum_sha256": "invalid"},
        {"storage_version_id": ""},
        {"storage_version_id": "x" * 256},
        {"storage_version_id": None},
    ],
)
def test_rejects_metadata_before_connecting(
    connection: FakeSocket, change: dict[str, object]
) -> None:
    storage, metadata = storage_fixture()
    storage.head = Mock(return_value=replace(metadata, **change))  # type: ignore[method-assign, arg-type]
    assert not scan(scanner(), storage, metadata).clean
    assert not connection.sent


@pytest.mark.parametrize("length", [129, 255])
def test_accepts_normalized_mime_case_checksum_and_existing_revision_lengths(
    connection: FakeSocket, length: int
) -> None:
    storage, metadata = storage_fixture()
    metadata = replace(
        metadata,
        content_type=" Video/MP4; codecs=avc1",
        checksum_sha256=metadata.checksum_sha256.upper(),
        storage_version_id="r" * length,
    )
    storage.head = Mock(return_value=metadata)  # type: ignore[method-assign]
    assert scan(scanner(), storage, metadata).clean


@pytest.mark.parametrize("length", [0, -1, True, 1.2, 101 * 1024 * 1024])
def test_invalid_and_oversize_lengths_never_start_storage_or_transport(
    connection: FakeSocket, length: int
) -> None:
    storage, metadata = storage_fixture()
    storage.head = Mock(side_effect=AssertionError("must not read"))  # type: ignore[method-assign]
    assert not scan(scanner(), storage, replace(metadata, content_length=length)).clean
    assert not connection.sent


@pytest.mark.parametrize("checksum", ["a" * 64, "invalid", ""])
def test_rejects_declared_checksum_mismatch_before_connecting(
    connection: FakeSocket, checksum: str
) -> None:
    storage, metadata = storage_fixture()
    assert scan(scanner(), storage, replace(metadata, checksum_sha256=checksum)).reason_code == (
        "CHECKSUM_MISMATCH"
    )
    assert not connection.sent


@pytest.mark.parametrize(
    "chunks,reason",
    [
        ([MP4[:-1]], "OBJECT_METADATA_MISMATCH"),
        ([MP4 + b"x"], "OBJECT_METADATA_MISMATCH"),
        ([MP4, b"x"], "OBJECT_METADATA_MISMATCH"),
        ([MP4[:-1] + b"x"], "CHECKSUM_MISMATCH"),
        ([b""], "OBJECT_STREAM_INVALID"),
        (["not bytes"], "OBJECT_STREAM_INVALID"),
        ([b"x" * (64 * 1024 + 1)], "OBJECT_STREAM_INVALID"),
    ],
)
def test_fails_closed_on_invalid_streams_and_closes_iterator(
    connection: FakeSocket, chunks: list[bytes], reason: str
) -> None:
    storage, metadata = storage_fixture()
    closed: list[bool] = []

    def pieces() -> Iterator[bytes]:
        try:
            yield from chunks
        finally:
            closed.append(True)

    storage.iter_range = Mock(return_value=pieces())  # type: ignore[method-assign]
    assert scan(scanner(), storage, metadata).reason_code == reason
    assert closed == [True]
    assert connection.closed
    assert connection.sent[-1] != b"\0\0\0\0"


def test_rejects_mime_spoof_despite_a_clean_daemon(connection: FakeSocket) -> None:
    storage, metadata = storage_fixture(b"%PDF-1.7 document")
    assert scan(scanner(), storage, metadata).reason_code == "MIME_SNIFF_MISMATCH"
    assert connection.closed


@pytest.mark.parametrize("change", [{"storage_version_id": "new"}, {"content_type": "text/plain"}])
def test_rechecks_immutable_source_metadata_after_daemon_verdict(
    connection: FakeSocket, change: dict[str, object]
) -> None:
    storage, metadata = storage_fixture()
    storage.head = Mock(side_effect=[metadata, replace(metadata, **change)])  # type: ignore[method-assign, arg-type]
    assert scan(scanner(), storage, metadata).reason_code == "SOURCE_REVISION_CHANGED"


@pytest.mark.parametrize(
    "reply",
    [
        b"",
        b"stream: OK",
        b"stream: OK\n",
        b"OK\0",
        b"stream: OK\0garbage",
        b"stream: OK\0stream: Evil FOUND\0",
        b"stream: OK\0stream: OK\0",
        b"stream: ERROR\0",
        b"INSTREAM size limit exceeded. ERROR\0",
        b"stream: \xff FOUND\0",
        b"1: stream: OK\0",
        b"stream: OK\0" + b"x" * 4096,
    ],
)
def test_rejects_errors_truncation_ambiguity_and_overlong_replies(
    connection: FakeSocket, reply: bytes
) -> None:
    connection.replies = [reply, b""]
    storage, metadata = storage_fixture()
    with pytest.raises(MediaScannerUnavailable):
        scan(scanner(), storage, metadata)
    assert connection.closed


def test_fragmented_nul_reply_requires_eof(connection: FakeSocket) -> None:
    connection.replies = [b"st", b"ream:", b" OK", b"\0", b""]
    storage, metadata = storage_fixture()
    assert scan(scanner(), storage, metadata).clean


def test_ok_without_connection_end_is_not_a_complete_verdict(
    connection: FakeSocket, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        connection, "recv", Mock(side_effect=[b"stream: OK\0", TimeoutError("no EOF")])
    )
    storage, metadata = storage_fixture()
    with pytest.raises(MediaScannerUnavailable):
        scan(scanner(), storage, metadata)
    assert connection.closed


def test_hash_is_measured_when_caller_has_no_checksum(connection: FakeSocket) -> None:
    storage, metadata = storage_fixture()
    result = scanner().scan(
        storage=storage,
        object_key=KEY,
        declared_content_type=" VIDEO/MP4; codecs=avc1",
        content_length=metadata.content_length,
        checksum_sha256=None,
    )
    assert result == ScanResult(True, verified_checksum_sha256=hashlib.sha256(MP4).hexdigest())


@pytest.mark.parametrize(
    "reply,reason",
    [
        (b"stream: Win.Test.EICAR_HDB-1 FOUND\0", "MALWARE_DETECTED"),
        (b"stream: Heuristics.Limits.Exceeded.MaxFileSize FOUND\0", "SCANNER_SCAN_LIMIT_EXCEEDED"),
    ],
)
def test_never_promotes_malware_or_engine_limit_verdicts(
    connection: FakeSocket, reply: bytes, reason: str
) -> None:
    connection.replies = [reply, b""]
    storage, metadata = storage_fixture()
    assert scan(scanner(), storage, metadata) == ScanResult(False, reason)


@pytest.mark.parametrize("operation", ["connect", "head", "stream", "send", "recv"])
def test_transport_failures_are_sanitized_and_never_clean(
    connection: FakeSocket, monkeypatch: pytest.MonkeyPatch, operation: str
) -> None:
    storage, metadata = storage_fixture()
    failure = Mock(side_effect=TimeoutError("https://private.test/secret?token=do-not-expose"))
    if operation == "connect":
        monkeypatch.setattr(module, "_connect", failure)
    elif operation == "head":
        storage.head = failure  # type: ignore[method-assign]
    elif operation == "stream":
        storage.iter_range = failure  # type: ignore[method-assign]
    elif operation == "send":
        monkeypatch.setattr(connection, "sendall", failure)
    else:
        monkeypatch.setattr(connection, "recv", failure)
    with pytest.raises(MediaScannerUnavailable) as caught:
        scan(scanner(), storage, metadata)
    assert "secret" not in str(caught.value)
    assert caught.value.__suppress_context__
    if operation not in {"connect", "head"}:
        assert connection.closed


def test_total_deadline_cannot_be_extended_by_dribbling_storage(
    connection: FakeSocket, monkeypatch: pytest.MonkeyPatch
) -> None:
    storage, metadata = storage_fixture()
    clock = [0.0]
    monkeypatch.setattr(module, "time", SimpleNamespace(monotonic=lambda: clock[0]))

    def pieces() -> Iterator[bytes]:
        yield MP4[:8]
        clock[0] = 2
        yield MP4[8:]

    storage.iter_range = Mock(return_value=pieces())  # type: ignore[method-assign]
    with pytest.raises(MediaScannerUnavailable):
        scan(scanner(total_timeout_seconds=1), storage, metadata)
    assert connection.closed
    assert max(connection.timeouts) <= 1


def test_stream_failure_after_some_bytes_is_not_eof(connection: FakeSocket) -> None:
    storage, metadata = storage_fixture()
    closed: list[bool] = []

    def pieces() -> Iterator[bytes]:
        try:
            yield MP4[:8]
            raise OSError("partial object")
        finally:
            closed.append(True)

    storage.iter_range = Mock(return_value=pieces())  # type: ignore[method-assign]
    with pytest.raises(MediaScannerUnavailable):
        scan(scanner(), storage, metadata)
    assert closed == [True]
    assert connection.closed


def test_total_deadline_cannot_be_extended_by_dribbling_responses(
    connection: FakeSocket, monkeypatch: pytest.MonkeyPatch
) -> None:
    storage, metadata = storage_fixture()
    clock = [0.0]
    monkeypatch.setattr(module, "time", SimpleNamespace(monotonic=lambda: clock[0]))

    def receive(length: int) -> bytes:
        assert length > 0
        clock[0] += 0.6
        return b"s"

    monkeypatch.setattr(connection, "recv", receive)
    with pytest.raises(MediaScannerUnavailable):
        scan(scanner(total_timeout_seconds=1), storage, metadata)
    assert connection.closed
    assert connection.timeouts[-1] == pytest.approx(0.4)


@pytest.mark.parametrize(
    "change",
    [
        {"host": "localhost"},
        {"host": "example.test"},
        {"host": "192.168.1.1"},
        {"host": "0.0.0.0"},  # noqa: S104 - rejected endpoint, never a bind target
        {"host": "::"},
        {"host": "::ffff:127.0.0.1"},
        {"host": "127.0.0.1:3310"},
        {"host": "http://127.0.0.1"},
        {"unix_socket": "/run/clamav.sock"},
        {"port": 0},
        {"port": True},
        {"port": 65536},
        {"max_content_bytes": 2**31},
        {"chunk_size": 1024 * 1024 + 1},
        {"max_response_bytes": 0},
        {"total_timeout_seconds": float("inf")},
        {"io_timeout_seconds": float("nan")},
        {"connect_timeout_seconds": 0},
    ],
)
def test_rejects_unsafe_endpoints_and_unbounded_settings(change: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        replace(ClamAVScannerConfig(host="127.0.0.1"), **change)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "path",
    ["relative.sock", "/../clamd.sock", "/run/clam\0.sock", "/" + "x" * 104, "//remote/clamd"],
)
def test_rejects_invalid_unix_socket_paths(path: str) -> None:
    with pytest.raises(ValueError):
        ClamAVScannerConfig(unix_socket=path)


def test_configuration_requires_an_explicit_endpoint() -> None:
    with pytest.raises(ValueError):
        ClamAVScannerConfig()


def test_unix_transport_uses_only_the_configured_local_socket(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = Mock(spec=socket.socket)
    factory = Mock(return_value=connection)
    monkeypatch.setattr(socket, "AF_UNIX", 1, raising=False)
    monkeypatch.setattr(socket, "socket", factory)
    config = ClamAVScannerConfig(unix_socket="/run/clamav/clamd.sock")
    assert module._connect(config, time.monotonic() + 10) is connection
    factory.assert_called_once_with(1, socket.SOCK_STREAM)
    connection.connect.assert_called_once_with("/run/clamav/clamd.sock")


def test_unix_transport_fails_closed_when_platform_does_not_support_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delattr(socket, "AF_UNIX", raising=False)
    config = ClamAVScannerConfig(unix_socket="/run/clamav/clamd.sock")
    with pytest.raises(OSError):
        module._connect(config, time.monotonic() + 10)


@pytest.mark.parametrize("host,family", [("127.0.0.1", socket.AF_INET), ("::1", socket.AF_INET6)])
def test_uses_literal_socket_connections_without_dns(
    monkeypatch: pytest.MonkeyPatch, host: str, family: socket.AddressFamily
) -> None:
    connection = Mock(spec=socket.socket)
    factory = Mock(return_value=connection)
    monkeypatch.setattr(socket, "socket", factory)
    monkeypatch.setattr(socket, "getaddrinfo", Mock(side_effect=AssertionError("no DNS")))
    config = ClamAVScannerConfig(host=host)
    assert module._connect(config, time.monotonic() + 10) is connection
    factory.assert_called_once_with(family, socket.SOCK_STREAM)
    connection.connect.assert_called_once_with((host, 3310))


def test_failed_connection_closes_socket(monkeypatch: pytest.MonkeyPatch) -> None:
    connection = Mock(spec=socket.socket)
    connection.connect.side_effect = OSError("unavailable")
    monkeypatch.setattr(socket, "socket", Mock(return_value=connection))
    with pytest.raises(OSError):
        module._connect(ClamAVScannerConfig(host="127.0.0.1"), time.monotonic() + 10)
    connection.close.assert_called_once()


def test_real_loopback_socket_streams_and_reads_fragmented_reply() -> None:
    """A bounded protocol peer, not a daemon/antivirus acceptance test."""
    storage, metadata = storage_fixture(MP4 + b"x" * 200_000)
    received: list[str] = []
    failures: list[Exception] = []
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        listener.settimeout(3)

        def serve() -> None:
            try:
                with listener.accept()[0] as peer:
                    peer.settimeout(3)

                    def exact(size: int) -> bytes:
                        value = bytearray()
                        while len(value) < size:
                            chunk = peer.recv(size - len(value))
                            if not chunk:
                                raise RuntimeError("truncated client frame")
                            value.extend(chunk)
                        return bytes(value)

                    assert exact(10) == b"zINSTREAM\0"
                    digest = hashlib.sha256()
                    while size := struct.unpack(">I", exact(4))[0]:
                        assert size <= 64 * 1024
                        digest.update(exact(size))
                    received.append(digest.hexdigest())
                    peer.sendall(b"stream:")
                    peer.sendall(b" OK\0")
            except Exception as error:
                failures.append(error)

        worker = Thread(target=serve)
        worker.start()
        try:
            result = scan(scanner(port=listener.getsockname()[1]), storage, metadata)
        finally:
            worker.join(timeout=4)
        assert not worker.is_alive()
        assert not failures
        assert received == [metadata.checksum_sha256]
        assert result.clean
