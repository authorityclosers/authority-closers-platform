"""Bounded, first-party copies of verified Google profile photos."""

from __future__ import annotations

import asyncio
import io
import logging
import re
import threading
from urllib.parse import urlsplit, urlunsplit

import httpx
from PIL import Image, ImageOps

from ac_platform.media.errors import MediaProcessingError
from ac_platform.media.local_avatar_processing import decode_avatar

_LOGGER = logging.getLogger(__name__)
_IMAGE_GATE = threading.BoundedSemaphore(1)
_PHOTO_TYPES = {"image/jpeg", "image/png", "image/webp"}
_SIZE_SUFFIX = re.compile(r"=[A-Za-z0-9-]+$")
_MAX_SOURCE_BYTES = 1024 * 1024
_MAX_JPEG_BYTES = 65_536
_ACCEPT = "image/jpeg, image/png, image/webp"


def photo_request_url(picture_url: str) -> str | None:
    """Validate a Google-hosted photo URL and request its 256 px variant."""

    if (
        not isinstance(picture_url, str)
        or not picture_url
        or len(picture_url) > 2048
        or any(ord(char) < 32 or ord(char) == 127 for char in picture_url)
    ):
        return None
    try:
        parsed = urlsplit(picture_url)
        hostname = parsed.hostname
        port = parsed.port
    except ValueError:
        return None
    if (
        parsed.scheme != "https"
        or hostname is None
        or not hostname.lower().endswith(".googleusercontent.com")
        or parsed.username is not None
        or parsed.password is not None
        or port is not None
        or parsed.netloc.lower() != hostname.lower()
    ):
        return None

    parent, separator, filename = parsed.path.rpartition("/")
    if _SIZE_SUFFIX.search(filename):
        filename = _SIZE_SUFFIX.sub("=s256-c", filename)
    else:
        filename += "=s256-c"
    path = f"{parent}{separator}{filename}" if separator else filename
    return urlunsplit((parsed.scheme, parsed.netloc, path, parsed.query, parsed.fragment))


def _log_skipped(reason: str) -> None:
    _LOGGER.warning("google_photo_skipped:%s", reason)


def _make_jpeg(body: bytes, content_type: str) -> bytes:
    with (
        _IMAGE_GATE,
        decode_avatar(body, content_type) as decoded,
        ImageOps.fit(
            decoded,
            (256, 256),
            method=Image.Resampling.LANCZOS,
        ) as fitted,
    ):
        fitted.load()
        with Image.new("RGB", (256, 256), "white") as background:
            background.paste(fitted, mask=fitted.getchannel("A"))
            background.info.clear()
            output = io.BytesIO()
            background.save(
                output,
                format="JPEG",
                quality=85,
                optimize=True,
                exif=b"",
            )
    jpeg = output.getvalue()
    if len(jpeg) > _MAX_JPEG_BYTES:
        raise ValueError("jpeg_too_large")
    return jpeg


async def _fetch_with_client(client: httpx.AsyncClient, request_url: str) -> bytes | None:
    async with client.stream("GET", request_url, headers={"Accept": _ACCEPT}) as response:
        if response.status_code != 200:
            _log_skipped("status")
            return None
        content_type = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
        if content_type not in _PHOTO_TYPES:
            _log_skipped("content_type")
            return None
        chunks: list[bytes] = []
        size = 0
        async for chunk in response.aiter_bytes():
            size += len(chunk)
            if size > _MAX_SOURCE_BYTES:
                _log_skipped("source_too_large")
                return None
            chunks.append(chunk)
        try:
            return await asyncio.to_thread(_make_jpeg, b"".join(chunks), content_type)
        except ValueError as error:
            _log_skipped("jpeg_too_large" if str(error) == "jpeg_too_large" else "decode")
            return None
        except (MediaProcessingError, OSError, SyntaxError):
            _log_skipped("decode")
            return None
        except Exception:
            _log_skipped("decode")
            return None


async def fetch_google_profile_photo(
    picture_url: str,
    *,
    http_client: httpx.AsyncClient | None = None,
) -> bytes | None:
    """Fetch, validate, and sanitize a Google-hosted profile photo."""

    request_url = photo_request_url(picture_url)
    if request_url is None:
        _log_skipped("invalid_url")
        return None

    try:
        async with asyncio.timeout(3.0):
            if http_client is not None:
                return await _fetch_with_client(http_client, request_url)
            async with httpx.AsyncClient(
                follow_redirects=False,
                trust_env=False,
                timeout=3.0,
            ) as client:
                return await _fetch_with_client(client, request_url)
    except (TimeoutError, httpx.TimeoutException):
        _log_skipped("timeout")
        return None
    except (httpx.HTTPError, OSError):
        _log_skipped("request")
        return None
    except Exception:
        _log_skipped("request")
        return None
