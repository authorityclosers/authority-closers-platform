from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "infra/release/validate-artifact-pool.py"
WORKFLOWS = (
    ROOT / ".github/workflows/application.yml",
    ROOT / ".github/workflows/application-recovery.yml",
    ROOT / ".github/workflows/sales-xray-web-image.yml",
    ROOT / ".github/workflows/sales-xray-native-image.yml",
)
VARIABLE = "AC_RELEASE_ARTIFACT_POOL_BYTES"


class _UniqueKeyLoader(yaml.SafeLoader):
    pass


def _construct_unique_mapping(loader: yaml.SafeLoader, node: yaml.MappingNode, deep: bool = False):
    mapping = {}
    for key, value in loader.construct_pairs(node, deep=deep):
        if key in mapping:
            raise yaml.constructor.ConstructorError(
                "while constructing a mapping",
                node.start_mark,
                f"found duplicate key: {key!r}",
                node.start_mark,
            )
        mapping[key] = value
    return mapping


_UniqueKeyLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_unique_mapping,
)


def _run_validator(value: str | None) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment.pop(VARIABLE, None)
    if value is not None:
        environment[VARIABLE] = value
    return subprocess.run(  # noqa: S603 - fixed repository validator
        [sys.executable, str(SCRIPT)],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        check=False,
        text=True,
    )


def test_pool_validator_defaults_and_accepts_bounded_values() -> None:
    assert _run_validator(None).stdout == "1000000000\n"
    assert _run_validator("").stdout == "1000000000\n"
    for value in ("450000000", "1000000000", "4000000000", "0000000450000000"):
        result = _run_validator(value)
        assert result.returncode == 0, result.stderr
        assert result.stdout == f"{int(value)}\n"


@pytest.mark.parametrize(
    "value",
    (
        "449999999",
        "4000000001",
        "-1",
        "1.0",
        "1000000000 ",
        "not-a-number",
        "4" * 5000,
    ),
)
def test_pool_validator_rejects_invalid_or_unsafe_values(value: str) -> None:
    result = _run_validator(value)
    assert result.returncode == 2
    assert VARIABLE in result.stderr


def test_all_release_workflows_use_the_repository_pool_variable() -> None:
    expected_env = (
        "AC_RELEASE_ARTIFACT_POOL_BYTES: ${{ vars.AC_RELEASE_ARTIFACT_POOL_BYTES || '1000000000' }}"
    )
    for workflow_path in WORKFLOWS:
        workflow = workflow_path.read_text(encoding="utf-8")
        assert expected_env in workflow
        assert "python infra/release/validate-artifact-pool.py" in workflow
        assert "max_artifact_bytes=450000000" in workflow


def test_pool_validator_is_a_step_and_pool_setting_is_job_scoped() -> None:
    expected_value = "${{ vars.AC_RELEASE_ARTIFACT_POOL_BYTES || '1000000000' }}"
    for workflow_path in WORKFLOWS:
        workflow = yaml.load(
            workflow_path.read_text(encoding="utf-8"),
            Loader=_UniqueKeyLoader,  # noqa: S506
        )
        matching_jobs = [
            job
            for job in workflow["jobs"].values()
            if isinstance(job, dict) and job.get("env", {}).get(VARIABLE) == expected_value
        ]
        assert len(matching_jobs) == 1
        job = matching_jobs[0]
        assert "run" not in job["env"]
        assert any(
            "python infra/release/validate-artifact-pool.py" in step.get("run", "")
            for step in job["steps"]
        )


def test_application_cleanup_stays_after_upload_proof_and_retains_one_day() -> None:
    for workflow_path in WORKFLOWS[:2]:
        workflow = workflow_path.read_text(encoding="utf-8")
        upload_index = workflow.index("Upload reviewed release bundle")
        reclaim_index = workflow.index("Reclaim superseded release artifacts after verified upload")
        proof_index = workflow.index("Uploaded release artifact could not be proven")
        delete_index = workflow.index("gh api --method DELETE")
        assert proof_index < delete_index
        assert upload_index < reclaim_index
        assert upload_index < delete_index
        assert "retention-days: 1" in workflow


def test_application_admission_accounts_for_verified_cleanup() -> None:
    for workflow_path in WORKFLOWS[:2]:
        workflow = workflow_path.read_text(encoding="utf-8")
        assert 'superseded_release_bytes="$(jq' in workflow
        assert 'test("^ac-application-[0-9a-f]{40}$")' in workflow
        assert "retained_bytes - superseded_release_bytes + candidate_bytes" in workflow
