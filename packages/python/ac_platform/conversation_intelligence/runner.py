"""Inert serial runner for the dedicated conversation workers.

The runner owns no database, provider, settings, or launcher state.  A caller
injects the four already-scoped workers and explicitly awaits :meth:`run`.
Each complete cycle invokes retention, offline inspection, processing-plan
advancement, and inference in that order.  Stopping between cycles leaves no
accepted worker call abandoned; native cancellation drains the currently
owned call before propagating cancellation.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from contextlib import suppress
from dataclasses import dataclass
from datetime import timedelta
from threading import Lock
from typing import Protocol

from ac_platform.outbox.policy import ReconciliationRequiredError

_MIN_DELAY = timedelta(milliseconds=10)
_MAX_DELAY = timedelta(minutes=15)


class ConversationRetentionStep(Protocol):
    async def step(self) -> bool:
        """Run one bounded retention scheduling step."""


class ConversationOfflineRunOnce(Protocol):
    async def run_once(self) -> bool:
        """Run one bounded local inspection or erasure job."""


class ConversationPlanStep(Protocol):
    async def step(self) -> bool:
        """Run one bounded processing-plan scheduling step."""


class ConversationInferenceRunOnce(Protocol):
    async def run_once(self) -> bool:
        """Run one bounded provider-stage job."""


@dataclass(frozen=True, slots=True)
class ConversationWorkerRunnerSummary:
    """Content-free counters for one explicit runner invocation."""

    cycles: int = 0
    work_cycles: int = 0
    idle_cycles: int = 0
    retention_work: int = 0
    offline_work: int = 0
    plan_work: int = 0
    inference_work: int = 0
    recovery_holds: int = 0

    def append(
        self,
        outcomes: tuple[bool, bool, bool, bool],
    ) -> ConversationWorkerRunnerSummary:
        retention, offline, plan, inference = outcomes
        worked = any(outcomes)
        return ConversationWorkerRunnerSummary(
            cycles=self.cycles + 1,
            work_cycles=self.work_cycles + int(worked),
            idle_cycles=self.idle_cycles + int(not worked),
            retention_work=self.retention_work + int(retention),
            offline_work=self.offline_work + int(offline),
            plan_work=self.plan_work + int(plan),
            inference_work=self.inference_work + int(inference),
            recovery_holds=self.recovery_holds,
        )

    def append_recovery_hold(self) -> ConversationWorkerRunnerSummary:
        """Count a recovery-gated cycle without fabricating worker progress."""

        return ConversationWorkerRunnerSummary(
            cycles=self.cycles,
            work_cycles=self.work_cycles,
            idle_cycles=self.idle_cycles,
            retention_work=self.retention_work,
            offline_work=self.offline_work,
            plan_work=self.plan_work,
            inference_work=self.inference_work,
            recovery_holds=self.recovery_holds + 1,
        )


class ConversationWorkerRunner:
    """Serially poll the four dedicated conversation worker boundaries."""

    def __init__(
        self,
        retention: ConversationRetentionStep,
        offline_worker: ConversationOfflineRunOnce,
        plan_scheduler: ConversationPlanStep,
        inference_worker: ConversationInferenceRunOnce,
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
            or not _MIN_DELAY <= recovery_backoff <= _MAX_DELAY
        ):
            raise ValueError("Conversation worker runner delays must be bounded and ordered")
        for name, component, method_name in (
            ("retention", retention, "step"),
            ("offline worker", offline_worker, "run_once"),
            ("plan scheduler", plan_scheduler, "step"),
            ("inference worker", inference_worker, "run_once"),
        ):
            if not callable(getattr(component, method_name, None)):
                raise TypeError(f"Conversation worker runner requires a dedicated {name}")
        self.retention = retention
        self.offline_worker = offline_worker
        self.plan_scheduler = plan_scheduler
        self.inference_worker = inference_worker
        self.idle_min = idle_min
        self.idle_max = idle_max
        self.recovery_backoff = recovery_backoff
        self._admission = Lock()

    async def run(self, stop: asyncio.Event) -> ConversationWorkerRunnerSummary:
        """Poll complete serial cycles until an explicit stop is requested."""

        if not isinstance(stop, asyncio.Event):
            raise TypeError("Conversation worker runner stop must be an asyncio.Event")
        if not self._admission.acquire(blocking=False):
            raise RuntimeError("Conversation worker runner is already active")
        summary = ConversationWorkerRunnerSummary()
        idle = self.idle_min
        try:
            while not stop.is_set():
                try:
                    outcomes = await self._run_cycle(stop)
                except ReconciliationRequiredError:
                    summary = summary.append_recovery_hold()
                    if stop.is_set():
                        break
                    await self._wait_for_stop(stop, self.recovery_backoff)
                    idle = self.idle_min
                    continue
                summary = summary.append(outcomes)
                if stop.is_set():
                    break
                if any(outcomes):
                    idle = self.idle_min
                else:
                    await self._wait_for_stop(stop, idle)
                    idle = min(idle * 2, self.idle_max)
            return summary
        finally:
            self._admission.release()

    async def _run_cycle(self, stop: asyncio.Event) -> tuple[bool, bool, bool, bool]:
        """Run serial components, checking stop before each new admission."""

        retention = await self._owned_call(self.retention.step, "retention")
        if stop.is_set():
            return retention, False, False, False
        offline = await self._owned_call(self.offline_worker.run_once, "offline worker")
        if stop.is_set():
            return retention, offline, False, False
        plan = await self._owned_call(self.plan_scheduler.step, "plan scheduler")
        if stop.is_set():
            return retention, offline, plan, False
        inference = await self._owned_call(self.inference_worker.run_once, "inference worker")
        return retention, offline, plan, inference

    async def _owned_call(self, call: Callable[[], Awaitable[bool]], name: str) -> bool:
        async def invoke() -> bool:
            result = await call()
            if type(result) is not bool:
                raise TypeError(f"Conversation {name} returned an invalid result")
            return result

        owned = asyncio.create_task(invoke(), name=f"conversation-worker-runner-{name}")
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
                    owned.exception()
            raise

    @staticmethod
    async def _wait_for_stop(stop: asyncio.Event, delay: timedelta) -> None:
        with suppress(TimeoutError):
            await asyncio.wait_for(stop.wait(), timeout=delay.total_seconds())


__all__ = [
    "ConversationInferenceRunOnce",
    "ConversationOfflineRunOnce",
    "ConversationPlanStep",
    "ConversationRetentionStep",
    "ConversationWorkerRunner",
    "ConversationWorkerRunnerSummary",
]
