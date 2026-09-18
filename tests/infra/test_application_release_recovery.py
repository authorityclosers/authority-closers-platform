"""Contract checks for the bounded existing-image release package recovery workflow."""

from __future__ import annotations

from pathlib import Path

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
    }
    steps = job["steps"]
    names = [step.get("name", "") for step in steps]
    assert "Validate published-image recovery proof" in names
    assert "Pull and verify published release images" in names
    assert "Create transport archives and reviewed manifest" in names
    assert "Upload reviewed release bundle" in names
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
    assert "head_sha == $sha" in proof_text
    assert "academy-capacity-simulation" in proof_text
    assert "EXPECTED_%s_REGISTRY_DIGEST" in proof_text
    pull = next(
        step for step in steps if step.get("name") == "Pull and verify published release images"
    )
    pull_text = pull["run"]
    assert "docker manifest inspect" in pull_text
    assert "docker pull" in pull_text
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
