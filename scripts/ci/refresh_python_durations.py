#!/usr/bin/env python3
"""Refresh measured file costs from SHA-pinned Python-shard JUnit receipts."""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
import xml.etree.ElementTree as ET
from collections import defaultdict
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

SCHEMA = "ac.ci.python-durations/1"


class DurationError(ValueError):
    """Duration evidence is missing, malformed or not pinned to the requested source."""


def test_path(value: str) -> str:
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or ".." in path.parts
        or "\\" in value
        or not value.startswith("tests/")
        or path.suffix != ".py"
    ):
        raise DurationError("Duration paths must identify repository tests")
    return value


def validate_junit_input(path: Path) -> None:
    if path.stat().st_size > 32 * 1024 * 1024:
        raise DurationError("JUnit receipt exceeds the bounded input size")
    with path.open("rb") as stream:
        previous = b""
        while chunk := stream.read(65536):
            value = (previous + chunk).upper()
            if b"\0" in value:
                raise DurationError("JUnit receipt must use UTF-8 text")
            if b"<!DOCTYPE" in value or b"<!ENTITY" in value:
                raise DurationError("JUnit receipt cannot contain a DTD or entities")
            previous = value[-16:]


def measured_costs(
    root: Path, sha: str, shard_count: int = 4
) -> tuple[dict[str, float], dict[str, Any]]:
    if re.fullmatch(r"[0-9a-f]{40}", sha) is None or shard_count < 1:
        raise DurationError("An exact source SHA and positive shard count are required")
    pattern = re.compile(rf"python-test-shard-{sha}-([1-9][0-9]*)-([0-9]+)\Z")
    chosen: dict[int, tuple[int, Path]] = {}
    for directory in root.iterdir():
        if not directory.is_dir():
            continue
        match = pattern.fullmatch(directory.name)
        if not match:
            raise DurationError("Every shard evidence directory must match the source SHA")
        attempt, index = int(match[1]), int(match[2])
        if index >= shard_count:
            raise DurationError("Shard evidence index exceeds the configured shard count")
        if index not in chosen or attempt > chosen[index][0]:
            chosen[index] = (attempt, directory)
    if set(chosen) != set(range(shard_count)):
        raise DurationError("A complete set of shard receipts is required")
    costs: dict[str, float] = defaultdict(float)
    sources = []
    assigned: set[str] = set()
    discovered: set[str] | None = None
    excluded: set[str] | None = None
    for index, (attempt, directory) in sorted(chosen.items()):
        try:
            manifest = json.loads((directory / "manifest.json").read_text())
            if (
                manifest["schema"] != "ac.ci.python-test-shard/1"
                or type(manifest["pytest_exit_code"]) is not int
                or manifest["pytest_exit_code"] != 0
                or manifest["environment_skips"]
            ):
                raise DurationError("Only completed, passing shard receipts can refresh durations")
            if manifest["shard_index"] != index or manifest["shard_count"] != shard_count:
                raise DurationError("Manifest shard identity does not match its receipt")
            current_discovered = {test_path(path) for path in manifest["discovered"]}
            if discovered is not None and current_discovered != discovered:
                raise DurationError("Shard discovery differs between receipts")
            discovered = current_discovered
            current_excluded = {test_path(path) for path in manifest["excluded"]}
            if not current_excluded <= current_discovered or (
                excluded is not None and excluded != current_excluded
            ):
                raise DurationError("Shard exclusions differ or contain unknown test files")
            excluded = current_excluded
            paths = [test_path(item["path"]) for item in manifest["tests"]]
            if len(paths) != len(set(paths)) or assigned.intersection(paths):
                raise DurationError("A test file appears more than once in the chosen shard set")
            if not set(paths) <= current_discovered - current_excluded:
                raise DurationError("Shard assigns an unknown or separately gated test file")
            assigned.update(paths)
            modules = {path[:-3].replace("/", "."): path for path in paths}
            cases = 0
            measured_files = set()
            junit = directory / "junit.xml"
            validate_junit_input(junit)
            for _, element in ET.iterparse(junit, events=("end",)):  # noqa: S314 - bounded, DTD-free
                if element.tag in {"failure", "error"}:
                    raise DurationError("Only passing JUnit receipts can refresh durations")
                if element.tag != "testcase":
                    element.clear()
                    continue
                candidate = element.get("classname", "")
                while candidate and candidate not in modules:
                    candidate = candidate.rpartition(".")[0]
                if candidate not in modules:
                    raise DurationError("JUnit testcase cannot be mapped to its assigned test file")
                seconds = float(element.get("time", ""))
                if not math.isfinite(seconds) or seconds < 0:
                    raise DurationError("Testcase durations must be finite and nonnegative")
                path = modules[candidate]
                costs[path] += seconds
                measured_files.add(path)
                cases += 1
                element.clear()
            if not cases:
                raise DurationError("Shard JUnit receipt contains no testcases")
            sources.append(
                {
                    "shard": index,
                    "attempt": attempt,
                    "testcases": cases,
                    "measured_files": len(measured_files),
                    "junit": junit.relative_to(root).as_posix(),
                }
            )
        except (KeyError, TypeError, ValueError, OSError, ET.ParseError) as error:
            if isinstance(error, DurationError):
                raise
            raise DurationError("Shard duration receipt could not be validated") from None
    if assigned != (discovered or set()) - (excluded or set()):
        raise DurationError("Shard receipts do not cover every discovered, non-gated test file")
    # Preserve very short tests with a positive floor, not zero scheduling cost.
    return {path: max(0.001, round(seconds, 6)) for path, seconds in sorted(costs.items())}, {
        "sha": sha,
        "shard_count": shard_count,
        "receipts": sources,
        "assigned_files": len(assigned),
        "measured_files": len(costs),
    }


def read_durations(path: Path) -> dict[str, float]:
    try:
        document = json.loads(path.read_text())
        if (
            document["schema"] != SCHEMA
            or re.fullmatch(r"[0-9a-f]{40}", document["source"]["sha"]) is None
        ):
            raise DurationError("Measured durations need a schema and exact source SHA")
        costs = document["seconds_by_file"]
        if not isinstance(costs, dict) or not costs:
            raise DurationError("Measured durations need file costs")
        result = {}
        for relative, seconds in costs.items():
            test_path(relative)
            if type(seconds) not in (int, float) or not math.isfinite(seconds) or seconds <= 0:
                raise DurationError("Measured file costs must be positive finite numbers")
            result[relative] = float(seconds)
        return result
    except (KeyError, TypeError, ValueError, OSError) as error:
        if isinstance(error, DurationError):
            raise
        raise DurationError("Measured durations could not be read") from None


def balance(
    files: Sequence[str],
    count: int,
    measured: Mapping[str, float],
    fallback: Mapping[str, float],
) -> tuple[tuple[tuple[str, ...], ...], tuple[float, ...]]:
    if count < 1 or not files or len(set(files)) != len(files):
        raise DurationError("Shard inputs need unique test files and a positive shard count")
    costs = {path: measured.get(path, fallback[path]) for path in files}
    if any(not math.isfinite(cost) or cost <= 0 for cost in costs.values()):
        raise DurationError("Every scheduled file needs a positive finite cost")
    assigned: list[list[str]] = [[] for _ in range(count)]
    loads = [0.0] * count
    for path in sorted(files, key=lambda value: (-costs[value], value)):
        index = min(range(count), key=lambda value: (loads[value], value))
        assigned[index].append(path)
        loads[index] += costs[path]
    return tuple(tuple(sorted(paths)) for paths in assigned), tuple(loads)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence-dir", type=Path, required=True)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--shard-count", type=int, default=4)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        costs, source = measured_costs(args.evidence_dir, args.source_sha, args.shard_count)
        document = {
            "schema": SCHEMA,
            "generated_at": datetime.now(UTC).isoformat(),
            "source": source,
            "seconds_by_file": costs,
        }
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n")
    except DurationError as error:
        print(f"Duration refresh refused: {error}", file=sys.stderr)
        return 1
    print(f"Measured {len(costs)} test files from {args.shard_count} SHA-pinned shard receipts")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
