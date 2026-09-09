"""Real image sanitization for the explicit localhost demo, not malware attestation."""

from __future__ import annotations

import hashlib
import io
import threading
import warnings
from collections.abc import Iterable
from uuid import UUID

from PIL import Image, ImageOps, UnidentifiedImageError

from ac_platform.media.api_contracts import CropMetadata
from ac_platform.media.errors import MediaProcessingError, MediaQuotaExceeded
from ac_platform.media.local_avatar_storage import MAX_AVATAR_BYTES
from ac_platform.media.models import MediaPurpose
from ac_platform.media.processing import (
    CaptionPassthrough,
    ProcessedAvatarVariant,
    ProcessingResult,
)
from ac_platform.media.scanner import ScanResult
from ac_platform.media.storage import PrivateObjectStorage

MAX_IMAGE_PIXELS = 12_000_000
MAX_IMAGE_EDGE = 8192
MAX_VARIANT_BYTES = 2 * 1024 * 1024
_IMAGE_GATE = threading.BoundedSemaphore(1)
_FORMATS = {"JPEG": "image/jpeg", "PNG": "image/png", "WEBP": "image/webp"}


def decode_avatar(body: bytes, content_type: str) -> Image.Image:
    """Fully decode one still image, orient like browser display, strip metadata.

    Caller holds the one-image process gate. Header dimensions are checked
    before pixel allocation. Accepted inputs never become delivery objects.
    This rejects malformed/bomb/animated files; it is not antivirus approval.
    """
    if not 0 < len(body) <= MAX_AVATAR_BYTES:
        raise MediaProcessingError("The local profile image exceeds its byte limit.")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(body), formats=list(_FORMATS)) as probe:
                if (
                    _FORMATS.get(probe.format or "") != content_type
                    or probe.width <= 0
                    or probe.height <= 0
                    or max(probe.size) > MAX_IMAGE_EDGE
                    or probe.width * probe.height > MAX_IMAGE_PIXELS
                    or getattr(probe, "n_frames", 1) != 1
                ):
                    raise ValueError
                probe.verify()
            with Image.open(io.BytesIO(body), formats=list(_FORMATS)) as source:
                source.load()
                with ImageOps.exif_transpose(source) as oriented:
                    # New pixel container, no EXIF, ICC, XMP, comments or original bytes.
                    pixels = oriented.convert("RGBA")
                    pixels.info.clear()
                    return pixels
    except (
        OSError,
        ValueError,
        SyntaxError,
        UnidentifiedImageError,
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
    ) as error:
        raise MediaProcessingError(
            "The local profile image could not be decoded safely."
        ) from error


class LocalAvatarScanner:
    def scan(
        self,
        *,
        storage: PrivateObjectStorage,
        object_key: str,
        declared_content_type: str,
        content_length: int,
        checksum_sha256: str | None,
    ) -> ScanResult:
        if not _IMAGE_GATE.acquire(blocking=False):
            raise MediaQuotaExceeded("Another local profile image is being checked; retry shortly.")
        try:
            metadata = storage.head(object_key)
            if metadata is None or metadata.content_length != content_length:
                return ScanResult(False, "LOCAL_AVATAR_SIZE_MISMATCH")
            body = storage.read(object_key)
            digest = hashlib.sha256(body).hexdigest()
            if digest != checksum_sha256 or metadata.checksum_sha256 != digest:
                return ScanResult(False, "LOCAL_AVATAR_CHECKSUM_MISMATCH")
            try:
                with decode_avatar(body, declared_content_type):
                    pass
            except MediaProcessingError:
                return ScanResult(False, "LOCAL_AVATAR_DECODE_REJECTED")
            return ScanResult(True, verified_checksum_sha256=digest)
        finally:
            _IMAGE_GATE.release()


class LocalAvatarProcessor:
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
        del version_id
        if purpose is not MediaPurpose.AVATAR or tuple(captions):
            raise MediaProcessingError("The local image processor accepts only profile photos.")
        if not _IMAGE_GATE.acquire(blocking=False):
            raise MediaQuotaExceeded(
                "Another local profile image is being processed; retry shortly."
            )
        created: list[str] = []
        try:
            with decode_avatar(storage.read(source_key), content_type) as image:
                if crop is None:
                    edge = min(image.size)
                    left, top = (image.width - edge) / 2, (image.height - edge) / 2
                    box = (left, top, left + edge, top + edge)
                else:
                    parsed = CropMetadata.model_validate(crop)
                    if parsed.rotation_degrees != 0:
                        raise MediaProcessingError("Local profile crop rotation is not supported.")
                    width, height = parsed.width * image.width, parsed.height * image.height
                    if min(width, height) < 1 or abs(width - height) > 1:
                        raise MediaProcessingError(
                            "The profile crop must contain a square of pixels."
                        )
                    box = (
                        parsed.x * image.width,
                        parsed.y * image.height,
                        (parsed.x + parsed.width) * image.width,
                        (parsed.y + parsed.height) * image.height,
                    )
                variants: list[ProcessedAvatarVariant] = []
                total = 0
                for size in (128, 256, 512):
                    key = f"{source_key}/avatar/{size}"
                    if storage.head(key) is not None:
                        raise MediaProcessingError("The profile variant already exists.")
                    with image.resize((size, size), Image.Resampling.LANCZOS, box=box) as resized:
                        resized.info.clear()
                        output = io.BytesIO()
                        resized.save(output, format="WEBP", quality=88, method=4)
                        body = output.getvalue()
                    total += len(body)
                    if total > MAX_VARIANT_BYTES:
                        raise MediaQuotaExceeded("The profile variants exceed their byte quota.")
                    storage.put(object_key=key, body=body, content_type="image/webp")
                    created.append(key)
                    variants.append(
                        ProcessedAvatarVariant(
                            size_px=size, content_type="image/webp", object_key=key
                        )
                    )
                return ProcessingResult(
                    avatar_variants=tuple(variants),
                    object_keys=tuple(created),
                    width=512,
                    height=512,
                    output_bytes=total,
                )
        except Exception:
            for key in created:
                storage.delete(key)
            raise
        finally:
            _IMAGE_GATE.release()
