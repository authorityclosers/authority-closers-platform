"""Synthetic tests for private audio range slicing and cancellation cleanup."""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Iterator
from typing import Any

import pytest

from ac_platform.http.conversation_playback import _PrivateAudioResponse, byte_range


@pytest.mark.parametrize(
    ("header", "size", "expected"),
    [
        (None, 10, (0, 9)),
        ("bytes=2-5", 10, (2, 5)),
        ("bytes=2-", 10, (2, 9)),
        ("bytes=-3", 10, (7, 9)),
        ("bytes=8-50", 10, (8, 9)),
    ],
)
def test_byte_range_accepts_one_bounded_interval(
    header: str | None, size: int, expected: tuple[int, int]
) -> None:
    assert byte_range(header, size) == expected


@pytest.mark.parametrize(
    "header",
    ["", "bytes=", "bytes=0-0,2-3", "bytes=10-11", "bytes=5-4", "bytes=-0"],
)
def test_byte_range_rejects_malformed_or_unsatisfiable_interval(header: str | None) -> None:
    with pytest.raises(ValueError):
        byte_range(header, 10)


def test_private_audio_response_slices_chunks_and_closes_source() -> None:
    closed = False

    def source() -> Iterator[bytes]:
        nonlocal closed
        try:
            yield b"def"
            yield b"ghi"
        finally:
            closed = True

    iterator = source()
    response = _PrivateAudioResponse(
        iterator, b"abc", 1, 4, status_code=206, media_type="audio/wav"
    )

    async def exercise() -> list[bytes]:
        chunks: list[bytes] = []
        async for chunk in response.body_iterator:
            chunks.append(chunk)
        response._close()
        return chunks

    assert asyncio.run(exercise()) == [b"bc", b"de"]
    assert closed


def test_private_audio_response_cancellation_closes_blocked_source() -> None:
    started, release = threading.Event(), threading.Event()
    closed = threading.Event()

    class BlockingIterator:
        def __iter__(self) -> BlockingIterator:
            return self

        def __next__(self) -> bytes:
            started.set()
            if not release.wait(5):
                raise RuntimeError("synthetic source did not release")
            return b"def"

        def close(self) -> None:
            closed.set()

    response = _PrivateAudioResponse(
        BlockingIterator(), b"abc", 0, 5, status_code=206, media_type="audio/wav"
    )

    async def exercise() -> None:
        async def send(message: dict[str, Any]) -> None:
            del message

        task = asyncio.create_task(
            response(
                {
                    "type": "http",
                    "asgi": {"spec_version": "2.4"},
                    "method": "GET",
                    "path": "/recordings/source",
                    "headers": [],
                    "query_string": b"",
                },
                lambda: asyncio.sleep(0),
                send,
            )
        )
        assert await asyncio.to_thread(started.wait, 5)
        task.cancel()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(exercise())
    assert closed.is_set()
