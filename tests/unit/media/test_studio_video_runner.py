from __future__ import annotations

import asyncio
from collections import deque
from datetime import timedelta

import pytest

from ac_platform.media.studio_video_runner import (
    StudioVideoRunner,
    StudioVideoRunnerSummary,
)
from ac_platform.media.studio_video_worker import StudioVideoWorkerResult


class _Worker:
    def __init__(self, *results: StudioVideoWorkerResult | BaseException) -> None:
        self.results = deque(results)
        self.calls = 0
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.block = False

    async def run_once(self) -> StudioVideoWorkerResult:
        self.calls += 1
        self.started.set()
        if self.block:
            await self.release.wait()
        result = self.results.popleft() if self.results else StudioVideoWorkerResult()
        if isinstance(result, BaseException):
            raise result
        return result


def _runner(worker: _Worker, *, recovery: float = 0.05) -> StudioVideoRunner:
    return StudioVideoRunner(
        worker,
        idle_min=timedelta(milliseconds=10),
        idle_max=timedelta(milliseconds=20),
        recovery_backoff=timedelta(seconds=recovery),
    )


@pytest.mark.asyncio
async def test_stop_during_poll_drains_accepted_work_and_claims_nothing_else() -> None:
    worker = _Worker(StudioVideoWorkerResult(claimed=1, succeeded=1))
    worker.block = True
    runner, stop = _runner(worker), asyncio.Event()
    task = asyncio.create_task(runner.run(stop))
    await worker.started.wait()
    stop.set()
    await asyncio.sleep(0)
    assert not task.done()
    worker.release.set()
    assert await task == StudioVideoRunnerSummary(polls=1, claimed=1, succeeded=1)
    assert worker.calls == 1


@pytest.mark.asyncio
async def test_repeated_native_cancellation_drains_poll_and_holds_admission() -> None:
    worker = _Worker(StudioVideoWorkerResult(claimed=1, retried=1))
    worker.block = True
    runner = _runner(worker)
    task = asyncio.create_task(runner.run(asyncio.Event()))
    await worker.started.wait()
    task.cancel()
    await asyncio.sleep(0.01)
    assert not task.done()
    task.cancel()
    await asyncio.sleep(0.01)
    assert not task.done()
    with pytest.raises(RuntimeError, match="already active"):
        await runner.run(asyncio.Event())
    worker.release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert worker.calls == 1
    stopped = asyncio.Event()
    stopped.set()
    assert await runner.run(stopped) == StudioVideoRunnerSummary()


@pytest.mark.asyncio
async def test_recovery_hold_uses_backoff_instead_of_busy_polling() -> None:
    worker = _Worker(StudioVideoWorkerResult(recovery_held=1))
    runner, stop = _runner(worker, recovery=0.1), asyncio.Event()
    task = asyncio.create_task(runner.run(stop))
    await worker.started.wait()
    await asyncio.sleep(0.03)
    assert worker.calls == 1
    stop.set()
    assert await task == StudioVideoRunnerSummary(polls=1, recovery_held=1)


@pytest.mark.asyncio
async def test_empty_polls_back_off_and_claimed_work_resets_delay(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    worker = _Worker(
        StudioVideoWorkerResult(),
        StudioVideoWorkerResult(),
        StudioVideoWorkerResult(),
        StudioVideoWorkerResult(claimed=1, dead_lettered=1),
        StudioVideoWorkerResult(),
        StudioVideoWorkerResult(recovery_held=1),
        StudioVideoWorkerResult(),
    )
    runner, stop, delays = _runner(worker, recovery=0.1), asyncio.Event(), []

    async def record_delay(_stop: asyncio.Event, delay: timedelta) -> None:
        delays.append(delay)
        if len(delays) == 6:
            stop.set()

    monkeypatch.setattr(runner, "_wait_for_stop", record_delay)
    summary = await runner.run(stop)
    assert summary.polls == 7
    assert summary.claimed == summary.dead_lettered == 1
    assert summary.recovery_held == 1
    assert delays == [
        timedelta(milliseconds=10),
        timedelta(milliseconds=20),
        timedelta(milliseconds=20),
        timedelta(milliseconds=10),
        timedelta(milliseconds=100),
        timedelta(milliseconds=10),
    ]


@pytest.mark.asyncio
async def test_concurrent_run_is_rejected_and_admission_releases_after_stop() -> None:
    worker = _Worker(StudioVideoWorkerResult())
    worker.block = True
    runner, first_stop = _runner(worker), asyncio.Event()
    first = asyncio.create_task(runner.run(first_stop))
    await worker.started.wait()
    with pytest.raises(RuntimeError, match="already active"):
        await runner.run(asyncio.Event())
    first_stop.set()
    worker.release.set()
    assert (await first).polls == 1

    already_stopped = asyncio.Event()
    already_stopped.set()
    assert await runner.run(already_stopped) == StudioVideoRunnerSummary()


@pytest.mark.asyncio
async def test_unexpected_worker_error_propagates_without_retry_loop() -> None:
    worker = _Worker(RuntimeError("synthetic infrastructure failure"))
    runner = _runner(worker)
    with pytest.raises(RuntimeError, match="synthetic infrastructure failure"):
        await runner.run(asyncio.Event())
    assert worker.calls == 1


@pytest.mark.parametrize(
    ("idle_min", "idle_max", "recovery"),
    [
        (0.0, 1.0, 1.0),
        (2.0, 1.0, 2.0),
        (1.0, 901.0, 1.0),
        (1.0, 2.0, 901.0),
    ],
)
def test_delay_configuration_is_bounded(idle_min: float, idle_max: float, recovery: float) -> None:
    with pytest.raises(ValueError, match="bounded and ordered"):
        StudioVideoRunner(
            _Worker(),
            idle_min=timedelta(seconds=idle_min),
            idle_max=timedelta(seconds=idle_max),
            recovery_backoff=timedelta(seconds=recovery),
        )
