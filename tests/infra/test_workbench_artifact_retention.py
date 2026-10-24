"""Workbench storage policy keeps coverage proofs and bounds diagnostic lifetime."""

from __future__ import annotations

import fnmatch
import json
import os
import shutil
import subprocess
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


def summary_step(predicate) -> dict:
    return next(step for step in JOBS["summary"]["steps"] if predicate(step))


def test_each_run_folds_its_shard_manifests_into_one_artifact() -> None:
    """24 Oct 2026: per-shard artifacts expired about once a minute and moved Root's inventory."""
    steps = JOBS["summary"]["steps"]
    fold = summary_step(
        lambda step: step.get("uses", "").startswith("actions/upload-artifact/merge@")
    )
    download = summary_step(lambda step: step.get("uses", "").startswith("actions/download"))
    assert steps.index(fold) < steps.index(download)
    assert fold["uses"].split("@", 1)[1] == UPLOADS[0]["uses"].split("@", 1)[1]
    assert fold["with"]["retention-days"] == 1
    assert fold["with"]["delete-merged"] is True
    assert fold["with"]["separate-directories"] is True
    assert fold["with"]["pattern"] == "wb-py-[ab]-${{ github.sha }}-${{ github.run_attempt }}-*"
    # The summary still downloads the folded artifact; a failed fold leaves the shards in place.
    assert fnmatch.fnmatchcase(fold["with"]["name"], download["with"]["pattern"])
    assert fold["continue-on-error"] is True
    assert fold["if"] == download["if"]


def test_verify_reads_folded_and_unfolded_shard_folders(tmp_path: Path) -> None:
    verify = summary_step(lambda step: step.get("id") == "verify")
    sha = "a" * 40
    script = (
        verify["run"].replace("${{ github.sha }}", sha).replace("${{ github.run_attempt }}", "1")
    )
    downloaded = tmp_path / "wb-py"
    folded = downloaded / f"wb-py-shards-{sha}-1" / f"wb-py-b-{sha}-1-0"
    unfolded = downloaded / f"wb-py-a-{sha}-1-0"
    for directory in (folded, unfolded):
        directory.mkdir(parents=True)
        (directory / "manifest.json").write_text("{}")
    tools = tmp_path / "bin"
    tools.mkdir()
    (tools / "python3").write_text("#!/bin/sh\nexit 0\n")
    (tools / "python3").chmod(0o755)
    environment = {
        **os.environ,
        "PATH": f"{tools}{os.pathsep}{os.environ['PATH']}",
        "RUNNER_TEMP": str(tmp_path),
        "GITHUB_WORKSPACE": str(tmp_path),
        "COUNT_A": "1",
        "COUNT_B": "1",
    }
    subprocess.run(["bash", "-c", script], check=True, env=environment)  # noqa: S603, S607
    for family in ("a", "b"):
        manifest = tmp_path / f"verify-{family}" / f"python-test-shard-{sha}-1-0" / "manifest.json"
        assert manifest.is_file()
