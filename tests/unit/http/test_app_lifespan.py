"""The API's lifespan: servers freeze their startup objects and dump a long stall's stacks.

26 Oct 2026: production stalled 3.7 s while a Home screen loaded, and nothing could
say what held it. Tests and laptops keep the collector untouched and dump nothing.
"""

from __future__ import annotations

import asyncio
import gc
from typing import ClassVar

import pytest
from fastapi import FastAPI

from ac_platform.http import app as api


class _Watchdog:
    made: ClassVar[list[float | None]] = []

    def __init__(self, *, dump_after: float | None = None) -> None:
        self.made.append(dump_after)

    def start(self) -> None:
        return None

    async def stop(self) -> None:
        return None


class _Engine:
    async def dispose(self) -> None:
        return None


@pytest.mark.parametrize(
    ("environment", "server"),
    [("production", True), ("staging", True), ("development", True), ("test", False)],
)
def test_servers_freeze_startup_objects_and_dump_long_stalls(
    monkeypatch: pytest.MonkeyPatch, environment: str, server: bool
) -> None:
    monkeypatch.setattr(
        api, "settings", api.settings.model_copy(update={"environment": environment})
    )
    monkeypatch.setattr(api, "LoopWatchdog", _Watchdog)
    monkeypatch.setattr(api, "engine", _Engine())
    _Watchdog.made.clear()
    gc.unfreeze()

    async def serve() -> int:
        async with api.lifespan(FastAPI()):
            return gc.get_freeze_count()

    try:
        frozen = asyncio.run(serve())
    finally:
        gc.unfreeze()
    assert (frozen > 0) is server
    assert _Watchdog.made == [3.0 if server else None]
