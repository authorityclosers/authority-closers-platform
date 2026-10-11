"""Actual storage fences overlap processing and exclude erasure on Linux."""

import asyncio
import os
from pathlib import Path

import pytest

from ac_platform.conversation_intelligence.worker import _FencedExecutor


@pytest.mark.skipif(os.name == "nt", reason="Windows keeps conservative exclusive admission")
@pytest.mark.asyncio
async def test_c1_and_provider_overlap_while_erasure_waits_for_both(tmp_path: Path) -> None:
    first = asyncio.Event()
    second = asyncio.Event()
    release_first = asyncio.Event()
    release_second = asyncio.Event()
    erased = asyncio.Event()

    async def process(started: asyncio.Event, release: asyncio.Event) -> None:
        async with _FencedExecutor(tmp_path, exclusive=False):
            started.set()
            await release.wait()

    async def erase() -> None:
        async with _FencedExecutor(tmp_path):
            erased.set()

    c1 = asyncio.create_task(process(first, release_first))
    provider = asyncio.create_task(process(second, release_second))
    erasure = None
    try:
        await asyncio.wait_for(first.wait(), 1)
        await asyncio.wait_for(second.wait(), 1)
        erasure = asyncio.create_task(erase())
        await asyncio.sleep(0.02)
        assert not erased.is_set()
        release_first.set()
        await c1
        await asyncio.sleep(0.02)
        assert not erased.is_set()
        release_second.set()
        await provider
        await asyncio.wait_for(erasure, 1)
        assert erased.is_set()
    finally:
        release_first.set()
        release_second.set()
        await asyncio.gather(c1, provider, *([] if erasure is None else [erasure]))
