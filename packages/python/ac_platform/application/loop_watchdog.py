"""Say what blocked the API's event loop, and where (orchestrator, 24 Oct 2026).

The API serves every request from one event loop. Anything synchronous that
runs long on it (a large encode, a blocking call, a heavy parse) stalls every
request in flight, and until now nothing said where: first launches waited
~15 s on 24 Oct 2026. A heartbeat task ticks every ``interval``; a watcher
thread notices when a tick is more than ``threshold`` late, notes where the
loop thread is at that moment (file:line and function only, never values), and
the heartbeat logs one ``event_loop_blocked`` warning with the whole lag once
the loop is back. Each place warns at most once per ``every`` seconds; the
ones held back are counted in its next warning. A loop still blocked after
``still_after`` seconds is reported by the watcher right away, in case it
never comes back.

"unknown" means the watcher never ran during the stall: something held the GIL
in C the whole time. On 26 Oct 2026 production stalled 3.7 s that way while a
Home screen loaded, and the same seven requests took 0.15 s a minute later.
So the watchdog also says:
- when the stall was the garbage collector: ``where`` names its generation,
  with ``gc_ms``, and any collection of ``GC_SLOW`` or more logs ``gc_pause``;
- with ``dump_after`` set, every thread's stack (file, line and function only)
  once the loop has been held that long. faulthandler writes it from a thread
  of its own that needs no GIL, so a C-level holder names itself too.
``settle_startup_heap()`` freezes what the server built at startup, so full
collections stop walking it: about 245 ms of every one on ac's CPU.
"""

from __future__ import annotations

import asyncio
import contextlib
import faulthandler
import gc
import sys
import threading
import time
import traceback
from collections import deque
from types import FrameType
from typing import Any, TextIO

import structlog

logger = structlog.get_logger()

# A stall users feel; ordinary scheduling jitter stays well under it.
THRESHOLD = 0.25
INTERVAL = 0.1
EVERY = 60.0
STILL_AFTER = 10.0
# A collection this long gets a line of its own, stall or not.
GC_SLOW = 0.1
# The servers' stack dump: stalls this long write every thread's stack.
DUMP_AFTER = 3.0
# Places remembered for throttling; more than this starts the count afresh.
_PLACES = 256
# Slow collections kept for the heartbeat to log; more than this drops the oldest.
_SLOW_KEPT = 32
# Where a path stops being the server's own layout.
_ROOTS = ("/site-packages/", "/ac_platform/", "/tests/", "/lib/python")


def _short(filename: str) -> str:
    path = filename.replace("\\", "/")
    for root in _ROOTS:
        at = path.rfind(root)
        if at != -1:
            return path[at + 1 :]
    return path.rsplit("/", 1)[-1]


def blocking_location(frame: FrameType | None, *, inner: int = 3, ours: int = 3) -> str:
    """The ``inner`` innermost frames, then up to ``ours`` of the platform's own callers.

    For example ``copy.py:270 in _reconstruct < copy.py:146 in deepcopy <
    fastapi/routing.py:301 in app < ac_platform/http/x.py:88 in answer``: what was
    running, which library call it was in, and which of our code led there (on
    dev, 24 Oct 2026, the innermost frame and our middleware alone didn't say).
    File, line and function names only.
    """

    if frame is None:
        return "unknown"
    stack = traceback.extract_stack(frame)  # outermost first
    if not stack:
        return "unknown"
    places = list(reversed(stack[-inner:]))
    found = 0
    for entry in reversed(stack[:-inner]):
        if found >= ours:
            break
        if "/ac_platform/" in entry.filename.replace("\\", "/"):
            places.append(entry)
            found += 1
    return " < ".join(
        f"{_short(entry.filename)}:{entry.lineno} in {entry.name}" for entry in places
    )


class LoopWatchdog:
    """Start inside the running loop; stop it on shutdown."""

    def __init__(
        self,
        *,
        threshold: float = THRESHOLD,
        interval: float = INTERVAL,
        every: float = EVERY,
        still_after: float = STILL_AFTER,
        dump_after: float | None = None,
        dump_to: TextIO | None = None,
    ) -> None:
        self.threshold = threshold
        self.interval = interval
        self.every = every
        self.still_after = still_after
        self.dump_after = dump_after
        self.held_back = 0
        self._beat = time.monotonic()
        # (beat, place) noted by the watcher for the stall that began after that beat.
        self._noted: tuple[float, str] | None = None
        self._still_reported: float | None = None
        self._warned: dict[str, float] = {}
        self._held: dict[str, int] = {}
        self._loop_thread: int | None = None
        self._task: asyncio.Task[None] | None = None
        self._thread: threading.Thread | None = None
        self._stopping = threading.Event()
        # Collections: when the running one began, the last one (generation, began, ended),
        # and the slow ones (generation, ms, collected) waiting for the heartbeat to log.
        self._gc_began: float | None = None
        self._last_gc: tuple[int, float, float] | None = None
        self._slow_gc: deque[tuple[int, int, int]] = deque(maxlen=_SLOW_KEPT)
        # The stack dump: where it goes, and when it was last pushed back. Re-armed
        # six times per ``dump_after``, so any stall that long dumps.
        self._dump_to = dump_to
        self._armed = 0.0

    def start(self) -> None:
        self._loop_thread = threading.get_ident()
        self._beat = time.monotonic()
        gc.callbacks.append(self._collection)
        self._arm(self._beat)
        self._task = asyncio.get_running_loop().create_task(self._heartbeat(), name="loop-watchdog")
        self._thread = threading.Thread(target=self._watch, name="loop-watchdog", daemon=True)
        self._thread.start()

    async def stop(self) -> None:
        self._stopping.set()
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
        if self._thread is not None:
            self._thread.join(timeout=1)
        with contextlib.suppress(ValueError):
            gc.callbacks.remove(self._collection)
        if self.dump_after is not None:
            faulthandler.cancel_dump_traceback_later()

    async def _heartbeat(self) -> None:
        while True:
            beat = time.monotonic()
            self._beat = beat
            self._arm(beat)
            await asyncio.sleep(self.interval)
            now = time.monotonic()
            lag = now - beat - self.interval
            if lag > self.threshold:
                noted = self._noted
                where = noted[1] if noted and noted[0] == beat else "unknown"
                facts: dict[str, Any] = {}
                last = self._last_gc
                # A collection that ended inside this stall and took a stall's length was it.
                if last is not None and last[2] > beat and last[2] - last[1] > self.threshold:
                    where = f"gc generation {last[0]}"
                    facts["gc_ms"] = round((last[2] - last[1]) * 1000)
                if self.dump_after is not None and now - self._armed >= self.dump_after:
                    facts["stacks_dumped"] = True
                self._warn(lag, where, **facts)
            while self._slow_gc:
                generation, ms, collected = self._slow_gc.popleft()
                logger.warning(
                    "gc_pause",
                    generation=generation,
                    ms=ms,
                    collected=collected,
                    frozen=gc.get_freeze_count(),
                )

    def _arm(self, now: float) -> None:
        if self.dump_after is None or now - self._armed < self.dump_after / 6:
            return
        faulthandler.dump_traceback_later(self.dump_after, file=self._dump_to or sys.stderr)
        self._armed = now

    def _collection(self, phase: str, info: dict[str, int]) -> None:
        # Runs inside the collection, on whichever thread triggered it: note, never log.
        now = time.monotonic()
        if phase == "start":
            self._gc_began = now
            return
        began, self._gc_began = self._gc_began, None
        if began is None:
            return
        self._last_gc = (info["generation"], began, now)
        if now - began >= GC_SLOW:
            self._slow_gc.append(
                (info["generation"], round((now - began) * 1000), info.get("collected", 0))
            )

    def _warn(self, lag: float, where: str, **facts: Any) -> None:
        now = time.monotonic()
        if now - self._warned.get(where, float("-inf")) < self.every:
            self.held_back += 1
            self._held[where] = self._held.get(where, 0) + 1
            return
        if len(self._warned) >= _PLACES:
            self._warned.clear()
            self._held.clear()
        logger.warning(
            "event_loop_blocked",
            lag_ms=round(lag * 1000),
            where=where,
            held_back=self._held.pop(where, 0),
            **facts,
        )
        self._warned[where] = now

    def _watch(self) -> None:
        while not self._stopping.wait(self.interval / 2):
            beat = self._beat
            late = time.monotonic() - beat - self.interval
            if late <= self.threshold:
                continue
            noted = self._noted
            if noted is None or noted[0] != beat:
                frame = sys._current_frames().get(self._loop_thread or 0)
                self._noted = (beat, blocking_location(frame))
            if late > self.still_after and self._still_reported != beat:
                self._still_reported = beat
                logger.warning(
                    "event_loop_still_blocked",
                    blocked_ms=round(late * 1000),
                    where=self._noted[1] if self._noted else "unknown",
                )


def settle_startup_heap() -> int:
    """Collect once, then freeze what is left: the server's long-lived startup objects.

    Later full collections skip them (``gc.freeze``). Only for a long-running server:
    frozen objects are never collected, even once they become garbage.
    """

    gc.collect()
    gc.freeze()
    return gc.get_freeze_count()


__all__ = ["DUMP_AFTER", "LoopWatchdog", "blocking_location", "settle_startup_heap"]
