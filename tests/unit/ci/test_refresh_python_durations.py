from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.ci import refresh_python_durations as DURATIONS

SHA = "a" * 40


def receipt(root: Path, index: int, *, attempt: int = 1, seconds: str = "1.25") -> Path:
    directory = root / f"python-test-shard-{SHA}-{attempt}-{index}"
    directory.mkdir()
    paths = [f"tests/unit/test_file_{value}.py" for value in range(4)]
    (directory / "manifest.json").write_text(
        json.dumps(
            {
                "schema": "ac.ci.python-test-shard/1",
                "pytest_exit_code": 0,
                "environment_skips": [],
                "excluded": [],
                "shard_index": index,
                "shard_count": 4,
                "discovered": paths,
                "tests": [{"path": paths[index]}],
            }
        )
    )
    (directory / "junit.xml").write_text(
        f'<testsuites><testsuite><testcase classname="tests.unit.test_file_{index}.TestClass" '
        f'name="test_probe" time="{seconds}" /></testsuite></testsuites>'
    )
    return directory


def test_refresh_maps_test_classes_and_sums_only_latest_retry(tmp_path: Path) -> None:
    for index in range(4):
        receipt(tmp_path, index)
    receipt(tmp_path, 2, attempt=2, seconds="5.5")
    costs, source = DURATIONS.measured_costs(tmp_path, SHA)
    assert costs == {
        "tests/unit/test_file_0.py": 1.25,
        "tests/unit/test_file_1.py": 1.25,
        "tests/unit/test_file_2.py": 5.5,
        "tests/unit/test_file_3.py": 1.25,
    }
    assert source["sha"] == SHA
    assert [item["attempt"] for item in source["receipts"]] == [1, 1, 2, 1]


def test_incomplete_or_wrong_source_cannot_overwrite_measured_costs(tmp_path: Path) -> None:
    receipt(tmp_path, 0)
    with pytest.raises(DURATIONS.DurationError, match="complete"):
        DURATIONS.measured_costs(tmp_path, SHA)
    with pytest.raises(DURATIONS.DurationError, match="source SHA"):
        DURATIONS.measured_costs(tmp_path, "b" * 40)


@pytest.mark.parametrize("encoding", ["utf-8", "utf-16"])
def test_junit_entities_are_rejected_before_parsing(tmp_path: Path, encoding: str) -> None:
    for index in range(4):
        directory = receipt(tmp_path, index)
        if index == 0:
            (directory / "junit.xml").write_bytes(
                '<!DOCTYPE testsuites [<!ENTITY x "value">]><testsuites />'.encode(encoding)
            )
    with pytest.raises(DURATIONS.DurationError, match="DTD or entities|UTF-8"):
        DURATIONS.measured_costs(tmp_path, SHA)


@pytest.mark.parametrize("fault", ["failed", "missing-file", "excluded-file"])
def test_incomplete_or_failing_coverage_cannot_refresh_timings(tmp_path: Path, fault: str) -> None:
    directories = [receipt(tmp_path, index) for index in range(4)]
    path = directories[0] / "manifest.json"
    data = json.loads(path.read_text())
    if fault == "failed":
        data["pytest_exit_code"] = 1
    elif fault == "missing-file":
        for directory in directories:
            other = directory / "manifest.json"
            manifest = json.loads(other.read_text())
            manifest["discovered"].append("tests/unit/test_missing.py")
            other.write_text(json.dumps(manifest))
        data["discovered"].append("tests/unit/test_missing.py")
    else:
        data["excluded"] = [data["tests"][0]["path"]]
    path.write_text(json.dumps(data))
    with pytest.raises(DURATIONS.DurationError):
        DURATIONS.measured_costs(tmp_path, SHA)


@pytest.mark.parametrize("seconds", ["nan", "inf", "-1", "invalid", ""])
def test_invalid_timings_fail_closed(tmp_path: Path, seconds: str) -> None:
    for index in range(4):
        receipt(tmp_path, index, seconds=seconds if index == 0 else "1")
    with pytest.raises(DURATIONS.DurationError):
        DURATIONS.measured_costs(tmp_path, SHA)


def test_balancing_is_deterministic_and_never_drops_a_file() -> None:
    files = tuple(f"tests/unit/test_file_{index}.py" for index in range(40))
    costs = {path: float(index + 1) for index, path in enumerate(files)}
    assigned, loads = DURATIONS.balance(files, 4, costs, {path: 1.0 for path in files})
    assert DURATIONS.balance(tuple(reversed(files)), 4, costs, {path: 1.0 for path in files}) == (
        assigned,
        loads,
    )
    assert sorted(path for shard in assigned for path in shard) == sorted(files)
    assert max(loads) <= 1.15 * (sum(loads) / len(loads))


def test_new_files_keep_fallback_cost_instead_of_disappearing() -> None:
    old, new = "tests/unit/test_old.py", "tests/database/test_new.py"
    assigned, loads = DURATIONS.balance((old, new), 2, {old: 5.0}, {old: 1.0, new: 24.0})
    assert assigned == ((new,), (old,))
    assert loads == (24.0, 5.0)


@pytest.mark.parametrize("value", [True, 0, -1, float("nan"), float("inf"), "5"])
def test_duration_file_rejects_invalid_costs(tmp_path: Path, value: object) -> None:
    path = tmp_path / "durations.json"
    path.write_text(
        json.dumps(
            {
                "schema": DURATIONS.SCHEMA,
                "source": {"sha": SHA},
                "seconds_by_file": {"tests/unit/test_probe.py": value},
            }
        )
    )
    with pytest.raises(DURATIONS.DurationError):
        DURATIONS.read_durations(path)


@pytest.mark.parametrize("result", ["failure", "error"])
def test_junit_failure_cannot_refresh_even_with_successful_manifest(
    tmp_path: Path, result: str
) -> None:
    directories = [receipt(tmp_path, index) for index in range(4)]
    junit = directories[0] / "junit.xml"
    junit.write_text(junit.read_text().replace(" />", f"><{result} message='failed' /></testcase>"))
    with pytest.raises(DURATIONS.DurationError, match="passing JUnit"):
        DURATIONS.measured_costs(tmp_path, SHA)
