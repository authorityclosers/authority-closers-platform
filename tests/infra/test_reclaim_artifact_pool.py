from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "infra/release/reclaim-artifact-pool.py"
SPEC = importlib.util.spec_from_file_location("reclaim_artifact_pool", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
POOL = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(POOL)
CEILING = 2_000_000_000
CURRENT_SHA = "f" * 40


def artifact(
    identity: int, size: int, *, family: str = "sales-xray-visual", branch: str = "task/closed"
) -> dict[str, Any]:
    sha = f"{identity:040x}"
    name = f"{family}-{sha}" + ("-1" if family == "sales-xray-visual" else "")
    return {
        "id": identity,
        "name": name,
        "size_in_bytes": size,
        "expired": False,
        "created_at": f"2026-10-05T00:{identity:02d}:00Z",
        "workflow_run": {
            "head_branch": branch,
            "head_sha": sha,
            "head_repository_id": 1,
            "repository_id": 1,
        },
    }


def pull(*, state: str = "closed", branch: str = "task/closed", sha: str = "a" * 40) -> dict:
    return {
        "state": state,
        "head": {"ref": branch, "sha": sha, "repo": {"id": 1}},
        "closed_at": "2026-10-05T01:00:00Z" if state == "closed" else None,
        "merged_at": None,
        "merge_commit_sha": None,
    }


class FixtureGitHub:
    def __init__(self, artifacts: list[dict], pulls: list[dict]) -> None:
        self.pool = artifacts.copy()
        self.prs = pulls
        self.deleted: list[int] = []
        self.reopened: list[dict] = []
        self.delete_fails = False
        self.stale_inventory = False
        self.concurrent_artifact: dict | None = None

    def artifacts(self) -> list[dict]:
        return self.pool.copy()

    def pulls(self, state: str) -> list[dict]:
        return self.prs if state == "all" else [*self.prs, *self.reopened]

    def api(self, path: str, *, delete: bool) -> None:
        assert delete
        identity = int(path.rsplit("/", 1)[1])
        if self.delete_fails:
            raise ValueError("GitHub metadata request failed")
        self.deleted.append(identity)
        if not self.stale_inventory:
            self.pool = [item for item in self.pool if item["id"] != identity]
        if self.concurrent_artifact:
            self.pool.append(self.concurrent_artifact)
            self.concurrent_artifact = None


@pytest.fixture(autouse=True)
def fictional_source(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GITHUB_SHA", CURRENT_SHA)
    monkeypatch.setenv("FROZEN_SHA", CURRENT_SHA)


def test_visual_only_excess_reclaims_oldest_until_admitted() -> None:
    github = FixtureGitHub(
        [artifact(3, 100_000_000), artifact(2, 100_000_000), artifact(1, 100_000_000)],
        [pull()],
    )
    assert POOL.reclaim(github, 1_900_000_000, CEILING, None) == CEILING
    assert github.deleted == [1, 2]
    assert [item["id"] for item in github.pool] == [3]


def test_mixed_families_are_reclaimed_in_one_oldest_first_order() -> None:
    github = FixtureGitHub(
        [artifact(3, 100), artifact(1, 100, family="ac-sales-xray-web"), artifact(2, 100)],
        [pull()],
    )
    assert POOL.reclaim(github, CEILING - 100, CEILING, None) == CEILING
    assert github.deleted == [1, 2]


@pytest.mark.parametrize("by_sha", [False, True])
def test_open_pr_protection_overrides_closed_branch_history(by_sha: bool) -> None:
    item = artifact(1, 200_000_000)
    opened = pull(state="open", branch="new-branch" if by_sha else "task/closed")
    if by_sha:
        opened["head"]["sha"] = f"{1:040x}"
    github = FixtureGitHub([item], [pull(), opened])
    assert POOL.reclaim(github, 1_900_000_000, CEILING, None) == 2_100_000_000
    assert github.deleted == []


def test_reopened_branch_is_protected_at_delete_time() -> None:
    github = FixtureGitHub([artifact(1, 200_000_000)], [pull()])
    github.reopened = [pull(state="open")]
    assert POOL.reclaim(github, 1_900_000_000, CEILING, None) > CEILING
    assert github.deleted == []


def test_application_native_and_unknown_provenance_are_never_reclaimed() -> None:
    github = FixtureGitHub(
        [
            artifact(1, 600_000_000, family="ac-application"),
            artifact(2, 600_000_000, family="ac-sales-xray-native"),
            artifact(3, 300_000_000, branch="unknown"),
            artifact(4, 100_000_000),
        ],
        [pull()],
    )
    assert POOL.reclaim(github, 600_000_001, CEILING, None) == 2_100_000_001
    assert github.deleted == [4]
    assert [item["id"] for item in github.pool] == [1, 2, 3]


def test_latest_main_and_current_source_are_preserved() -> None:
    old, latest = artifact(1, 100, branch="main"), artifact(2, 100, branch="main")
    closed = pull()
    closed.update(merged_at=closed["closed_at"], merge_commit_sha=f"{1:040x}")
    current = artifact(3, 100)
    current["name"] = f"sales-xray-visual-{CURRENT_SHA}-1"
    github = FixtureGitHub([latest, current, old], [closed])
    assert POOL.reclaim(github, CEILING - 100, CEILING, None) == CEILING + 100
    assert github.deleted == [1]


def test_newer_reused_branch_is_not_proved_closed() -> None:
    item = artifact(1, 200_000_000)
    item["created_at"] = "2026-10-05T02:00:00Z"
    github = FixtureGitHub([item], [pull()])
    assert POOL.reclaim(github, 1_900_000_000, CEILING, None) > CEILING
    assert github.deleted == []


def test_existing_replacement_credit_is_not_subtracted_twice() -> None:
    github = FixtureGitHub(
        [artifact(1, 200_000_000, family="ac-sales-xray-web"), artifact(2, 200_000_000)],
        [pull()],
    )
    assert POOL.reclaim(github, 1_900_000_000, CEILING, "ac-sales-xray-web") == 1_900_000_000
    assert github.deleted == [2]


@pytest.mark.parametrize("failure", ["delete_fails", "stale_inventory"])
def test_failed_or_unverified_delete_never_admits(failure: str) -> None:
    github = FixtureGitHub([artifact(1, 200_000_000)], [pull()])
    setattr(github, failure, True)
    with pytest.raises(ValueError):
        POOL.reclaim(github, 1_900_000_000, CEILING, None)


def test_inventory_readback_counts_concurrent_uploads() -> None:
    github = FixtureGitHub([artifact(1, 200_000_000)], [pull()])
    github.concurrent_artifact = artifact(2, 200_000_000, family="ac-application")
    assert POOL.reclaim(github, 1_900_000_000, CEILING, None) == 2_100_000_000
    assert github.deleted == [1]


def test_under_ceiling_does_not_reclaim() -> None:
    github = FixtureGitHub([artifact(1, 100)], [pull()])
    assert POOL.reclaim(github, CEILING - 100, CEILING, None) == CEILING
    assert github.deleted == []


@pytest.mark.parametrize(
    "response",
    [None, {}, [], [{}], [{"artifacts": [1]}], [{"artifacts": [artifact(1, -1)]}]],
)
def test_unproven_inventory_refuses_before_deleting(
    monkeypatch: pytest.MonkeyPatch, response: object
) -> None:
    github = POOL.GitHub("fixture/repository")
    monkeypatch.setattr(github, "api", lambda *args, **kwargs: response)
    with pytest.raises((ValueError, TypeError, KeyError)):
        POOL.reclaim(github, CEILING, CEILING, None)


@pytest.mark.parametrize("response", [None, {}, [], [{}], [[{"state": "open"}]]])
def test_unproven_pr_inventory_refuses_before_deleting(
    monkeypatch: pytest.MonkeyPatch, response: object
) -> None:
    github = POOL.GitHub("fixture/repository")
    monkeypatch.setattr(github, "api", lambda *args, **kwargs: response)
    monkeypatch.setattr(github, "artifacts", lambda: [artifact(1, 100)])
    with pytest.raises((ValueError, TypeError, KeyError)):
        POOL.reclaim(github, CEILING, CEILING, None)


@pytest.mark.parametrize(
    ("workflow", "prefix"),
    [
        ("application", "ac-application"),
        ("application-recovery", "ac-application"),
        ("sales-xray-web-image", "ac-sales-xray-web"),
        ("sales-xray-native-image", None),
    ],
)
@pytest.mark.parametrize("retained", [1_500_000_000, 1_600_000_001])
def test_real_admission_steps_reclaim_visual_excess(
    tmp_path: Path, workflow: str, prefix: str | None, retained: int
) -> None:
    data = yaml.safe_load((ROOT / f".github/workflows/{workflow}.yml").read_text())
    job = next(job for job in data["jobs"].values() if "application-release-packaging" in str(job))
    step = next(step for step in job["steps"] if "under the pooled ceiling" in step.get("name", ""))
    binary = tmp_path / "bin"
    binary.mkdir()
    state = tmp_path / "state.json"
    state.write_text(
        json.dumps(
            {
                "artifacts": [
                    artifact(1, 200_000_000),
                    artifact(2, retained, family="retained-evidence"),
                ],
                "pulls": [pull()],
                "deleted": [],
            }
        )
    )
    (binary / "gh").write_text("""#!/usr/bin/env python3
import json, os, sys
from pathlib import Path
path = Path(os.environ["FIXTURE_STATE"])
state = json.loads(path.read_text())
args = sys.argv[1:]
if "DELETE" in args:
    identity = int(args[-1].rsplit("/", 1)[1])
    state["deleted"].append(identity)
    state["artifacts"] = [a for a in state["artifacts"] if a["id"] != identity]
    path.write_text(json.dumps(state))
elif "/pulls?" in args[-1]:
    print(json.dumps([state["pulls"]]))
else:
    pages = [{"total_count": len(state["artifacts"]), "artifacts": state["artifacts"]}]
    if "--slurp" in args:
        print(json.dumps(pages))
    else:
        for page in pages:
            print(json.dumps(page))
""")
    (binary / "du").write_text('#!/bin/sh\nprintf "400000000\\tfixture\\n"\n')
    for executable in binary.iterdir():
        executable.chmod(0o700)
    environment = {
        **os.environ,
        "PATH": os.pathsep.join(
            (str(binary), str(Path(sys.executable).parent), os.environ["PATH"])
        ),
        "FIXTURE_STATE": str(state),
        "GITHUB_REPOSITORY": "fixture/repository",
        "RELEASE_SHA": CURRENT_SHA,
        "RUNNER_TEMP": str(tmp_path),
        "AC_RELEASE_ARTIFACT_POOL_BYTES": str(CEILING),
    }
    bash = shutil.which("bash")
    assert bash is not None
    result = subprocess.run(  # noqa: S603 - fixed workflow with fixture executables
        [bash, "-c", step["run"]],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert json.loads(state.read_text())["deleted"] == [1]
    projected = retained + 400_000_000 + (65_536 if workflow == "application-recovery" else 0)
    if retained == 1_500_000_000:
        assert result.returncode == 0, result.stderr
        assert f"projected repository pool is {projected} bytes" in result.stdout
    else:
        assert result.returncode == 1
        assert f"{projected} bytes; refusing upload above 2000000000" in result.stderr
    assert job["permissions"]["pull-requests"] == "read"
    assert job["permissions"]["actions"] == "write"
    if prefix:
        assert f"--replacement-prefix {prefix}" in step["run"]


def test_visual_evidence_retention_is_one_day() -> None:
    workflow = yaml.safe_load((ROOT / ".github/workflows/sales-xray-visual.yml").read_text())
    upload = next(
        step
        for step in workflow["jobs"]["visual-advisory"]["steps"]
        if step.get("id") == "evidence"
    )
    assert upload["with"]["retention-days"] == 1
