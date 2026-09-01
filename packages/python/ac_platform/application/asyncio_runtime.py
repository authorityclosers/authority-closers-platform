"""Cross-platform runner for package-native asynchronous entrypoints."""

from __future__ import annotations

import asyncio
import sys
from collections.abc import Coroutine
from typing import Any


def compatible_event_loop_factory() -> asyncio.AbstractEventLoop:
    """Return an event loop that supports async psycopg on this platform."""

    if sys.platform == "win32":
        return asyncio.SelectorEventLoop()
    return asyncio.new_event_loop()


def run_async[T](coroutine: Coroutine[Any, Any, T]) -> T:
    """Run a coroutine on an event loop compatible with async psycopg.

    Python defaults to ``ProactorEventLoop`` on Windows. Psycopg's async
    implementation explicitly requires a selector loop, so every package-native
    database CLI must make that choice before opening a connection.
    """

    if sys.platform == "win32":
        with asyncio.Runner(loop_factory=compatible_event_loop_factory) as runner:
            return runner.run(coroutine)
    return asyncio.run(coroutine)


__all__ = ["compatible_event_loop_factory", "run_async"]
