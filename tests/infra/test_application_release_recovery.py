"""Contract checks for the bounded existing-image release package recovery workflow."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/application-recovery.yml"


def test_recovery_workflow_is_package_only_and_digest_bound() -> None:
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    trigger = workflow[True]
    inputs = trigger["workflow_dispatch"]["inputs"]
    assert set(inputs) == {
        "release_sha",
        "validation_run_id",
        "published_registry_digests",
    }

    job = workflow["jobs"]["package-release-images"]
    assert job["permissions"] == {
        "actions": "write",
        "contents": "read",
        "packages": "read",
        "pull-requests": "read",
    }
    steps = job["steps"]
    names = [step.get("name", "") for step in steps]
    assert "Validate published-image recovery proof" in names
    assert "Pull and verify published release images" in names
    assert "Create transport archives and reviewed manifest" in names
    assert "Upload reviewed release bundle" in names
    assert "Upload CI recovery proof" in names
    assert job["if"] == "github.ref == 'refs/heads/main'"
    assert not any(name.startswith("Build ") for name in names)
    assert "Publish immutable SHA tags" not in names

    checkout = steps[0]
    assert checkout["with"]["ref"] == "${{ inputs.release_sha }}"
    proof = next(
        step for step in steps if step.get("name") == "Validate published-image recovery proof"
    )
    proof_text = proof["run"]
    assert '".github/workflows/application.yml"' in proof_text
    assert '.status == "completed"' in proof_text
    assert '.conclusion == "success"' in proof_text
    assert '.event == "push"' in proof_text
    assert '.head_branch == "main"' in proof_text
    assert ".repository.full_name == $repository" in proof_text
    assert "head_sha == $sha" in proof_text
    assert "academy-capacity-simulation" in proof_text
    assert "EXPECTED_%s_REGISTRY_DIGEST" in proof_text
    pull = next(
        step for step in steps if step.get("name") == "Pull and verify published release images"
    )
    pull_text = pull["run"]
    assert "docker manifest inspect" in pull_text
    assert "docker pull" in pull_text
    assert 'docker pull "$immutable_image"' in pull_text
    assert 'immutable_image="${image%:*}@$expected_digest"' in pull_text
    assert "RepoDigests" in pull_text
    assert '"$api_release_id" = "$RELEASE_SHA"' in pull_text

    create = next(
        step
        for step in steps
        if step.get("name") == "Create transport archives and reviewed manifest"
    )
    create_text = create["run"]
    assert 'verify-bundle "$artifact_dir" "$RELEASE_SHA"' in create_text
    assert "verify_transport_config" in create_text
    assert "AC_API_REGISTRY_DIGEST" in create_text
    assert "${API_IMAGE%:*}@$EXPECTED_API_REGISTRY_DIGEST" in create_text
    assert "${COACH_IMAGE%:*}@$EXPECTED_COACH_REGISTRY_DIGEST" in create_text


def recovery_step(name: str) -> str:
    job = yaml.safe_load(WORKFLOW.read_text())["jobs"]["package-release-images"]
    return next(step["run"] for step in job["steps"] if step.get("name") == name)


@pytest.mark.parametrize(
    "overrides,accepted",
    [
        ({"event": "push"}, True),
        ({"event": "workflow_dispatch"}, True),
        ({"event": "pull_request"}, False),
        ({"head_branch": "task/x"}, False),
        ({"head_sha": "b" * 40}, False),
        ({"conclusion": "failure"}, False),
        ({"status": "in_progress"}, False),
        ({"repository": {"full_name": "fork/repo"}}, False),
        ({"path": ".github/workflows/other.yml"}, False),
        ({"publication_count": 3}, False),
        ({"publication_digest": "e" * 64}, False),
    ],
)
def test_actual_recovery_shell_validates_original_push(tmp_path, overrides, accepted):
    sha = "a" * 40
    overrides = dict(overrides)
    publication_count = overrides.pop("publication_count", 4)
    publication_digest = overrides.pop("publication_digest", "d" * 64)
    run = {
        "head_sha": sha,
        "head_branch": "main",
        "status": "completed",
        "conclusion": "success",
        "event": "push",
        "repository": {"full_name": "authorityclosers/authority-closers-platform"},
        "path": ".github/workflows/application.yml",
        **overrides,
    }
    jobs = {
        "jobs": [
            {"id": 300, "name": name, "head_sha": sha, "conclusion": "success"}
            for name in ("validate", "academy-capacity-simulation", "package-release-images")
        ]
    }
    gh = tmp_path / "gh"
    gh.write_text(
        "#!/usr/bin/env python3\nimport sys\n"
        + "if sys.argv[-1].endswith('/logs'):\n"
        + f" print('2026-10-05T01:13:00Z Digest: sha256:{publication_digest}\\n' "
        + f"* {publication_count}, end='')\n"
        + " sys.exit(0)\n"
        + f"print({json.dumps(json.dumps(jobs))} if '/jobs?' in sys.argv[-1] "
        + f"else {json.dumps(json.dumps(run))})\n"
    )
    gh.chmod(0o755)
    env = {
        **os.environ,
        "PATH": f"{tmp_path}:{os.environ['PATH']}",
        "RELEASE_SHA": sha,
        "REUSE_VALIDATION_RUN_ID": "100",
        "REUSE_PUBLISHED_REGISTRY_DIGESTS": ",".join(
            f"{name}=sha256:{'d' * 64}" for name in ("api", "learner", "admin", "coach")
        ),
        "GITHUB_ENV": str(tmp_path / "github.env"),
        "RUNNER_TEMP": str(tmp_path),
        "GITHUB_REPOSITORY": "authorityclosers/authority-closers-platform",
    }
    result = subprocess.run(  # noqa: S603 - execute the checked-in workflow with mocked gh
        ["/bin/bash", "-c", recovery_step("Validate published-image recovery proof")],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert (result.returncode == 0) is accepted, result.stderr


def test_ci_proof_binds_upload_digest_manifest_and_distinct_workflow_sha(tmp_path):
    sha, workflow_sha = "a" * 40, "b" * 40
    artifact_dir = tmp_path / f"ac-application-{sha}"
    artifact_dir.mkdir()
    (artifact_dir / "release-images.env").write_text(f"AC_RELEASE_ID={sha}\n")
    env = {
        **os.environ,
        "RELEASE_SHA": sha,
        "RUNNER_TEMP": str(tmp_path),
        "GITHUB_REPOSITORY": "authorityclosers/authority-closers-platform",
        "GITHUB_SHA": workflow_sha,
        "GITHUB_RUN_ID": "200",
        "REUSE_VALIDATION_RUN_ID": "100",
        "RECOVERED_ARTIFACT_ID": "8",
        "RECOVERED_ARTIFACT_DIGEST": "d" * 64,
        "ORIGINAL_PACKAGE_JOB_ID": "300",
        "ORIGINAL_PUBLICATION_LOG_SHA256": "sha256:" + "c" * 64,
    }
    for name, image in zip(
        ("API", "LEARNER", "ADMIN", "COACH"),
        ("api", "learner-web", "admin-web", "coach-web"),
        strict=True,
    ):
        env[f"{name}_IMAGE"] = f"ghcr.io/authorityclosers/authority-closers-{image}:{sha}"
        env[f"EXPECTED_{name}_REGISTRY_DIGEST"] = "sha256:" + "e" * 64
    result = subprocess.run(  # noqa: S603 - fixed checked-in proof generator, no provider calls
        [
            "/bin/bash",
            "-c",
            recovery_step("Bind recovery bundle to original validation and image digests"),
        ],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    proof = json.loads(
        (tmp_path / f"ac-application-recovery-proof-{sha}" / "recovery-proof.json").read_text()
    )
    assert proof["release_sha"] == sha
    assert proof["recovery_head_sha"] == workflow_sha
    assert proof["validation_run_id"] == 100
    assert proof["recovery_run_id"] == 200
    assert proof["artifact_id"] == 8
    assert proof["artifact_digest"] == "sha256:" + "d" * 64
    assert set(proof["registry_digests"]) == {"api", "learner", "admin", "coach"}
