from __future__ import annotations

import asyncio
import io

import httpx
import pytest
from PIL import Image

from ac_platform.identity.google_profile_photo import (
    fetch_google_profile_photo,
    photo_request_url,
)

PICTURE_URL = "https://lh3.googleusercontent.com/a/profile=s96-c"


def _image_bytes(
    image: Image.Image,
    *,
    image_format: str = "PNG",
    save_all: bool = False,
    append_images: list[Image.Image] | None = None,
) -> bytes:
    output = io.BytesIO()
    image.save(
        output,
        format=image_format,
        save_all=save_all,
        append_images=append_images or [],
    )
    return output.getvalue()


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        (
            "https://lh3.googleusercontent.com/a/profile=s96-c?token=fictional",
            "https://lh3.googleusercontent.com/a/profile=s256-c?token=fictional",
        ),
        (
            "https://lh3.googleusercontent.com/a/profile",
            "https://lh3.googleusercontent.com/a/profile=s256-c",
        ),
    ],
)
def test_photo_request_url_rewrites_only_the_final_size_suffix(source: str, expected: str) -> None:
    assert photo_request_url(source) == expected


@pytest.mark.parametrize(
    "value",
    [
        "http://lh3.googleusercontent.com/a/profile",
        "https://googleusercontent.com/a/profile",
        "https://evilgoogleusercontent.com/a/profile",
        "https://user@lh3.googleusercontent.com/a/profile",
        "https://lh3.googleusercontent.com:443/a/profile",
        "https://lh3.googleusercontent.com:/a/profile",
    ],
)
def test_photo_request_url_rejects_non_google_or_unsafe_authorities(value: str) -> None:
    assert photo_request_url(value) is None


@pytest.mark.asyncio
async def test_png_alpha_is_copied_as_metadata_free_256_pixel_jpeg() -> None:
    source = Image.new("RGBA", (32, 16), (20, 40, 60, 0))
    source.info["exif"] = b"fictional source metadata"
    body = _image_bytes(source)
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, headers={"content-type": "image/png"}, content=body)

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        follow_redirects=False,
    ) as client:
        jpeg = await fetch_google_profile_photo(PICTURE_URL, http_client=client)

    assert jpeg is not None and len(jpeg) <= 65_536
    with Image.open(io.BytesIO(jpeg)) as copied:
        assert copied.format == "JPEG"
        assert copied.size == (256, 256)
        assert copied.getexif() == {}
        assert copied.getpixel((128, 128)) == (255, 255, 255)
    assert len(requests) == 1
    assert str(requests[0].url) == photo_request_url(PICTURE_URL)
    assert requests[0].headers["accept"] == "image/jpeg, image/png, image/webp"
    assert "cookie" not in requests[0].headers


@pytest.mark.parametrize("status_code", [302, 404])
@pytest.mark.asyncio
async def test_non_200_status_is_skipped_without_following_redirects(status_code: int) -> None:
    requests = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal requests
        requests += 1
        return httpx.Response(
            status_code,
            headers={"location": "https://outside.example.test/photo"},
            request=request,
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        follow_redirects=False,
    ) as client:
        assert await fetch_google_profile_photo(PICTURE_URL, http_client=client) is None
    assert requests == 1


@pytest.mark.asyncio
async def test_timeout_is_skipped_and_does_not_log_the_source_url(
    caplog: pytest.LogCaptureFixture,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("fictional timeout", request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        assert await fetch_google_profile_photo(PICTURE_URL, http_client=client) is None
    assert "google_photo_skipped:timeout" in caplog.text
    assert PICTURE_URL not in caplog.text


@pytest.mark.parametrize(
    ("body", "content_type"),
    [
        (b"x" * (1024 * 1024 + 1), "image/png"),
        (b"fictional image bytes", "text/plain"),
        (b"fictional-image-secret", "image/png"),
    ],
)
@pytest.mark.asyncio
async def test_oversize_wrong_type_and_decode_failure_are_skipped_without_logging_bytes(
    body: bytes,
    content_type: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-type": content_type}, content=body)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        assert await fetch_google_profile_photo(PICTURE_URL, http_client=client) is None
    assert "google_photo_skipped:" in caplog.text
    assert PICTURE_URL not in caplog.text
    assert body[:32].decode("ascii", errors="ignore") not in caplog.text


@pytest.mark.asyncio
async def test_decompression_bomb_and_animated_png_are_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 1024)
    large = Image.new("RGB", (40, 40), "white")
    large_body = _image_bytes(large)

    async def fetch(body: bytes) -> bytes | None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, headers={"content-type": "image/png"}, content=body)

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await fetch_google_profile_photo(PICTURE_URL, http_client=client)

    assert await fetch(large_body) is None

    first = Image.new("RGBA", (8, 8), "red")
    second = Image.new("RGBA", (8, 8), "blue")
    animated_body = _image_bytes(first, save_all=True, append_images=[second])
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 12_000_000)
    assert await fetch(animated_body) is None


@pytest.mark.parametrize(
    "value",
    [
        "http://lh3.googleusercontent.com/a/profile",
        "https://evil.example.test/a/profile",
        "https://user@lh3.googleusercontent.com/a/profile",
        "https://lh3.googleusercontent.com:443/a/profile",
    ],
)
@pytest.mark.asyncio
async def test_invalid_source_url_makes_no_request(value: str) -> None:
    requests = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal requests
        requests += 1
        return httpx.Response(200, content=b"")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        assert await fetch_google_profile_photo(value, http_client=client) is None
    assert requests == 0


@pytest.mark.asyncio
async def test_total_timeout_is_enforced_for_a_slow_mock_transport() -> None:
    async def slow_handler(_request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(3.1)
        return httpx.Response(200, headers={"content-type": "image/png"}, content=b"late")

    async with httpx.AsyncClient(transport=httpx.MockTransport(slow_handler)) as client:
        assert await fetch_google_profile_photo(PICTURE_URL, http_client=client) is None
