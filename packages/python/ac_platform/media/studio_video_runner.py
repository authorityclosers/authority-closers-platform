"""Bounded local/test polling for the dedicated Studio video worker.

The runner is deliberately inert until a caller awaits :meth:`run`.  It owns
one serial ``run_once`` poll at a time, never dispatches generic job kinds and
contains no launcher, settings or logging side effects.  Shutdown waits for an
accepted poll to resolve; native task cancellation drains that poll before it
is propagated.
"""

from __future__ import annotations

import asyncio
from contextlib import suppress
from dataclasses import dataclass
from datetime import timedelta
from threading import Lock
from typing import Protocol

from ac_platform.media.studio_video_worker import StudioVideoWorkerResult

_MIN_DELAY = timedelta(milliseconds=10)
_MAX_DELAY = timedelta(minutes=15)


class StudioVideoRunOnce(Protocol):
    async def run_once(self) -> StudioVideoWorkerResult:
        """Claim and fully resolve no more than one Studio video job."""


@dataclass(frozen=True, slots=True)
class StudioVideoRunnerSummary:
    polls: int = 0
    claimed: int = 0
    succeeded: int = 0
    retried: int = 0
    dead_lettered: int = 0
    fenced: int = 0
    recovery_held: int = 0
    release_failed: int = 0
    busy: int = 0

    def append(self, result: StudioVideoWorkerResult) -> StudioVideoRunnerSummary:
        return StudioVideoRunnerSummary(
            polls=self.polls + 1,
            claimed=self.claimed + result.claimed,
            succeeded=self.succeeded + result.succeeded,
            retried=self.retried + result.retried,
            dead_lettered=self.dead_lettered + result.dead_lettered,
            fenced=self.fenced + result.fenced,
            recovery_held=self.recovery_held + result.recovery_held,
            release_failed=self.release_failed + result.release_failed,
            busy=self.busy + result.busy,
        )


class StudioVideoRunner:
    """Poll one dedicated worker serially until an explicit stop is requested."""

    def __init__(
        self,
        worker: StudioVideoRunOnce,
        *,
        idle_min: timedelta = timedelta(milliseconds=250),
        idle_max: timedelta = timedelta(seconds=5),
        recovery_backoff: timedelta = timedelta(seconds=10),
    ) -> None:
        if (
            not isinstance(idle_min, timedelta)
            or not isinstance(idle_max, timedelta)
            or not isinstance(recovery_backoff, timedelta)
            or not _MIN_DELAY <= idle_min <= idle_max <= _MAX_DELAY
            or not idle_min <= recovery_backoff <= _MAX_DELAY
        ):
            raise ValueError("Studio video runner delays must be bounded and ordered")
        if not callable(getattr(worker, "run_once", None)):
            raise TypeError("Studio video runner requires a dedicated run_once worker")
        self.worker = worker
        self.idle_min = idle_min
        self.idle_max = idle_max
        self.recovery_backoff = recovery_backoff
        self._admission = Lock()

    async def run(self, stop: asyncio.Event) -> StudioVideoRunnerSummary:
        """Poll until ``stop``; finish accepted work before returning.

        Setting ``stop`` never cancels an in-flight worker call.  Cancelling the
        runner task drains its strongly held poll task before re-raising
        ``CancelledError``.  Unexpected worker exceptions propagate so a
        launcher can report/restart explicitly instead of silently busy-looping.
        """

        if not isinstance(stop, asyncio.Event):
            raise TypeError("Studio video runner stop must be an asyncio.Event")
        if not self._admission.acquire(blocking=False):
            raise RuntimeError("Studio video runner is already active")
        summary = StudioVideoRunnerSummary()
        idle = self.idle_min
        try:
            while not stop.is_set():
                result = await self._owned_poll()
                if type(result) is not StudioVideoWorkerResult:
                    raise TypeError("Studio video worker returned an invalid result")
                summary = summary.append(result)
                if stop.is_set():
                    break
                if result.recovery_held:
                    idle = self.idle_min
                    await self._wait_for_stop(stop, self.recovery_backoff)
                elif result.claimed:
                    idle = self.idle_min
                else:
                    await self._wait_for_stop(stop, idle)
                    idle = min(idle * 2, self.idle_max)
            return summary
        finally:
            self._admission.release()

    async def _owned_poll(self) -> StudioVideoWorkerResult:
        owned = asyncio.create_task(
            self.worker.run_once(),
            name="studio-video-runner-poll",
        )
        try:
            return await asyncio.shield(owned)
        except asyncio.CancelledError:
            while not owned.done():
                try:
                    await asyncio.shield(owned)
                except asyncio.CancelledError:
                    continue
                except BaseException:
                    break
            if owned.done() and not owned.cancelled():
                with suppress(BaseException):
                    owned.result()
            raise

    @staticmethod
    async def _wait_for_stop(stop: asyncio.Event, delay: timedelta) -> None:
        with suppress(TimeoutError):
            await asyncio.wait_for(stop.wait(), timeout=delay.total_seconds())


__all__ = [
    "StudioVideoRunOnce",
    "StudioVideoRunner",
    "StudioVideoRunnerSummary",
]
