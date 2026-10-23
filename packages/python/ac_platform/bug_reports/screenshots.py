"""Pictures of the screen attached to bug reports.

A picture is decoded fully, checked (one still PNG, JPEG or WebP, bounded size, no
decompression bomb), turned upright, stripped of every piece of metadata, shrunk to at most
1600 px on its long edge and saved as new WebP pixels. The original bytes are never kept.

Pictures live in the environment's private Sales X-Ray store (``sales_xray_storage_root``),
in its own ``bug-reports`` folder: one file per report, named by the report's id, written
once (temporary file, fsync, link) and read back only when its SHA-256 matches the report.
"""

from __future__ import annotations

import hashlib
import io
import os
import threading
import warnings
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from PIL import Image, ImageOps, UnidentifiedImageError

MAX_SCREENSHOT_BYTES = 4 * 1024 * 1024
MAX_PIXELS = 24_000_000
MAX_EDGE = 8192
KEPT_EDGE = 1600
FOLDER = "bug-reports"
_FORMATS = {"JPEG": "image/jpeg", "PNG": "image/png", "WEBP": "image/webp"}
_GATE = threading.BoundedSemaphore(2)


class ScreenshotError(ValueError):
    """The picture was refused; the message is safe to show."""


@dataclass(frozen=True, slots=True)
class CleanScreenshot:
    data: bytes
    sha256: str
    content_type: str = "image/webp"


def clean_screenshot(body: bytes, content_type: str) -> CleanScreenshot:
    """New WebP pixels from one still image, or ScreenshotError."""
    if not 0 < len(body) <= MAX_SCREENSHOT_BYTES:
        raise ScreenshotError("The picture is larger than 4 MB.")
    if not _GATE.acquire(timeout=10):
        raise ScreenshotError("Pictures are busy. Send again in a moment.")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(body), formats=list(_FORMATS)) as probe:
                if (
                    _FORMATS.get(probe.format or "") != content_type
                    or probe.width <= 0
                    or probe.height <= 0
                    or max(probe.size) > MAX_EDGE
                    or probe.width * probe.height > MAX_PIXELS
                    or getattr(probe, "n_frames", 1) != 1
                ):
                    raise ScreenshotError("Choose one still PNG, JPG or WebP picture.")
                probe.verify()
            with Image.open(io.BytesIO(body), formats=list(_FORMATS)) as source:
                source.load()
                with ImageOps.exif_transpose(source) as upright:
                    pixels = upright.convert("RGB")
        try:
            pixels.thumbnail((KEPT_EDGE, KEPT_EDGE), Image.Resampling.LANCZOS)
            pixels.info.clear()
            output = io.BytesIO()
            pixels.save(output, format="WEBP", quality=82, method=4)
        finally:
            pixels.close()
    except ScreenshotError:
        raise
    except (
        UnidentifiedImageError,
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
        OSError,
        ValueError,
        SyntaxError,
    ):
        raise ScreenshotError("Choose one still PNG, JPG or WebP picture.") from None
    finally:
        _GATE.release()
    data = output.getvalue()
    return CleanScreenshot(data=data, sha256=hashlib.sha256(data).hexdigest())


class ScreenshotStore:
    """One private folder of report pictures under the environment's Sales X-Ray store."""

    def __init__(self, storage_root: str | os.PathLike[str] | None) -> None:
        root = Path(storage_root) if storage_root else None
        self.folder = (
            root / FOLDER if root is not None and root.is_absolute() and root.is_dir() else None
        )

    @property
    def available(self) -> bool:
        return self.folder is not None

    def key_for(self, bug_id: UUID) -> str:
        return f"{FOLDER}/{bug_id.hex}.webp"

    def _path(self, key: str) -> Path:
        if self.folder is None:
            raise ScreenshotError("Pictures are not kept here.")
        name = key.removeprefix(FOLDER + "/")
        stem = name.removesuffix(".webp")
        if name == key or stem == name or len(stem) != 32 or stem.strip("0123456789abcdef"):
            raise ScreenshotError("That picture is not here.")
        return self.folder / name

    def put(self, bug_id: UUID, picture: CleanScreenshot) -> str:
        """Write once; an existing file for this report is never replaced."""
        key = self.key_for(bug_id)
        path = self._path(key)
        assert self.folder is not None
        self.folder.mkdir(mode=0o700, exist_ok=True)
        temporary = self.folder / f".upload-{bug_id.hex}-{os.getpid()}.tmp"
        descriptor = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        try:
            with os.fdopen(descriptor, "wb") as output:
                output.write(picture.data)
                output.flush()
                os.fsync(output.fileno())
            try:
                os.link(temporary, path)
            except FileExistsError:
                raise ScreenshotError("This report already has a picture.") from None
        finally:
            temporary.unlink(missing_ok=True)
        return key

    def read(self, key: str, *, expected_sha256: str) -> bytes:
        path = self._path(key)
        try:
            data = path.read_bytes()
        except FileNotFoundError:
            raise ScreenshotError("That picture is not here.") from None
        if hashlib.sha256(data).hexdigest() != expected_sha256:
            raise ScreenshotError("That picture changed after it was saved.")
        return data
