"""Pictures of the screen attached to bug reports.

A picture is decoded fully, checked (one still PNG, JPEG or WebP, bounded size, no
decompression bomb), turned upright, stripped of every piece of metadata, shrunk to at most
1600 px on its long edge and saved as new WebP pixels. The original bytes are never kept.

Pictures live in the environment's private Sales X-Ray store (``sales_xray_storage_root``),
in its own ``bug-reports`` folder: one file per report, named by the report's id, written
once (temporary file, fsync, link) and read back only when its SHA-256 matches the report.
A voice note sent with a report sits beside it (``<id>.voice.webm|ogg|m4a``), kept as sent
once its container's first bytes and its size check out.
"""

from __future__ import annotations

import hashlib
import io
import os
import re
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


# A voice note: its container's first bytes, where they sit, and the file ending.
VOICE_TYPES: dict[str, tuple[bytes, int, str]] = {
    "audio/webm": (b"\x1a\x45\xdf\xa3", 0, "webm"),
    "audio/ogg": (b"OggS", 0, "ogg"),
    "audio/mp4": (b"ftyp", 4, "m4a"),
}
MAX_VOICE_BYTES = 1536 * 1024
MAX_VOICE_SECONDS = 120
_NAME = re.compile(r"^[0-9a-f]{32}(?:\.webp|\.voice\.(?:webm|ogg|m4a))$")


@dataclass(frozen=True, slots=True)
class CleanVoice:
    data: bytes
    sha256: str
    content_type: str
    seconds: int


def check_voice(body: bytes, content_type: str, seconds: int) -> CleanVoice:
    """A voice note is kept as sent once its container and size check out."""
    shape = VOICE_TYPES.get(content_type)
    if shape is None:
        raise ScreenshotError("Record the voice note again.")
    magic, offset, _ending = shape
    if not 0 < len(body) <= MAX_VOICE_BYTES or body[offset : offset + len(magic)] != magic:
        raise ScreenshotError("Record the voice note again.")
    if not 1 <= seconds <= MAX_VOICE_SECONDS:
        raise ScreenshotError("Keep the voice note under two minutes.")
    return CleanVoice(body, hashlib.sha256(body).hexdigest(), content_type, seconds)


class ScreenshotStore:
    """One private folder of report files (pictures, voice notes) under the environment's
    Sales X-Ray store. Names are built here from the report's id, never taken from a request."""

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

    def voice_key_for(self, bug_id: UUID, content_type: str) -> str:
        return f"{FOLDER}/{bug_id.hex}.voice.{VOICE_TYPES[content_type][2]}"

    def _path(self, key: str) -> Path:
        if self.folder is None:
            raise ScreenshotError("Pictures are not kept here.")
        name = key.removeprefix(FOLDER + "/")
        if name == key or not _NAME.fullmatch(name):
            raise ScreenshotError("That file is not here.")
        return self.folder / name

    def _write_once(self, key: str, data: bytes) -> str:
        path = self._path(key)
        assert self.folder is not None
        self.folder.mkdir(mode=0o700, exist_ok=True)
        temporary = self.folder / f".upload-{path.name}-{os.getpid()}.tmp"
        descriptor = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        try:
            with os.fdopen(descriptor, "wb") as output:
                output.write(data)
                output.flush()
                os.fsync(output.fileno())
            try:
                os.link(temporary, path)
            except FileExistsError:
                raise ScreenshotError("This report already has that file.") from None
        finally:
            temporary.unlink(missing_ok=True)
        return key

    def put(self, bug_id: UUID, picture: CleanScreenshot) -> str:
        """Write once; an existing file for this report is never replaced."""
        return self._write_once(self.key_for(bug_id), picture.data)

    def put_voice(self, bug_id: UUID, voice: CleanVoice) -> str:
        return self._write_once(self.voice_key_for(bug_id, voice.content_type), voice.data)

    def read(self, key: str, *, expected_sha256: str) -> bytes:
        path = self._path(key)
        try:
            data = path.read_bytes()
        except FileNotFoundError:
            raise ScreenshotError("That file is not here.") from None
        if hashlib.sha256(data).hexdigest() != expected_sha256:
            raise ScreenshotError("That file changed after it was saved.")
        return data
