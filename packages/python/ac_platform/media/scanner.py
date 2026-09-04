"""Quarantine and content-inspection port."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Protocol

from ac_platform.media.errors import MediaScannerUnavailable
from ac_platform.media.storage import PrivateObjectStorage


@dataclass(frozen=True, slots=True)
class ScanResult:
    clean: bool
    reason_code: str | None = None
    verified_checksum_sha256: str | None = None


class ContentScanner(Protocol):
    def scan(
        self,
        *,
        storage: PrivateObjectStorage,
        object_key: str,
        declared_content_type: str,
        content_length: int,
        checksum_sha256: str | None,
    ) -> ScanResult: ...


class FailClosedScanner:
    def scan(self, **kwargs: object) -> ScanResult:
        del kwargs
        return ScanResult(False, "SCANNER_NOT_CONFIGURED")


class SignatureContentScanner:
    """Small deterministic inspector for tests/local verification only."""

    def scan(
        self,
        *,
        storage: PrivateObjectStorage,
        object_key: str,
        declared_content_type: str,
        content_length: int,
        checksum_sha256: str | None,
    ) -> ScanResult:
        if content_length <= 0:
            return ScanResult(False, "EMPTY_OBJECT")
        try:
            metadata = storage.head(object_key)
            prefix = storage.read_prefix(object_key)
        except Exception as error:
            raise MediaScannerUnavailable(
                "The media scanner could not read the quarantined object."
            ) from error
        if metadata is None or metadata.content_length != content_length:
            return ScanResult(False, "OBJECT_METADATA_MISMATCH")
        provider_checksum = metadata.checksum_sha256.lower()
        if checksum_sha256 and provider_checksum and checksum_sha256.lower() != provider_checksum:
            return ScanResult(False, "CHECKSUM_MISMATCH")
        detected = self._detect(prefix, declared_content_type)
        if detected != declared_content_type:
            return ScanResult(False, "MIME_SNIFF_MISMATCH")
        if checksum_sha256:
            digest = checksum_sha256
        elif provider_checksum:
            digest = provider_checksum
        elif content_length == len(prefix):
            digest = hashlib.sha256(prefix).hexdigest()
        else:
            digest = None
        if not digest or not re.fullmatch(r"[0-9a-fA-F]{64}", digest):
            return ScanResult(False, "CHECKSUM_REQUIRED")
        # The storage adapter is the byte-integrity authority; scanner proof
        # binds its clean verdict to the checksum presented by the service.
        return ScanResult(True, verified_checksum_sha256=digest.lower())

    @staticmethod
    def _detect(prefix: bytes, declared: str) -> str | None:
        if prefix.startswith(b"\x89PNG\r\n\x1a\n"):
            return "image/png"
        if prefix.startswith(b"\xff\xd8\xff"):
            return "image/jpeg"
        if prefix[:4] == b"RIFF" and prefix[8:12] == b"WEBP":
            return "image/webp"
        if prefix.startswith(b"%PDF-"):
            return "application/pdf"
        if prefix.startswith(b"PK\x03\x04"):
            return "application/zip"
        if len(prefix) >= 8 and prefix[4:8] == b"ftyp":
            return "video/mp4"
        if prefix.startswith(b"\x1a\x45\xdf\xa3"):
            return "video/webm"
        if declared in {"text/plain", "text/vtt", "application/json"}:
            try:
                prefix.decode("utf-8")
            except UnicodeDecodeError:
                return None
            return declared
        return None


LocalContentScanner = SignatureContentScanner


__all__ = [
    "ContentScanner",
    "FailClosedScanner",
    "LocalContentScanner",
    "ScanResult",
    "SignatureContentScanner",
]
