"""The event-loop watchdog names what blocked the loop, and stays quiet otherwise."""

from __future__ import annotations

import asyncio
import time

from structlog.testing import capture_logs

from ac_platform.application.loop_watchdog import LoopWatchdog


def _block_the_loop(seconds: float) -> None:
    time.sleep(seconds)  # synchronous on purpose: this is what the watchdog is for


async def _run(watchdog: LoopWatchdog, blocks: list[float]) -> None:
    watchdog.start()
    try:
        await asyncio.sleep(0.05)
        for seconds in blocks:
            _block_the_loop(seconds)
            await asyncio.sleep(0.08)
    finally:
        await watchdog.stop()


def _blocked(logs: list[dict[str, object]], event: str = "event_loop_blocked") -> list[dict]:
    # Only the test's own block: a slow runner may add a stall elsewhere.
    return [
        entry
        for entry in logs
        if entry["event"] == event and "in _block_the_loop" in str(entry["where"])
    ]


def test_a_block_over_the_threshold_is_named_by_file_line_and_function() -> None:
    with capture_logs() as logs:
        asyncio.run(_run(LoopWatchdog(threshold=0.05, interval=0.01), [0.3]))
    [warning] = _blocked(logs)
    assert warning["log_level"] == "warning"
    assert int(str(warning["lag_ms"])) >= 200
    where = str(warning["where"])
    assert where.startswith("tests/unit/application/test_loop_watchdog.py:"), where
    assert "in _block_the_loop" in where
    # Then the frames around it: which call led there.
    assert where.split(" < ")[1].endswith("in _run"), where
    assert warning["held_back"] == 0


def test_short_pauses_say_nothing_and_repeats_from_one_place_are_held_back() -> None:
    watchdog = LoopWatchdog(threshold=0.05, interval=0.01, every=60)
    with capture_logs() as logs:
        asyncio.run(_run(watchdog, [0.01, 0.2, 0.2, 0.2]))
    assert len(_blocked(logs)) == 1
    assert watchdog.held_back == 2


def test_a_loop_still_blocked_is_reported_before_it_comes_back() -> None:
    with capture_logs() as logs:
        asyncio.run(_run(LoopWatchdog(threshold=0.05, interval=0.01, still_after=0.15), [0.4]))
    [still] = _blocked(logs, "event_loop_still_blocked")
    assert int(str(still["blocked_ms"])) >= 150
    assert "in _block_the_loop" in str(still["where"])
    assert len(_blocked(logs)) == 1
