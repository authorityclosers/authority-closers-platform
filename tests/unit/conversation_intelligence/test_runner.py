"""Focused tests for the inert dedicated conversation worker runner."""

from __future__ import annotations

import asyncio
from collections import deque
from collections.abc import Callable
from datetime import timedelta

import pytest

from ac_platform.conversation_intelligence.runner import (
    ConversationWorkerRunner,
    ConversationWorkerRunnerSummary,
)
from ac_platform.outbox.policy import ReconciliationRequiredError


class _FakeComponent:
    def __init__(
        self,
        label: str,
        log: list[str],
        *results: bool | BaseException,
        block: bool = False,
        on_call: Callable[[], None] | None = None,
    ) -> None:
        self.label = label
        self.log = log
        self.results = deque(results)
        self.block = block
        self.on_call = on_call
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.calls = 0

    async def invoke(self) -> bool:
        self.calls += 1
        self.log.append(self.label)
        self.started.set()
        if self.on_call is not None:
            self.on_call()
        if self.block:
            await self.release.wait()
        result = self.results.popleft() if self.results else False
        if isinstance(result, BaseException):
            raise result
        return result

    async def step(self) -> bool:
        return await self.invoke()

    async def run_once(self) -> bool:
        return await self.invoke()


def _runner(
    log: list[str],
    *,
    retention: _FakeComponent | None = None,
    offline: _FakeComponent | None = None,
    plan: _FakeComponent | None = None,
    inference: _FakeComponent | None = None,
    recovery_backoff: timedelta = timedelta(seconds=10),
) -> ConversationWorkerRunner:
    return ConversationWorkerRunner(
        retention or _FakeComponent("retention", log),
        offline or _FakeComponent("offline", log),
        plan or _FakeComponent("plan", log),
        inference or _FakeComponent("inference", log),
        idle_min=timedelta(milliseconds=10),
        idle_max=timedelta(milliseconds=40),
        recovery_backoff=recovery_backoff,
    )


@pytest.mark.asyncio
async def test_cycle_order_and_content_free_summary() -> None:
    log: list[str] = []
    stop = asyncio.Event()
    inference = _FakeComponent("inference", log, True, on_call=stop.set)
    runner = _runner(
        log,
        retention=_FakeComponent("retention", log, True),
        offline=_FakeComponent("offline", log, False),
        plan=_FakeComponent("plan", log, True),
        inference=inference,
    )

    assert await runner.run(stop) == ConversationWorkerRunnerSummary(
        cycles=1,
        work_cycles=1,
        idle_cycles=0,
        retention_work=1,
        offline_work=0,
        plan_work=1,
        inference_work=1,
    )
    assert log == ["retention", "offline", "plan", "inference"]


@pytest.mark.asyncio
async def test_all_idle_cycles_back_off_and_stop_bounds_polling(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    log: list[str] = []
    stop = asyncio.Event()
    delays: list[timedelta] = []
    runner = _runner(log)

    async def record_wait(_stop: asyncio.Event, delay: timedelta) -> None:
        delays.append(delay)
        if len(delays) == 3:
            stop.set()

    monkeypatch.setattr(runner, "_wait_for_stop", record_wait)
    summary = await runner.run(stop)

    assert summary.cycles == summary.idle_cycles == 3
    assert summary.work_cycles == 0
    assert delays == [
        timedelta(milliseconds=10),
        timedelta(milliseconds=20),
        timedelta(milliseconds=40),
    ]
    assert len(log) == 12


@pytest.mark.asyncio
async def test_recovery_gate_uses_bounded_backoff_without_invoking_later_components(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    log: list[str] = []
    stop = asyncio.Event()
    delays: list[timedelta] = []
    runner = _runner(
        log,
        retention=_FakeComponent(
            "retention", log, ReconciliationRequiredError("synthetic recovery hold")
        ),
        recovery_backoff=timedelta(milliseconds=20),
    )

    async def record_wait(_stop: asyncio.Event, delay: timedelta) -> None:
        delays.append(delay)
        stop.set()

    monkeypatch.setattr(runner, "_wait_for_stop", record_wait)
    summary = await runner.run(stop)

    assert summary == ConversationWorkerRunnerSummary(recovery_holds=1)
    assert delays == [timedelta(milliseconds=20)]
    assert log == ["retention"]


@pytest.mark.asyncio
async def test_stop_during_cycle_drains_accepted_call_without_new_work() -> None:
    log: list[str] = []
    stop = asyncio.Event()
    retention = _FakeComponent("retention", log, block=True)
    runner = _runner(log, retention=retention)
    task = asyncio.create_task(runner.run(stop))
    await retention.started.wait()
    stop.set()
    await asyncio.sleep(0)
    assert not task.done()

    retention.release.set()
    summary = await task
    assert summary.cycles == 1
    assert log == ["retention"]
    assert summary.retention_work == summary.offline_work == 0
    assert summary.plan_work == summary.inference_work == 0


@pytest.mark.asyncio
async def test_repeated_cancellation_drains_owned_call_and_holds_admission() -> None:
    log: list[str] = []
    retention = _FakeComponent("retention", log, block=True)
    runner = _runner(log, retention=retention)
    task = asyncio.create_task(runner.run(asyncio.Event()))
    await retention.started.wait()

    task.cancel()
    await asyncio.sleep(0.01)
    assert not task.done()
    task.cancel()
    await asyncio.sleep(0.01)
    assert not task.done()
    with pytest.raises(RuntimeError, match="already active"):
        await runner.run(asyncio.Event())

    retention.release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert log == ["retention"]

    stopped = asyncio.Event()
    stopped.set()
    assert await runner.run(stopped) == ConversationWorkerRunnerSummary()


@pytest.mark.asyncio
async def test_unexpected_component_error_propagates_without_retry_or_later_stages() -> None:
    log: list[str] = []
    runner = _runner(
        log,
        offline=_FakeComponent("offline", log, RuntimeError("synthetic failure")),
    )

    with pytest.raises(RuntimeError, match="synthetic failure"):
        await runner.run(asyncio.Event())
    assert log == ["retention", "offline"]


@pytest.mark.asyncio
async def test_non_boolean_component_result_is_rejected() -> None:
    log: list[str] = []

    class Invalid(_FakeComponent):
        async def step(self) -> bool:
            self.log.append(self.label)
            return "invalid"  # type: ignore[return-value]

    runner = _runner(log, retention=Invalid("retention", log))
    with pytest.raises(TypeError, match="invalid result"):
        await runner.run(asyncio.Event())
    assert log == ["retention"]


@pytest.mark.parametrize(
    ("idle_min", "idle_max"),
    [
        (timedelta(0), timedelta(seconds=1)),
        (timedelta(seconds=2), timedelta(seconds=1)),
        (timedelta(seconds=1), timedelta(minutes=16)),
    ],
)
def test_delay_configuration_is_bounded(idle_min: timedelta, idle_max: timedelta) -> None:
    log: list[str] = []
    with pytest.raises(ValueError, match="bounded and ordered"):
        ConversationWorkerRunner(
            _FakeComponent("retention", log),
            _FakeComponent("offline", log),
            _FakeComponent("plan", log),
            _FakeComponent("inference", log),
            idle_min=idle_min,
            idle_max=idle_max,
        )


def test_recovery_backoff_is_bounded() -> None:
    log: list[str] = []
    with pytest.raises(ValueError, match="bounded and ordered"):
        ConversationWorkerRunner(
            _FakeComponent("retention", log),
            _FakeComponent("offline", log),
            _FakeComponent("plan", log),
            _FakeComponent("inference", log),
            recovery_backoff=timedelta(minutes=16),
        )
