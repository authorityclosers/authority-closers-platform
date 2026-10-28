import asyncio

import pytest

from ac_platform.worker.heavy_lane import HeavyRunner, HeavyTopic, priority_once
from ac_platform.worker.load_gate import LoadGateConfig


class Gate:
    config = LoadGateConfig(poll_seconds=0.01)

    def __init__(self, green: bool = True) -> None:
        self.allowed = green

    def green(self) -> bool:
        return self.allowed

    async def wait(self, stop: asyncio.Event) -> bool:
        if not self.allowed:
            await stop.wait()
            return False
        return not stop.is_set()


class Consumer:
    def __init__(self, claimed: int = 1) -> None:
        self.calls = 0
        self.claimed = claimed

    async def run_once(self) -> int:
        self.calls += 1
        return self.claimed


async def test_interactive_has_priority_and_ignores_background_gate() -> None:
    interactive, background = Consumer(), Consumer()
    assert await priority_once(interactive, background, Gate(False)) == 1
    assert interactive.calls == 1 and background.calls == 0


async def test_background_only_when_interactive_empty_and_gate_green() -> None:
    interactive, background = Consumer(0), Consumer()
    assert await priority_once(interactive, background, Gate(False)) == 0
    assert background.calls == 0
    assert await priority_once(interactive, background, Gate(True)) == 1
    assert background.calls == 1


async def test_recycle_counts_durable_jobs() -> None:
    consumer = Consumer()
    runner = HeavyRunner({HeavyTopic.TRANSCODE: consumer}, gate=Gate(), max_jobs=3)
    assert await runner.run(HeavyTopic.TRANSCODE, asyncio.Event()) == 3
    assert consumer.calls == 3


async def test_red_gate_never_claims() -> None:
    consumer, stop = Consumer(), asyncio.Event()
    runner = HeavyRunner({HeavyTopic.SCAN: consumer}, gate=Gate(False))
    task = asyncio.create_task(runner.run(HeavyTopic.SCAN, stop))
    await asyncio.sleep(0)
    assert consumer.calls == 0
    stop.set()
    assert await task == 0


async def test_cancel_drains_accepted_work() -> None:
    started, release = asyncio.Event(), asyncio.Event()

    class Blocked:
        async def run_once(self) -> int:
            started.set()
            await release.wait()
            return 1

    runner = HeavyRunner({HeavyTopic.TRANSCODE: Blocked()}, gate=Gate())
    task = asyncio.create_task(runner.run(HeavyTopic.TRANSCODE, asyncio.Event()))
    await started.wait()
    task.cancel()
    await asyncio.sleep(0)
    assert not task.done()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task


async def test_unregistered_topic_never_dispatches() -> None:
    runner = HeavyRunner({HeavyTopic.TRANSCODE: Consumer()}, gate=Gate())
    with pytest.raises(ValueError, match="heavy_topic_not_registered"):
        await runner.run(HeavyTopic.REANALYSE, asyncio.Event())
