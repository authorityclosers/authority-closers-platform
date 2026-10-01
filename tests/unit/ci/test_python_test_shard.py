from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

# Pytest's importlib mode does not add the repository root to ``sys.path``.
ROOT = Path(__file__).parents[3]
sys.path.insert(0, str(ROOT))

import scripts.ci.python_test_shard as shard  # noqa: E402

SHA = "a" * 40


def _artifact(root: Path, index: int, attempt: int = 1) -> Path:
    return root / "manifests" / f"python-test-shard-{SHA}-{attempt}-{index}" / "manifest.json"


def _verify_cli(root: Path, exclusion_file: Path) -> int:
    return shard.main(
        [
            "verify",
            "--root",
            str(root),
            "--shard-count",
            "4",
            "--exclude-file",
            str(exclusion_file),
            "--manifest-dir",
            str(root / "manifests"),
            "--sha",
            SHA,
            "--run-attempt",
            "2",
        ]
    )


@pytest.fixture
def retry_fixture(tmp_path: Path) -> Path:
    for index in range(4):
        _write_test_file(tmp_path, f"tests/unit/test_fictional_{index}.py")
    _write_test_file(tmp_path, "tests/unit/test_separate_gate.py")
    excluded = ("tests/unit/test_separate_gate.py",)
    exclusion_file = tmp_path / "exclusions.txt"
    exclusion_file.write_text(excluded[0] + "\n", encoding="utf-8")
    discovered = shard.discover_test_files(tmp_path)
    assignments = shard.assign_shards(tuple(path for path in discovered if path not in excluded), 4)
    for index, attempt in ((0, 1), (1, 1), (3, 1), (2, 1), (2, 2)):
        _write_manifest(
            _artifact(tmp_path, index, attempt),
            index=index,
            count=4,
            discovered=discovered,
            assigned=assignments[index],
            excluded=excluded,
        )
    return exclusion_file


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
            _artifact(tmp_path, index),
            index=index,
            count=2,
            discovered=discovered,
            assigned=assigned,
            excluded=(),
        )
    shard.verify_manifests(
        tmp_path / "manifests", tmp_path, 2, exclusion_file, sha=SHA, run_attempt=1
    )

    duplicate = json.loads(_artifact(tmp_path, 1).read_text())
    duplicate["tests"].append(duplicate["tests"][0])
    _artifact(tmp_path, 1).write_text(json.dumps(duplicate))
    with pytest.raises(shard.ShardConfigurationError, match="more than one shard"):
        shard.verify_manifests(
            tmp_path / "manifests", tmp_path, 2, exclusion_file, sha=SHA, run_attempt=1
        )


@pytest.mark.parametrize("full_rerun", [False, True])
def test_retry_cli_selects_newest_attempts(
    tmp_path: Path, retry_fixture: Path, capsys: pytest.CaptureFixture[str], full_rerun: bool
) -> None:
    if full_rerun:
        for index in (0, 1, 3):
            target = _artifact(tmp_path, index, 2)
            target.parent.mkdir()
            target.write_text(_artifact(tmp_path, index).read_text())
    # Superseded content cannot affect the selected evidence.
    _artifact(tmp_path, 2).write_text("invalid older JSON")
    assert _verify_cli(tmp_path, retry_fixture) == 0
    output = capsys.readouterr()
    assert output.out == "".join(
        f"selected shard {index}: attempt {2 if full_rerun or index == 2 else 1}\n"
        for index in range(4)
    )
    assert output.err == ""


def test_retry_cli_rejects_missing_index(
    tmp_path: Path, retry_fixture: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = _artifact(tmp_path, 1)
    path.unlink()
    path.parent.rmdir()
    assert _verify_cli(tmp_path, retry_fixture) == 2
    output = capsys.readouterr()
    assert output.out == ""
    assert output.err == (
        "python test shard configuration error: expected 4 shard manifests, found 3 in "
        f"{tmp_path / 'manifests'}\n"
    )


@pytest.mark.parametrize(
    ("name", "diagnostic"),
    [
        (f"python-test-shard-{'b' * 40}-1-0", "foreign shard SHA"),
        (f"python-test-shard-{SHA}-3-0", "shard attempt exceeds current attempt"),
        (f"python-test-shard-{SHA}-1-4", "shard artifact index is outside shard count"),
        ("junk", "invalid shard artifact directory"),
        *[
            (f"python-test-shard-{SHA}-{tail}", "invalid shard artifact directory")
            for tail in ("0-0", "01-0", "-1-0", "1-00", "1--1", "1-0-extra")
        ],
        (f"python-test-shard-{'A' * 40}-1-0", "invalid shard artifact directory"),
        (f"python-test-shard-{'a' * 39}-1-0", "invalid shard artifact directory"),
    ],
)
def test_retry_cli_rejects_every_invalid_artifact_directory(
    tmp_path: Path,
    retry_fixture: Path,
    capsys: pytest.CaptureFixture[str],
    name: str,
    diagnostic: str,
) -> None:
    (tmp_path / "manifests" / name).mkdir()
    assert _verify_cli(tmp_path, retry_fixture) == 2
    output = capsys.readouterr()
    assert output.out == ""
    assert output.err == f"python test shard configuration error: {diagnostic}: {name}\n"


@pytest.mark.parametrize(
    ("change", "diagnostic"),
    [
        ({"shard_index": 0}, "shard artifact/manifest index mismatch"),
        ({"shard_index": "2"}, "shard artifact/manifest index mismatch"),
        ({"schema": "wrong"}, "shard manifest schema or count mismatch"),
        ({"shard_count": 3}, "shard manifest schema or count mismatch"),
        ({"discovered": []}, "shards used different pytest discovery results"),
        ({"excluded": []}, "shards used different explicit gate exclusions"),
        ({"tests": []}, "shard coverage mismatch; missing="),
        ("invalid JSON", "invalid shard manifest"),
        (None, "invalid shard manifest"),
    ],
)
def test_invalid_newest_evidence_fails_without_fallback(
    tmp_path: Path,
    retry_fixture: Path,
    capsys: pytest.CaptureFixture[str],
    change: dict[str, object] | str | None,
    diagnostic: str,
) -> None:
    path = _artifact(tmp_path, 2, 2)
    value = json.loads(path.read_text())
    if isinstance(change, str):
        path.write_text(change)
    elif change is not None:
        value.update(change)
        path.write_text(json.dumps(value))
    else:
        path.unlink()
    assert _verify_cli(tmp_path, retry_fixture) == 2
    output = capsys.readouterr()
    assert output.out == ""
    assert output.err.startswith(f"python test shard configuration error: {diagnostic}")


@pytest.mark.parametrize("matrix_result", ["success", "failure"])
def test_coverage_cannot_override_failed_python_matrix(matrix_result: str) -> None:
    workflow = yaml.safe_load((ROOT / ".github/workflows/application.yml").read_text())
    step = next(
        step
        for step in workflow["jobs"]["validate"]["steps"]
        if step.get("name") == "Require every validation component to pass"
    )
    assert step["env"]["PYTHON_TESTS_RESULT"] == "${{ needs.validate-python-tests.result }}"
    result = subprocess.run(  # noqa: S603 - checked-in gate with fictional status inputs
        ["/bin/bash", "-c", step["run"]],
        env={
            key: matrix_result if key == "PYTHON_TESTS_RESULT" else "success" for key in step["env"]
        },
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == (0 if matrix_result == "success" else 1)


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
