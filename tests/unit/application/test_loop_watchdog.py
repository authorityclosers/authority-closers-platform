"""The event-loop watchdog names what blocked the loop, and stays quiet otherwise."""

from __future__ import annotations

import asyncio
import gc
import time
from collections.abc import Callable
from pathlib import Path

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


# 26 Oct 2026: production stalled 3.7 s with where=unknown, and nothing could say why.


def _slow_full_collection(seconds: float) -> Callable[[str, dict[str, int]], None]:
    def pause(phase: str, info: dict[str, int]) -> None:
        if phase == "start" and info["generation"] == 2:
            time.sleep(seconds)

    return pause


async def _collect(watchdog: LoopWatchdog, seconds: float) -> None:
    watchdog.start()
    # After the watchdog's own callback, so the pause falls inside the collection it times.
    pause = _slow_full_collection(seconds)
    gc.callbacks.append(pause)
    try:
        await asyncio.sleep(0.05)
        gc.collect()
        await asyncio.sleep(0.08)
    finally:
        gc.callbacks.remove(pause)
        await watchdog.stop()


def test_a_long_collection_is_named_as_the_garbage_collector() -> None:
    callbacks = list(gc.callbacks)
    with capture_logs() as logs:
        asyncio.run(_collect(LoopWatchdog(threshold=0.05, interval=0.01), 0.3))
    stalls = [
        entry
        for entry in logs
        if entry["event"] == "event_loop_blocked" and entry["where"] == "gc generation 2"
    ]
    assert stalls, logs
    assert int(str(stalls[0]["gc_ms"])) >= 250
    pauses = [entry for entry in logs if entry["event"] == "gc_pause"]
    assert any(entry["generation"] == 2 and int(str(entry["ms"])) >= 250 for entry in pauses)
    # The watchdog leaves the collector as it found it.
    assert gc.callbacks == callbacks


def test_only_a_stall_past_dump_after_writes_every_threads_stack(tmp_path: Path) -> None:
    stalled = tmp_path / "stalled.txt"
    with stalled.open("w") as dump, capture_logs() as logs:
        asyncio.run(
            _run(
                LoopWatchdog(threshold=0.05, interval=0.01, dump_after=0.6, dump_to=dump),
                [1.0],
            )
        )
    text = stalled.read_text()
    assert "Timeout (" in text
    assert "in _block_the_loop" in text
    [warning] = _blocked(logs)
    assert warning["stacks_dumped"] is True

    # Running well for longer than dump_after keeps pushing the dump back.
    quiet = tmp_path / "quiet.txt"
    with quiet.open("w") as dump:
        asyncio.run(
            _run(
                LoopWatchdog(threshold=0.05, interval=0.01, dump_after=0.6, dump_to=dump),
                [0.01] * 12,
            )
        )
    assert quiet.read_text() == ""
