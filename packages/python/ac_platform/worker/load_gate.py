"""Admission before background claims; accepted leases always finish unchanged."""

from __future__ import annotations

import asyncio
import json
import math
import os
import time
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class LoadGateConfig:
    cpus: int = 2
    max_load_per_cpu: float = 0.75
    max_steal_fraction: float = 0.10
    min_credit_percent: float = 30.0
    credit_file: Path | None = None
    credit_max_age_seconds: float = 180.0
    poll_seconds: float = 5.0

    def __post_init__(self) -> None:
        if type(self.cpus) is not int or self.cpus < 1:
            raise ValueError("load_gate_invalid_cpu_count")
        for value in (
            self.max_load_per_cpu,
            self.max_steal_fraction,
            self.min_credit_percent,
            self.credit_max_age_seconds,
            self.poll_seconds,
        ):
            if not math.isfinite(value) or value <= 0:
                raise ValueError("load_gate_invalid_threshold")
        if self.max_steal_fraction > 1 or self.min_credit_percent > 100:
            raise ValueError("load_gate_invalid_threshold")


def admits_background(
    config: LoadGateConfig,
    *,
    load_one: float,
    steal_fraction: float,
    credit_percent: float | None = None,
) -> bool:
    """Missing/invalid telemetry fails closed; a disabled credit feed is optional."""
    if not all(math.isfinite(v) and v >= 0 for v in (load_one, steal_fraction)):
        return False
    if load_one / config.cpus >= config.max_load_per_cpu:
        return False
    if steal_fraction >= config.max_steal_fraction:
        return False
    if config.credit_file is not None:
        return (
            credit_percent is not None
            and math.isfinite(credit_percent)
            and config.min_credit_percent <= credit_percent <= 100
        )
    return True


class LoadGate:
    def __init__(
        self,
        config: LoadGateConfig | None = None,
        *,
        proc_stat: Path = Path("/proc/stat"),
        clock: Callable[[], float] = time.time,
        load_average: Callable[[], tuple[float, float, float]] = os.getloadavg,
    ) -> None:
        self.config = config or LoadGateConfig()
        self.proc_stat = proc_stat
        self.clock = clock
        self.load_average = load_average
        self._previous_cpu: tuple[int, int] | None = None

    def _credit(self) -> float | None:
        path = self.config.credit_file
        if path is None:
            return None
        # A local exporter writes atomic, content-free observations. No AWS call.
        with path.open("rb") as stream:
            raw = stream.read(4097)
        if len(raw) > 4096:
            return None
        value = json.loads(raw)
        balance, observed = value["balance_percent"], value["observed_at"]
        if type(balance) not in (int, float) or type(observed) not in (int, float):
            return None
        age = self.clock() - observed
        if not math.isfinite(age) or not 0 <= age <= self.config.credit_max_age_seconds:
            return None
        return float(balance)

    def green(self) -> bool:
        try:
            with self.proc_stat.open() as stream:
                values = [int(v) for v in stream.readline().split()[1:9]]
            if len(values) != 8 or any(v < 0 for v in values):
                return False
            current = (sum(values), values[7])  # guest time already counts in user/nice
            previous, self._previous_cpu = self._previous_cpu, current
            if previous is None:
                return False  # prime a delta, never use a boot-lifetime average
            total, stolen = current[0] - previous[0], current[1] - previous[1]
            if total <= 0 or not 0 <= stolen <= total:
                return False
            return admits_background(
                self.config,
                load_one=self.load_average()[0],
                steal_fraction=stolen / total,
                credit_percent=self._credit(),
            )
        except (OSError, ValueError, KeyError, TypeError, IndexError):
            return False

    async def wait(self, stop: asyncio.Event) -> bool:
        while not stop.is_set():
            if self.green():
                return True
            with suppress(TimeoutError):
                await asyncio.wait_for(stop.wait(), timeout=self.config.poll_seconds)
        return False


def worker_job_limit(value: str | None) -> int:
    """Zero preserves existing unlimited worker behavior outside the lean profile."""
    limit = int(value or "0")
    if not 0 <= limit <= 100_000:
        raise ValueError("worker_job_limit_invalid")
    return limit
