"""No host load, external provider or cloud account is used by these tests."""

import asyncio
import json
from pathlib import Path

import pytest

from ac_platform.worker.load_gate import LoadGate, LoadGateConfig, admits_background


@pytest.mark.parametrize(
    "load,steal,expected",
    [
        (0.1, 0.0, True),
        (1.49, 0.09, True),
        (1.5, 0, False),
        (0.1, 0.1, False),
        (float("nan"), 0, False),
        (0, float("inf"), False),
        (-1, 0, False),
        (0, -1, False),
    ],
)
def test_load_and_steal(load: float, steal: float, expected: bool) -> None:
    assert admits_background(LoadGateConfig(), load_one=load, steal_fraction=steal) is expected


@pytest.mark.parametrize(
    "credit,expected",
    [(None, False), (29, False), (30, True), (100, True), (101, False), (float("nan"), False)],
)
def test_optional_credit_is_fail_closed(credit: float | None, expected: bool) -> None:
    config = LoadGateConfig(credit_file=Path("/fictional/credit.json"))
    assert (
        admits_background(config, load_one=0, steal_fraction=0, credit_percent=credit) is expected
    )


def _stat(path: Path, *, user: int, stolen: int) -> None:
    path.write_text(f"cpu {user} 0 0 0 0 0 0 {stolen} 0 0\n")


def test_steal_uses_deltas_and_rejects_resets(tmp_path: Path) -> None:
    path = tmp_path / "stat"
    _stat(path, user=1000, stolen=100)
    gate = LoadGate(proc_stat=path, load_average=lambda: (0, 0, 0))
    assert not gate.green()  # first observation only primes delta
    _stat(path, user=1100, stolen=100)
    assert gate.green()
    _stat(path, user=1100, stolen=200)
    assert not gate.green()  # newly stolen interval despite low lifetime average
    _stat(path, user=1, stolen=0)
    assert not gate.green()


@pytest.mark.parametrize(
    "contents",
    [
        None,
        "{}",
        "not json",
        "x" * 4097,
        '{"balance_percent": 80, "observed_at": 0}',
        '{"balance_percent": 80, "observed_at": 1001}',
        '{"balance_percent": true, "observed_at": 1000}',
    ],
)
def test_missing_stale_future_malformed_credit_pauses(tmp_path: Path, contents: str | None) -> None:
    credit = tmp_path / "credit.json"
    if contents is not None:
        credit.write_text(contents)
    stat = tmp_path / "stat"
    _stat(stat, user=100, stolen=0)
    gate = LoadGate(
        LoadGateConfig(credit_file=credit),
        proc_stat=stat,
        clock=lambda: 1000,
        load_average=lambda: (0, 0, 0),
    )
    assert not gate.green()
    _stat(stat, user=200, stolen=0)
    assert not gate.green()
    credit.write_text(json.dumps({"balance_percent": 80, "observed_at": 1000}))
    _stat(stat, user=300, stolen=0)
    assert gate.green()


async def test_red_gate_wait_can_stop_without_claiming(tmp_path: Path) -> None:
    gate = LoadGate(proc_stat=tmp_path / "missing", config=LoadGateConfig(poll_seconds=0.01))
    stop = asyncio.Event()
    task = asyncio.create_task(gate.wait(stop))
    await asyncio.sleep(0)
    assert not task.done()
    stop.set()
    assert not await task
