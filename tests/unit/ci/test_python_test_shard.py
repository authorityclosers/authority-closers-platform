from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

# Pytest's importlib mode does not add the repository root to ``sys.path``.
ROOT = Path(__file__).parents[3]
sys.path.insert(0, str(ROOT))

import scripts.ci.python_test_shard as shard  # noqa: E402


def _write_test_file(root: Path, relative_path: str) -> None:
    path = root / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("def test_placeholder():\n    assert True\n", encoding="utf-8")


def _write_manifest(
    path: Path,
    *,
    index: int,
    count: int,
    discovered: tuple[str, ...],
    assigned: tuple[str, ...],
    excluded: tuple[str, ...],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "schema": "ac.ci.python-test-shard/1",
                "root": "tests",
                "shard_index": index,
                "shard_count": count,
                "discovered": list(discovered),
                "excluded": list(excluded),
                "tests": [
                    {"path": item, "weight": shard.test_weight(item), "shard": index}
                    for item in assigned
                ],
                "assigned_weight": sum(shard.test_weight(item) for item in assigned),
            }
        ),
        encoding="utf-8",
    )


def test_weighted_assignment_is_stable_and_prioritises_database() -> None:
    files = (
        "tests/unit/test_small.py",
        "tests/database/test_large.py",
        "tests/integration/test_medium.py",
        "tests/infra/test_boundary.py",
    )
    first = shard.assign_shards(files, 2)
    assert first == shard.assign_shards(files, 2)
    assert shard.test_weight("tests/database/test_large.py") > shard.test_weight(
        "tests/unit/test_small.py"
    )
    assert sorted(path for shard in first for path in shard) == sorted(files)


def test_verifier_rejects_missing_or_duplicate_future_test_file(tmp_path: Path) -> None:
    _write_test_file(tmp_path, "tests/unit/test_existing.py")
    _write_test_file(tmp_path, "tests/database/test_database.py")
    _write_test_file(tmp_path, "tests/unit/test_new_future_file.py")
    exclusion_file = tmp_path / "exclusions.txt"
    exclusion_file.write_text("", encoding="utf-8")
    discovered = shard.discover_test_files(tmp_path)
    assignments = shard.assign_shards(discovered, 2)
    for index, assigned in enumerate(assignments):
        _write_manifest(
            tmp_path / "manifests" / str(index) / "manifest.json",
            index=index,
            count=2,
            discovered=discovered,
            assigned=assigned,
            excluded=(),
        )
    shard.verify_manifests(tmp_path / "manifests", tmp_path, 2, exclusion_file)

    duplicate = json.loads((tmp_path / "manifests" / "1" / "manifest.json").read_text())
    duplicate["tests"].append(duplicate["tests"][0])
    (tmp_path / "manifests" / "1" / "manifest.json").write_text(json.dumps(duplicate))
    with pytest.raises(shard.ShardConfigurationError, match="more than one shard"):
        shard.verify_manifests(tmp_path / "manifests", tmp_path, 2, exclusion_file)


def test_junit_dependency_skips_are_recorded_for_fail_closed_ci(tmp_path: Path) -> None:
    receipt = tmp_path / "junit.xml"
    receipt.write_text(
        '<testsuite><testcase><skipped message="'
        'ffmpeg/ffprobe missing; no codec validation claimed" />'
        "</testcase></testsuite>",
        encoding="utf-8",
    )
    assert shard._parse_junit_skips(receipt) == (
        "ffmpeg/ffprobe missing; no codec validation claimed",
    )
