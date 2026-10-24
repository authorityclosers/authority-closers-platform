"""Main reuses a release PR's validation only for the exact tree it passed (24 Oct 2026)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from scripts.ci import main_validation as mv  # noqa: E402

REPOSITORY = "authorityclosers/authority-closers-platform"
WORKFLOW = yaml.safe_load((ROOT / ".github/workflows/application.yml").read_text())
TEST_JOBS = (
    "validate-python-static",
    "validate-frontend",
    "validate-sales-xray-acquisition-browser",
    "validate-python-tests",
    "validate-python-gates",
)


def git(repo: Path, *arguments: str) -> str:
    return subprocess.run(  # noqa: S603 - fixed git argv in a fixture repository
        ["git", "-C", str(repo), *arguments],  # noqa: S607
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


@pytest.fixture
def history(tmp_path: Path) -> dict[str, object]:
    """main@A; the release PR head B builds on A; main's squash S has B's tree and parent A."""
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "--quiet")
    git(repo, "config", "user.email", "fixture@example.invalid")
    git(repo, "config", "user.name", "Fixture")
    (repo / "app.txt").write_text("base\n")
    git(repo, "add", "-A")
    git(repo, "commit", "--quiet", "-m", "main")
    base = git(repo, "rev-parse", "HEAD")
    (repo / "app.txt").write_text("release\n")
    git(repo, "commit", "--quiet", "-am", "release head")
    head = git(repo, "rev-parse", "HEAD")
    squash = git(repo, "commit-tree", f"{head}^{{tree}}", "-p", base, "-m", "Release squash")
    return {"repo": repo, "base": base, "head": head, "squash": squash}


def runner(repo: Path, fetched: str):
    def run_git(*arguments: str) -> str:
        if arguments[0] == "fetch":
            # The fixture has no remote: the fetch lands the pull request head on the same ref.
            git(repo, "update-ref", "refs/ac/pr-head", fetched)
            return ""
        return git(repo, *arguments)

    return run_git


def api(sha: str, head: str, *, pulls=None, conclusion="success", validate="success"):
    runs_path = (
        f"/repos/{REPOSITORY}/actions/workflows/application.yml/runs"
        f"?event=pull_request&head_sha={head}&per_page=20"
    )
    responses = {
        f"/repos/{REPOSITORY}/commits/{sha}/pulls": pulls
        if pulls is not None
        else [
            {
                "number": 532,
                "merged_at": "2026-10-24T10:00:00Z",
                "merge_commit_sha": sha,
                "base": {"ref": "main"},
                "head": {"sha": head, "repo": {"full_name": REPOSITORY}},
            }
        ],
        runs_path: {
            "workflow_runs": [
                {
                    "id": 77,
                    "run_number": 5,
                    "run_attempt": 1,
                    "head_sha": head,
                    "event": "pull_request",
                    "path": ".github/workflows/application.yml",
                    "status": "completed",
                    "conclusion": conclusion,
                    "repository": {"full_name": REPOSITORY},
                }
            ]
        },
        f"/repos/{REPOSITORY}/actions/runs/77/jobs?filter=latest&per_page=100": {
            "jobs": [{"name": "validate", "conclusion": validate}]
        },
    }
    return lambda path: responses[path]


def decide(history, *, sha=None, fetched=None, event="push", **api_options):
    sha = sha or history["squash"]
    return mv.decide(
        api(sha, history["head"], **api_options),
        runner(history["repo"], fetched or history["head"]),
        event,
        "refs/heads/main",
        REPOSITORY,
        sha,
    )


def test_the_squash_of_a_passed_release_pull_request_reuses_its_run(history) -> None:
    assert decide(history) == {
        "reuse": "true",
        "run": "77",
        "pull": "532",
        "head": history["head"],
    }


def test_a_different_tree_runs_everything(history) -> None:
    repo = history["repo"]
    other = git(
        repo, "commit-tree", f"{history['base']}^{{tree}}", "-p", history["base"], "-m", "x"
    )
    result = decide(history, sha=other)
    assert result["reuse"] == "false"
    assert "tree differs" in result["reason"]


def test_a_head_that_lacks_mains_previous_commit_runs_everything(history) -> None:
    repo = history["repo"]
    moved = git(
        repo, "commit-tree", f"{history['base']}^{{tree}}", "-p", history["base"], "-m", "m"
    )
    squash = git(repo, "commit-tree", f"{history['head']}^{{tree}}", "-p", moved, "-m", "squash")
    result = decide(history, sha=squash)
    assert result == {
        "reuse": "false",
        "reason": "the pull request head does not contain main's previous commit",
    }


@pytest.mark.parametrize(
    ("options", "reason"),
    [
        ({"conclusion": "failure"}, "no successful Application validation run"),
        ({"validate": "skipped"}, "validate job did not pass"),
        ({"pulls": []}, "exactly one pull request"),
    ],
)
def test_missing_or_failed_pull_request_evidence_runs_everything(history, options, reason) -> None:
    result = decide(history, **options)
    assert result["reuse"] == "false" and reason in result["reason"]


def test_a_fork_or_unmerged_pull_request_is_never_reused(history) -> None:
    pull = {
        "number": 9,
        "merged_at": "2026-10-24T10:00:00Z",
        "merge_commit_sha": history["squash"],
        "base": {"ref": "main"},
        "head": {"sha": history["head"], "repo": {"full_name": "someone/fork"}},
    }
    assert decide(history, pulls=[pull])["reuse"] == "false"
    pull["head"]["repo"]["full_name"] = REPOSITORY
    pull["merged_at"] = None
    assert decide(history, pulls=[pull])["reuse"] == "false"


def test_a_moved_pull_request_head_runs_everything(history) -> None:
    result = decide(history, fetched=history["base"])
    assert result["reason"] == "the pull request head moved after its merge"


def test_pull_requests_and_api_failures_run_everything(history) -> None:
    def broken(path: str):
        raise OSError("network")

    assert decide(history, event="pull_request")["reuse"] == "false"
    result = mv.decide(
        broken,
        runner(history["repo"], history["head"]),
        "push",
        "refs/heads/main",
        REPOSITORY,
        history["squash"],
    )
    assert result == {"reuse": "false", "reason": "the pull request evidence could not be read"}


def test_only_the_duplicated_test_jobs_skip_and_only_on_proven_reuse() -> None:
    jobs = WORKFLOW["jobs"]
    for name in TEST_JOBS:
        assert "pr-evidence" in jobs[name]["needs"]
        assert jobs[name]["if"] == "needs.pr-evidence.outputs.reuse != 'true'"
    # The recovery workflow requires the main run's academy job, and packaging still waits for
    # validate inside its artifact-pool lock.
    assert "if" not in jobs["academy-capacity-simulation"]
    assert "if" not in jobs["ci-prerequisites"]
    assert jobs["package-release-images"]["needs"] == "validate"
    assert jobs["validate"]["if"] == "always()"
    assert "pr-evidence" in jobs["validate"]["needs"]


def test_prebuild_only_warms_the_build_cache() -> None:
    job = WORKFLOW["jobs"]["prebuild-release-images"]
    assert job["continue-on-error"] is True and "concurrency" not in job
    assert job["permissions"] == {"contents": "read", "pull-requests": "read"}
    builds = [step for step in job["steps"] if "docker/build-push-action" in step.get("uses", "")]
    package = WORKFLOW["jobs"]["package-release-images"]["steps"]
    packaged = [step for step in package if "docker/build-push-action" in step.get("uses", "")]
    assert len(builds) == len(packaged) == 4
    for warm, real in zip(builds, packaged, strict=True):
        assert warm["with"]["outputs"] == "type=cacheonly"
        assert "push" not in warm["with"] and "load" not in warm["with"]
        for key in ("file", "target", "build-args", "cache-from", "cache-to", "platforms"):
            assert warm["with"][key] == real["with"][key]
    assert not any("upload-artifact" in step.get("uses", "") for step in job["steps"])


def gate(**results: str) -> int:
    step = next(
        step
        for step in WORKFLOW["jobs"]["validate"]["steps"]
        if step.get("name") == "Require every validation component to pass"
    )
    env = {key: "success" for key in step["env"]} | {"REUSE": "false"} | results
    return subprocess.run(  # noqa: S603 - checked-in gate with fictional status inputs
        ["/bin/bash", "-c", step["run"]], env=env, capture_output=True, check=False
    ).returncode


SKIPPED = {
    "PYTHON_STATIC_RESULT": "skipped",
    "FRONTEND_RESULT": "skipped",
    "SALES_XRAY_ACQUISITION_BROWSER_RESULT": "skipped",
    "PYTHON_TESTS_RESULT": "skipped",
    "PYTHON_GATES_RESULT": "skipped",
}


def test_validate_accepts_skipped_tests_only_with_proven_reuse() -> None:
    assert gate() == 0
    assert gate(REUSE="true", **SKIPPED) == 0
    assert gate(**SKIPPED) == 1
    assert gate(REUSE="true", **(SKIPPED | {"PYTHON_TESTS_RESULT": "failure"})) == 1
    assert gate(REUSE="true", PR_EVIDENCE_RESULT="failure", **SKIPPED) == 1
    assert gate(REUSE="true", ACADEMY_RESULT="skipped", **SKIPPED) == 1
    assert gate(REUSE="true", PREREQUISITES_RESULT="skipped", **SKIPPED) == 1
