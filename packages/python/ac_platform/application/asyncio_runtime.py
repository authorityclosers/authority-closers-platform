"""Cross-platform runner for package-native asynchronous entrypoints."""

from __future__ import annotations

import asyncio
import sys
from collections.abc import Coroutine
from typing import Any


def run_async[T](coroutine: Coroutine[Any, Any, T]) -> T:
    """Run a coroutine on an event loop compatible with async psycopg.

    Python defaults to ``ProactorEventLoop`` on Windows. Psycopg's async
    implementation explicitly requires a selector loop, so every package-native
    database CLI must make that choice before opening a connection.
    """

    if sys.platform == "win32":
        with asyncio.Runner(loop_factory=asyncio.SelectorEventLoop) as runner:
            return runner.run(coroutine)
    return asyncio.run(coroutine)


__all__ = ["run_async"]
