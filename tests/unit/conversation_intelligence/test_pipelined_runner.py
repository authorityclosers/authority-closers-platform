"""Concurrency and shutdown proof without native/provider/DB execution."""

from __future__ import annotations

import asyncio
from datetime import timedelta

import pytest

from ac_platform.conversation_intelligence.runner import (
    MAX_PROVIDER_CONSUMERS,
    PipelinedConversationWorkerRunner,
)

from .test_runner import _FakeComponent


def runner(
    log: list[str],
    offline: _FakeComponent,
    inference: _FakeComponent,
    plan: _FakeComponent | None = None,
) -> PipelinedConversationWorkerRunner:
    return PipelinedConversationWorkerRunner(
        _FakeComponent("retention", log),
        offline,
        plan or _FakeComponent("plan", log),
        inference,
        idle_min=timedelta(seconds=5),
        idle_max=timedelta(seconds=5),
    )


@pytest.mark.asyncio
async def test_provider_progresses_while_another_call_is_in_c1() -> None:
    log: list[str] = []
    stop = asyncio.Event()
    offline = _FakeComponent("offline", log, True, block=True)
    inference = _FakeComponent("inference", log, True, block=True)
    consumer = runner(log, offline, inference)
    task = asyncio.create_task(consumer.run(stop))
    await asyncio.wait_for(offline.started.wait(), 1)
    await asyncio.wait_for(inference.started.wait(), 1)
    assert not offline.release.is_set()
    stop.set()
    inference.release.set()
    offline.release.set()
    summary = await asyncio.wait_for(task, 1)
    assert summary.offline_work == summary.inference_work == 1
    assert offline.calls == inference.calls == 1


@pytest.mark.asyncio
async def test_c1_commit_wakes_idle_pipeline_without_poll_delay() -> None:
    log: list[str] = []
    stop = asyncio.Event()
    offline = _FakeComponent("offline", log, True, block=True)
    plan = _FakeComponent("plan", log)
    inference = _FakeComponent("inference", log)
    consumer = runner(log, offline, inference, plan)
    task = asyncio.create_task(consumer.run(stop))
    await asyncio.wait_for(offline.started.wait(), 1)
    await asyncio.wait_for(inference.started.wait(), 1)
    # The next plan scan can proceed only after C1 returns (commits).
    plan.on_call = stop.set
    offline.block = False
    offline.release.set()
    summary = await asyncio.wait_for(task, 1)
    assert summary.offline_work == 1
    assert plan.calls >= 2


@pytest.mark.asyncio
@pytest.mark.parametrize("local", [True, False], ids=["local", "provider"])
async def test_commit_during_empty_scan_wakes_worker_without_idle_delay(local: bool) -> None:
    log: list[str] = []
    stop = asyncio.Event()
    committed = asyncio.Event()
    scanned = asyncio.Event()
    release = asyncio.Event()
    wakeups = (asyncio.Event(), asyncio.Event())

    class QueueScan(_FakeComponent):
        async def run_once(self) -> bool:
            self.calls += 1
            self.log.append(self.label)
            # A durable queue read can finish before another transaction
            # commits, while run_once is still returning its empty result.
            available = committed.is_set()
            if self.calls == 1:
                assert not available
                scanned.set()
                await release.wait()
            if available:
                stop.set()
            return available

    queue = QueueScan("queued", log)
    consumer = PipelinedConversationWorkerRunner(
        _FakeComponent("retention", log),
        queue if local else _FakeComponent("offline", log),
        _FakeComponent("plan", log),
        _FakeComponent("inference", log) if local else queue,
        idle_min=timedelta(seconds=5),
        idle_max=timedelta(seconds=5),
        wakeups=wakeups,
    )
    task = asyncio.create_task(consumer.run(stop))
    try:
        await asyncio.wait_for(scanned.wait(), 1)
        committed.set()
        # This models the external LISTEN hint, not the local worker's
        # own successful C1 return. A lost hint would incur the 5 s wait.
        wakeups[0 if local else 1].set()
        release.set()
        summary = await asyncio.wait_for(asyncio.shield(task), 1)
        assert queue.calls == 2
        assert summary.offline_work == int(local)
        assert summary.inference_work == int(not local)
    finally:
        stop.set()
        release.set()
        await asyncio.wait_for(task, 1)


@pytest.mark.asyncio
async def test_failure_drains_sibling_and_prevents_more_admission() -> None:
    log: list[str] = []
    offline = _FakeComponent("offline", log, block=True)

    class Failing(_FakeComponent):
        async def run_once(self) -> bool:
            await offline.started.wait()
            raise RuntimeError("synthetic failure")

    consumer = runner(log, offline, Failing("inference", log))
    task = asyncio.create_task(consumer.run(asyncio.Event()))
    await asyncio.wait_for(offline.started.wait(), 1)
    await asyncio.sleep(0.01)
    assert not task.done()
    with pytest.raises(RuntimeError, match="already active"):
        await consumer.run(asyncio.Event())
    offline.release.set()
    with pytest.raises(ExceptionGroup) as raised:
        await asyncio.wait_for(task, 1)
    assert any(str(error) == "synthetic failure" for error in raised.value.exceptions)
    assert offline.calls == 1


@pytest.mark.asyncio
async def test_cancel_drains_both_accepted_workers_and_cleans_waiters() -> None:
    log: list[str] = []
    offline = _FakeComponent("offline", log, block=True)
    inference = _FakeComponent("inference", log, block=True)
    consumer = runner(log, offline, inference)
    task = asyncio.create_task(consumer.run(asyncio.Event()))
    await asyncio.wait_for(offline.started.wait(), 1)
    await asyncio.wait_for(inference.started.wait(), 1)
    task.cancel()
    await asyncio.sleep(0.01)
    assert not task.done()
    offline.release.set()
    inference.release.set()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, 1)
    assert offline.calls == inference.calls == 1


@pytest.mark.asyncio
async def test_provider_consumers_wait_on_providers_side_by_side() -> None:
    log: list[str] = []
    stop = asyncio.Event()
    in_flight = 0
    all_in = asyncio.Event()
    release = asyncio.Event()

    class Provider(_FakeComponent):
        async def run_once(self) -> bool:
            nonlocal in_flight
            self.calls += 1
            in_flight += 1
            if in_flight == 3:
                all_in.set()
            await release.wait()
            stop.set()
            return True

    inference = Provider("inference", log)
    consumer = PipelinedConversationWorkerRunner(
        _FakeComponent("retention", log),
        _FakeComponent("offline", log),
        _FakeComponent("plan", log),
        inference,
        idle_min=timedelta(seconds=5),
        idle_max=timedelta(seconds=5),
        provider_consumers=3,
    )
    task = asyncio.create_task(consumer.run(stop))
    # Three provider stages are in flight at once; none waits for another.
    await asyncio.wait_for(all_in.wait(), 1)
    release.set()
    summary = await asyncio.wait_for(task, 1)
    assert inference.calls == 3
    assert summary.inference_work == 3


@pytest.mark.parametrize("value", [0, MAX_PROVIDER_CONSUMERS + 1, True, 2.0, "2"])
def test_provider_consumers_are_bounded(value: object) -> None:
    log: list[str] = []
    with pytest.raises(ValueError, match="provider consumers"):
        PipelinedConversationWorkerRunner(
            _FakeComponent("retention", log),
            _FakeComponent("offline", log),
            _FakeComponent("plan", log),
            _FakeComponent("inference", log),
            provider_consumers=value,  # type: ignore[arg-type]
        )
