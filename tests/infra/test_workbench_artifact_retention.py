"""Workbench storage policy keeps coverage proofs and bounds diagnostic lifetime."""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.ci import python_test_shard as shard  # noqa: E402

JOBS = yaml.safe_load((ROOT / ".github/workflows/workbench-checks.yml").read_text())["jobs"]
UPLOADS = [
    step
    for job in JOBS.values()
    for step in job["steps"]
    if step.get("uses", "").startswith("actions/upload-artifact@")
]
SHARD_UPLOADS = [step for step in UPLOADS if step["with"]["name"].startswith("wb-py-")]


def test_all_workbench_uploads_expire_after_one_day() -> None:
    assert len(UPLOADS) == 4  # coverage summaries, failed shards, screenshots and e2e
    assert all(step["with"]["retention-days"] == 1 for step in UPLOADS)


def test_green_shards_publish_only_required_coverage_summaries() -> None:
    green = next(step for step in SHARD_UPLOADS if "success()" in step["if"])
    assert green["if"] == "success() && matrix.fam != 'targeted'"
    assert green["with"]["path"].endswith("/manifest.json")
    assert "*" not in green["with"]["path"]
    assert green["with"]["if-no-files-found"] == "error"
    assert not green.get("continue-on-error")


def test_failed_shards_keep_diagnostics_with_the_same_coverage_identity() -> None:
    green, failed = SHARD_UPLOADS
    assert failed["if"] == "failure() || cancelled()"
    assert failed["with"]["name"] == green["with"]["name"]
    assert green["with"]["path"] == failed["with"]["path"] + "/manifest.json"
    steps = JOBS["summary"]["steps"]
    download = next(step for step in steps if step.get("uses", "").startswith("actions/download"))
    assert download["with"]["pattern"] == "wb-py-*-${{ github.sha }}-*"
    verify = next(step for step in steps if step.get("id") == "verify")
    assert "python_test_shard.py verify" in verify["run"]
    assert '--sha "${{ github.sha }}"' in verify["run"]
    assert '--run-attempt "${{ github.run_attempt }}"' in verify["run"]


def test_manifest_only_payload_still_proves_complete_shard_coverage(tmp_path: Path) -> None:
    tests = tmp_path / "tests"
    tests.mkdir()
    for name in ("a", "b"):
        (tests / f"test_{name}.py").write_text("def test_fictional(): pass\n")
    excluded = tmp_path / "exclusions.txt"
    excluded.write_text("")
    discovered = shard.discover_test_files(tmp_path)
    assignments = shard.assign_shards(discovered, 2)
    green = SHARD_UPLOADS[0]
    manifests = tmp_path / "downloaded"
    sha = "a" * 40
    for index, assigned in enumerate(assignments):
        payload = green["with"]["path"].replace("${{ runner.temp }}", str(tmp_path))
        source = Path(payload.replace("${{ matrix.shard }}", str(index)))
        source.parent.mkdir(parents=True)
        source.write_text(
            json.dumps(
                {
                    "schema": shard.SCHEMA,
                    "shard_index": index,
                    "shard_count": 2,
                    "discovered": discovered,
                    "excluded": [],
                    "tests": [
                        {"path": path, "weight": shard.test_weight(path), "shard": index}
                        for path in assigned
                    ],
                }
            )
        )
        (source.parent / "junit.xml").write_text("fictional detailed diagnostics")
        destination = manifests / f"python-test-shard-{sha}-2-{index}"
        destination.mkdir(parents=True)
        shutil.copy2(source, destination / source.name)
    assert not list(manifests.rglob("junit.xml"))
    assert shard.verify_manifests(manifests, tmp_path, 2, excluded, sha=sha, run_attempt=2) == {
        0: 2,
        1: 2,
    }
