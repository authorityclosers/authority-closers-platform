"""Explicit, bounded local clamd INSTREAM adapter; never selected by default.

Deployment prerequisites (not established by an INSTREAM verdict): a trusted
daemon/socket, maintained signatures, AlertExceedsMax enabled, and StreamMaxLength,
MaxFileSize and MaxScanSize compatible with the admitted source size. Clamd can
silently skip content under an unsafe engine configuration. Runtime composition
must verify that policy separately; this module does not activate/configure clamd.

Protocol: https://docs.clamav.net/manual/Usage/ClamdProtocol.html
Limits: https://docs.clamav.net/manual/Usage/Scanning.html
Storage calls must themselves have bounded I/O. The synchronous storage port
cannot cancel a blocked iterator; the deadline is checked around every operation.
"""

from __future__ import annotations

import hashlib
import ipaddress
import math
import re
import socket
import struct
import time
from contextlib import closing
from dataclasses import dataclass
from pathlib import PurePosixPath

from ac_platform.media.errors import MediaScannerUnavailable
from ac_platform.media.scanner import ScanResult, SignatureContentScanner
from ac_platform.media.storage import PrivateObjectStorage, StoredObjectMetadata
from ac_platform.media.studio_video_limits import STUDIO_VIDEO_MAX_SOURCE_BYTES

_MIB = 1024 * 1024
_SHA256 = re.compile(r"[0-9a-fA-F]{64}")
_FOUND = re.compile(rb"stream: ([\x20-\x7e]{1,1024}) FOUND\x00")
_UNAVAILABLE = "The media safety scanner could not verify the quarantined object."


@dataclass(frozen=True, slots=True)
class ClamAVScannerConfig:
    """Trusted composition settings, not user-supplied endpoints or policy proof."""

    unix_socket: str | None = None
    host: str | None = None
    port: int = 3310
    max_content_bytes: int = STUDIO_VIDEO_MAX_SOURCE_BYTES
    chunk_size: int = 64 * 1024
    max_response_bytes: int = 2048
    connect_timeout_seconds: float = 5.0
    io_timeout_seconds: float = 15.0
    verdict_timeout_seconds: float = 1200.0
    total_timeout_seconds: float = 120.0

    def __post_init__(self) -> None:
        if (self.unix_socket is None) == (self.host is None):
            raise ValueError("Configure exactly one local ClamAV endpoint.")
        if self.unix_socket is not None and (
            not isinstance(self.unix_socket, str)
            or not PurePosixPath(self.unix_socket).is_absolute()
            or self.unix_socket.startswith("//")
            or ".." in PurePosixPath(self.unix_socket).parts
            or any(ord(character) < 32 or ord(character) == 127 for character in self.unix_socket)
            or len(self.unix_socket.encode("utf-8")) > 103
        ):
            raise ValueError("The ClamAV Unix socket must be a bounded absolute local path.")
        if self.host is not None:
            try:
                address = ipaddress.ip_address(self.host)
            except ValueError:
                raise ValueError("ClamAV TCP requires a literal loopback address.") from None
            # Some Python patches classify IPv4-mapped IPv6 as loopback. Keep
            # the endpoint policy explicit: native IPv4 or IPv6 loopback only.
            if (
                not isinstance(self.host, str)
                or not address.is_loopback
                or (isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None)
                or "%" in self.host
            ):
                raise ValueError("ClamAV TCP requires a literal loopback address.")
        for value, maximum in (
            (self.port, 65535),
            # ClamAV cannot scan an individual file >= 2 GiB reliably.
            (self.max_content_bytes, 2**31 - 1),
            (self.chunk_size, _MIB),
            (self.max_response_bytes, 64 * 1024),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= maximum:
                raise ValueError("ClamAV size and port bounds must be positive bounded integers.")
        for timeout in (
            self.connect_timeout_seconds,
            self.io_timeout_seconds,
            self.verdict_timeout_seconds,
            self.total_timeout_seconds,
        ):
            if (
                isinstance(timeout, bool)
                or not isinstance(timeout, (int, float))
                or not math.isfinite(timeout)
                or not 0 < timeout <= 3600
            ):
                raise ValueError("ClamAV timeouts must be finite and between zero and one hour.")


class _Rejected(Exception):
    pass


def _remaining(deadline: float, timeout: float) -> float:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError
    return min(remaining, timeout)


def _connect(config: ClamAVScannerConfig, deadline: float) -> socket.socket:
    if config.unix_socket is not None:
        unix_family = getattr(socket, "AF_UNIX", None)
        if unix_family is None:
            raise OSError("Unix sockets are unavailable on this platform.")
        connection = socket.socket(unix_family, socket.SOCK_STREAM)
        endpoint: str | tuple[str, int] = config.unix_socket
    else:
        assert config.host is not None
        address = ipaddress.ip_address(config.host)
        connection = socket.socket(
            socket.AF_INET if address.version == 4 else socket.AF_INET6, socket.SOCK_STREAM
        )
        endpoint = (str(address), config.port)
    try:
        connection.settimeout(_remaining(deadline, config.connect_timeout_seconds))
        connection.connect(endpoint)
        return connection
    except Exception:
        connection.close()
        raise


def _mime(value: str) -> str:
    return value.lower().split(";", 1)[0].strip()


def _metadata(
    metadata: StoredObjectMetadata | None,
    *,
    object_key: str,
    declared_content_type: str,
    content_length: int,
    checksum_sha256: str | None,
) -> StoredObjectMetadata:
    if (
        metadata is None
        or metadata.object_key != object_key
        or not isinstance(metadata.content_type, str)
        or _mime(metadata.content_type) != declared_content_type
        or isinstance(metadata.content_length, bool)
        or not isinstance(metadata.content_length, int)
        or metadata.content_length != content_length
        or not isinstance(metadata.storage_version_id, str)
        or not 1 <= len(metadata.storage_version_id) <= 255
        or not isinstance(metadata.checksum_sha256, str)
        or _SHA256.fullmatch(metadata.checksum_sha256) is None
    ):
        raise _Rejected("OBJECT_METADATA_MISMATCH")
    if checksum_sha256 is not None and (
        not isinstance(checksum_sha256, str)
        or _SHA256.fullmatch(checksum_sha256) is None
        or checksum_sha256.lower() != metadata.checksum_sha256.lower()
    ):
        raise _Rejected("CHECKSUM_MISMATCH")
    return metadata


class ClamAVContentScanner:
    """Checks real clamd verdicts plus source integrity; no configured default.

    A clean result is neither provider approval nor a guarantee against all
    malware. Composition must enforce the daemon policy described above.
    """

    def __init__(self, config: ClamAVScannerConfig | None = None) -> None:
        self._config = config

    def scan(
        self,
        *,
        storage: PrivateObjectStorage,
        object_key: str,
        declared_content_type: str,
        content_length: int,
        checksum_sha256: str | None,
    ) -> ScanResult:
        config = self._config
        if config is None:
            return ScanResult(False, "SCANNER_NOT_CONFIGURED")
        try:
            if isinstance(content_length, bool) or not isinstance(content_length, int):
                raise _Rejected("OBJECT_METADATA_MISMATCH")
            if content_length <= 0:
                raise _Rejected("EMPTY_OBJECT")
            if content_length > config.max_content_bytes:
                raise _Rejected("SCANNER_CONTENT_TOO_LARGE")
            if not isinstance(declared_content_type, str) or not _mime(declared_content_type):
                raise _Rejected("MIME_SNIFF_MISMATCH")
            declared = _mime(declared_content_type)
            deadline = time.monotonic() + config.total_timeout_seconds
            before = _metadata(
                storage.head(object_key),
                object_key=object_key,
                declared_content_type=declared,
                content_length=content_length,
                checksum_sha256=checksum_sha256,
            )
            _remaining(deadline, config.io_timeout_seconds)
            with closing(_connect(config, deadline)) as connection:
                self._send(connection, b"zINSTREAM\0", deadline, config)
                digest = hashlib.sha256()
                consumed = 0
                prefix = bytearray()
                chunks = storage.iter_range(
                    object_key, start=0, end=None, chunk_size=config.chunk_size
                )
                try:
                    for chunk in chunks:
                        _remaining(deadline, config.io_timeout_seconds)
                        if not isinstance(chunk, bytes) or not 1 <= len(chunk) <= config.chunk_size:
                            raise _Rejected("OBJECT_STREAM_INVALID")
                        consumed += len(chunk)
                        if consumed > content_length:
                            raise _Rejected("OBJECT_METADATA_MISMATCH")
                        digest.update(chunk)
                        if len(prefix) < 512:
                            prefix.extend(chunk[: 512 - len(prefix)])
                        self._send(connection, struct.pack(">I", len(chunk)), deadline, config)
                        self._send(connection, chunk, deadline, config)
                finally:
                    close = getattr(chunks, "close", None)
                    if callable(close):
                        close()
                if consumed != content_length:
                    raise _Rejected("OBJECT_METADATA_MISMATCH")
                checksum = digest.hexdigest()
                if checksum != before.checksum_sha256.lower():
                    raise _Rejected("CHECKSUM_MISMATCH")
                # Reuse only the deterministic MIME prefix detector, never its
                # test-only clean verdict. Malware detection comes from clamd.
                if SignatureContentScanner._detect(bytes(prefix), declared) != declared:
                    raise _Rejected("MIME_SNIFF_MISMATCH")
                self._send(connection, b"\0\0\0\0", deadline, config)
                response = bytearray()
                # The daemon scans after INSTREAM finishes. Its verdict budget
                # is independent of short per-chunk writes, but never extends
                # the absolute scan deadline or resets on a partial reply.
                verdict_deadline = min(deadline, time.monotonic() + config.verdict_timeout_seconds)
                while True:
                    connection.settimeout(
                        _remaining(verdict_deadline, config.verdict_timeout_seconds)
                    )
                    part = connection.recv(min(4096, config.max_response_bytes + 1 - len(response)))
                    if not part:
                        break
                    response.extend(part)
                    if len(response) > config.max_response_bytes:
                        raise MediaScannerUnavailable(_UNAVAILABLE)
                # A non-session command ends at EOF, not just the first OK.
                # This rejects additional, contradictory or truncated records.
                if bytes(response) != b"stream: OK\0":
                    found = _FOUND.fullmatch(response)
                    if found:
                        reason = (
                            "SCANNER_SCAN_LIMIT_EXCEEDED"
                            if found[1].startswith(b"Heuristics.Limits.Exceeded")
                            else "MALWARE_DETECTED"
                        )
                        raise _Rejected(reason)
                    raise MediaScannerUnavailable(_UNAVAILABLE)
                if storage.head(object_key) != before:
                    raise _Rejected("SOURCE_REVISION_CHANGED")
                _remaining(deadline, config.io_timeout_seconds)
                return ScanResult(True, verified_checksum_sha256=checksum)
        except _Rejected as error:
            return ScanResult(False, str(error))
        except Exception:
            # Neither provider exceptions nor daemon text may expose object
            # keys, paths, endpoints or raw signature/error strings to callers.
            raise MediaScannerUnavailable(_UNAVAILABLE) from None

    @staticmethod
    def _send(
        connection: socket.socket, data: bytes, deadline: float, config: ClamAVScannerConfig
    ) -> None:
        connection.settimeout(_remaining(deadline, config.io_timeout_seconds))
        connection.sendall(data)


__all__ = ["ClamAVContentScanner", "ClamAVScannerConfig"]
