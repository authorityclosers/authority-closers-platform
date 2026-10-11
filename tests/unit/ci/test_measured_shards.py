from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pytest

from scripts.ci import python_test_shard as shard

SHA = "a" * 40


@pytest.fixture
def measured_set(tmp_path: Path):
    files = tuple(f"tests/unit/test_file_{index}.py" for index in range(40))
    for path in files:
        target = tmp_path / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("def test_fixture():\n    assert True\n")
    duration = tmp_path / "scripts/ci/python-test-durations.json"
    duration.parent.mkdir(parents=True)
    duration.write_text(
        json.dumps(
            {
                "schema": "ac.ci.python-durations/1",
                "source": {"sha": SHA},
                "seconds_by_file": {path: float(index + 1) for index, path in enumerate(files)},
            }
        )
    )
    exclusions = tmp_path / "exclusions.txt"
    exclusions.write_text("")
    costs, source = shard.duration_evidence(duration)
    assigned = shard.assign_shards(files, 4, costs)
    manifests = tmp_path / "manifests"
    for index in range(4):
        manifest = shard._manifest(
            root=tmp_path,
            shard_index=index,
            shard_count=4,
            excluded=(),
            assigned=assigned[index],
            measured=costs,
            duration_source=source,
        )
        path = manifests / f"python-test-shard-{SHA}-1-{index}" / "manifest.json"
        shard._write_manifest(path, manifest)
    return tmp_path, files, duration, costs, source, assigned, manifests, exclusions


def test_measured_assignment_preserves_complete_coverage_and_bound(measured_set) -> None:
    _, files, _, costs, _, assigned, _, _ = measured_set
    loads = [sum(costs[path] for path in group) for group in assigned]
    assert max(loads) <= 1.15 * (sum(loads) / len(loads))
    assert sorted(path for group in assigned for path in group) == sorted(files)
    assert assigned == shard.assign_shards(tuple(reversed(files)), 4, costs)


def test_pinned_measured_manifests_pass_existing_coverage_proof(measured_set) -> None:
    root, _, _, _, _, _, manifests, exclusions = measured_set
    assert shard.verify_manifests(manifests, root, 4, exclusions, sha=SHA, run_attempt=1) == {
        0: 1,
        1: 1,
        2: 1,
        3: 1,
    }


@pytest.mark.parametrize("fault", ["source", "cost", "total", "duplicate"])
def test_measured_evidence_tampering_and_duplicate_assignment_fail(measured_set, fault) -> None:
    root, _, _, _, _, _, manifests, exclusions = measured_set
    path = manifests / f"python-test-shard-{SHA}-1-0" / "manifest.json"
    data = json.loads(path.read_text())
    if fault == "source":
        data["duration_source"]["file_sha256"] = "b" * 64
    elif fault == "cost":
        data["tests"][0]["estimated_seconds"] += 1
    elif fault == "total":
        data["assigned_estimated_seconds"] += 1
    else:
        data["tests"].append(data["tests"][0])
    path.write_text(json.dumps(data))
    with pytest.raises(shard.ShardConfigurationError):
        shard.verify_manifests(manifests, root, 4, exclusions, sha=SHA, run_attempt=1)


def test_runner_uses_measured_manifest_and_keeps_every_assigned_test(
    measured_set, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, _, duration, costs, source, assigned, _, exclusions = measured_set
    commands = []

    def run(argv, **kwargs):
        commands.append(argv)
        return argparse.Namespace(returncode=0)

    monkeypatch.setattr(shard.subprocess, "run", run)
    args = argparse.Namespace(
        root=root,
        exclude_file=exclusions,
        duration_file=duration,
        shard_count=4,
        shard_index=0,
        manifest=root / "run-manifest.json",
        junitxml=None,
        basetemp=None,
    )
    assert shard.run_shard(args) == 0
    assert commands == [[sys.executable, "-m", "pytest", *assigned[0], "-r", "s"]]
    receipt = json.loads(args.manifest.read_text())
    assert receipt["duration_source"] == source
    assert receipt["assigned_estimated_seconds"] == sum(costs[path] for path in assigned[0])


def test_missing_duration_evidence_is_a_configuration_error(tmp_path: Path) -> None:
    with pytest.raises(shard.ShardConfigurationError, match="duration evidence"):
        shard.duration_evidence(tmp_path / "missing.json")
