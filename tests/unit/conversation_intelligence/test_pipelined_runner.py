"""Concurrency and shutdown proof without native/provider/DB execution."""

from __future__ import annotations

import asyncio
from datetime import timedelta

import pytest

from ac_platform.conversation_intelligence.runner import PipelinedConversationWorkerRunner

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
