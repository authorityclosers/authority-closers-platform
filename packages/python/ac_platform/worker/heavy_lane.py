"""Heavy-topic runner port; durable adapters retain claims, fencing and ack authority.

No queue row, caller-supplied executable, media source or scan verdict is trusted
by this runner. Adapters are explicitly composed and own their existing budgets,
leases and receipts. Only the Studio transcode adapter is activated by the CLI.
"""

from __future__ import annotations

import argparse
import asyncio
import signal
from collections.abc import Mapping
from contextlib import suppress
from enum import StrEnum
from pathlib import Path
from typing import Protocol

from ac_platform.worker.load_gate import LoadGate, LoadGateConfig, worker_job_limit


class HeavyTopic(StrEnum):
    SCAN = "ac.heavy.scan.v1"
    TRANSCODE = "ac.heavy.transcode.v1"
    REANALYSE = "ac.heavy.reanalyse.v1"
    EXPORT = "ac.heavy.export.v1"
    BACKUP = "ac.heavy.backup.v1"


INTERACTIVE_TOPIC = "ac.interactive.v1"
BACKGROUND_TOPIC = "ac.background.v1"


class DurableTopicConsumer(Protocol):
    async def run_once(self) -> int:
        """Resolve 0 or 1 admitted jobs; return claimed count after durable outcome.

        Implementations select only their exact topic/kind, own transactions,
        preserve idempotency/lease/deadline/budget, and drain accepted work on
        cancellation. A failed scan is never acknowledged as a clean result.
        """


async def priority_once(
    interactive: DurableTopicConsumer,
    background: DurableTopicConsumer,
    gate: LoadGate,
) -> int:
    """Interactive queue first; background is never claimed under a red gate."""
    claimed = await interactive.run_once()
    if claimed:
        return claimed
    if not gate.green():
        return 0
    return await background.run_once()


class HeavyRunner:
    def __init__(
        self,
        consumers: Mapping[HeavyTopic, DurableTopicConsumer],
        *,
        gate: LoadGate,
        max_jobs: int = 100,
    ) -> None:
        if not consumers or any(type(topic) is not HeavyTopic for topic in consumers):
            raise ValueError("heavy_topic_not_registered")
        if not 1 <= worker_job_limit(str(max_jobs)) <= 100_000:
            raise ValueError("worker_job_limit_invalid")
        self.consumers = dict(consumers)
        self.gate = gate
        self.max_jobs = max_jobs

    async def run(self, topic: HeavyTopic, stop: asyncio.Event) -> int:
        if topic not in self.consumers:
            raise ValueError("heavy_topic_not_registered")
        completed = 0
        while completed < self.max_jobs and await self.gate.wait(stop):
            if stop.is_set():
                break
            # No admission controls run after claiming. A red gate cannot
            # cancel accepted work or modify its lease, deadline or budget.
            task = asyncio.create_task(self.consumers[topic].run_once())
            try:
                claimed = await asyncio.shield(task)
            except asyncio.CancelledError:
                while not task.done():
                    try:
                        await asyncio.shield(task)
                    except asyncio.CancelledError:
                        continue
                task.result()
                raise
            if type(claimed) is not int or claimed not in (0, 1):
                raise ValueError("heavy_consumer_result_invalid")
            completed += claimed
            if not claimed:
                with suppress(TimeoutError):
                    await asyncio.wait_for(stop.wait(), timeout=self.gate.config.poll_seconds)
        return completed


class _StudioConsumer:
    def __init__(self, worker: object) -> None:
        self.worker = worker

    async def run_once(self) -> int:
        from ac_platform.media.studio_video_worker import StudioVideoJobWorker

        if not isinstance(self.worker, StudioVideoJobWorker):
            raise TypeError("heavy_studio_worker_required")
        return (await self.worker.run_once()).claimed


async def serve_video(args: argparse.Namespace) -> None:
    from ac_platform.application.settings import get_settings
    from ac_platform.media.runtime import create_default_media_runtime

    runtime = create_default_media_runtime(get_settings()).studio_video_runtime
    if runtime is None:
        raise ValueError("heavy_studio_runtime_required")
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop.set)
    try:
        runner = HeavyRunner(
            {HeavyTopic.TRANSCODE: _StudioConsumer(runtime.worker)},
            gate=LoadGate(LoadGateConfig(credit_file=args.credit_file)),
            max_jobs=args.max_jobs,
        )
        await runner.run(HeavyTopic.TRANSCODE, stop)
    finally:
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.remove_signal_handler(sig)


def main() -> None:
    parser = argparse.ArgumentParser(description="Explicit on-demand heavy Studio runner")
    parser.add_argument("--topic", choices=[HeavyTopic.TRANSCODE.value], required=True)
    parser.add_argument("--max-jobs", type=int, default=100)
    parser.add_argument("--credit-file", type=Path)
    args = parser.parse_args()
    if not 1 <= args.max_jobs <= 100_000:
        parser.error("max-jobs must be 1–100000")
    asyncio.run(serve_video(args))


if __name__ == "__main__":
    main()
