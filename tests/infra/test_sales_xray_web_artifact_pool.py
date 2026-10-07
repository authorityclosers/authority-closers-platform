from __future__ import annotations

import json
import os
import runpy
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = yaml.safe_load(
    (ROOT / ".github/workflows/sales-xray-web-image.yml").read_text(encoding="utf-8")
)
JOB = WORKFLOW["jobs"]["build-sales-xray-web"]
STEPS = {step["name"]: step for step in JOB["steps"]}
ADMIT = "Admit the web artifact under the pooled ceiling"
UPLOAD = "Upload the offline web image artifact"
RECLAIM = "Reclaim superseded web artifacts after verified upload"
SHA = "a" * 40
CURRENT_NAME = f"ac-sales-xray-web-{SHA}"
POOL_BYTES = 2_000_000_000
INVENTORY = runpy.run_path(str(ROOT / "infra/release/read-artifact-inventory.py"))


def _artifact(artifact_id: int, name: str, size: int) -> dict:
    return {
        "id": artifact_id,
        "name": name,
        "size_in_bytes": size,
        "expired": False,
        "workflow_run": {"id": 101},
    }


@dataclass
class _Harness:
    state_path: Path
    environment: dict[str, str]

    def set_state(self, artifacts: list[dict], **options: object) -> None:
        self.state_path.write_text(
            json.dumps({"artifacts": artifacts, "calls": [], **options}), encoding="utf-8"
        )

    def state(self) -> dict:
        return json.loads(self.state_path.read_text(encoding="utf-8"))

    def run(self, step: str) -> subprocess.CompletedProcess[str]:
        bash = shutil.which("bash")
        assert bash is not None, "Bash is required to exercise the workflow steps"
        return subprocess.run(  # noqa: S603 - repository step with local fixture executables
            [bash, "-c", STEPS[step]["run"]],
            cwd=ROOT,
            env=self.environment,
            capture_output=True,
            text=True,
            check=False,
        )


@pytest.fixture
def harness(tmp_path: Path) -> _Harness:
    binary_dir = tmp_path / "bin"
    binary_dir.mkdir()
    state_path = tmp_path / "github-fixture.json"
    scripts = {
        "gh": """#!/usr/bin/env python3
import json
import os
import sys
from pathlib import Path

path = Path(os.environ["FIXTURE_STATE"])
state = json.loads(path.read_text())
args = sys.argv[1:]
state["calls"].append(args)
path.write_text(json.dumps(state))
if args[0] != "api":
    sys.exit(2)
if "DELETE" in args:
    if state.get("delete_fails"):
        sys.exit(1)
    artifact_id = int(args[-1].rsplit("/", 1)[-1])
    state["artifacts"] = [a for a in state["artifacts"] if a["id"] != artifact_id]
    path.write_text(json.dumps(state))
elif "--paginate" in args:
    if "/pulls?" in args[-1]:
        if state.get("pulls_fail"):
            sys.exit(1)
        pulls = state.get("pulls", [])
        if "state=open" in args[-1]:
            pulls = [p for p in pulls if p["state"] == "open"]
        print(json.dumps([pulls]))
        sys.exit(0)
    if state.get("list_fails"):
        sys.exit(1)
    if state.get("list_results"):
        response = state["list_results"].pop(0)
        path.write_text(json.dumps(state))
        sys.stdout.write(response["stdout"])
        sys.stderr.write(response.get("stderr", ""))
        sys.exit(response.get("returncode", 0))
    artifacts = state["artifacts"]
    pages = [
        {"total_count": len(artifacts), "artifacts": artifacts[start:start + 100]}
        for start in range(0, max(1, len(artifacts)), 100)
    ]
    if "--slurp" in args:
        print(json.dumps(pages))
    else:
        for page in pages:
            print(json.dumps(page))
else:
    artifact_id = int(args[-1].rsplit("/", 1)[-1])
    matches = [a for a in state["artifacts"] if a["id"] == artifact_id]
    if not matches:
        sys.exit(1)
    print(json.dumps(matches[0]))
""",
        "python": """#!/usr/bin/env python3
import os
import runpy
import sys

if sys.argv[1] == "infra/release/read-artifact-inventory.py":
    # Exercise the real reader without waiting for its production retry delays.
    reader = runpy.run_path(sys.argv[1])
    reader["time"].sleep = lambda _: None
    sys.argv = sys.argv[1:]
    sys.exit(reader["main"]())
os.execv(sys.executable, [sys.executable, *sys.argv[1:]])
""",
        "du": '#!/bin/sh\nprintf "%s\\tfixture\\n" "$FIXTURE_CANDIDATE_BYTES"\n',
        "sleep": "#!/bin/sh\nexit 0\n",
    }
    for name, script in scripts.items():
        executable = binary_dir / name
        executable.write_text(script, encoding="utf-8")
        executable.chmod(0o700)
    environment = {
        **os.environ,
        "PATH": f"{binary_dir}{os.pathsep}{os.environ['PATH']}",
        "RUNNER_TEMP": str(tmp_path),
        "FROZEN_SHA": SHA,
        "GITHUB_REPOSITORY": "fixture/repository",
        "GITHUB_RUN_ID": "101",
        "UPLOADED_ARTIFACT_ID": "99",
        "AC_RELEASE_ARTIFACT_POOL_BYTES": str(POOL_BYTES),
        "FIXTURE_STATE": str(state_path),
        "FIXTURE_CANDIDATE_BYTES": "400000000",
    }
    result = _Harness(state_path, environment)
    result.set_state([])
    return result


def test_admission_recovers_the_reported_pool_without_deleting(harness: _Harness) -> None:
    harness.set_state(
        [
            _artifact(1, "ac-application-" + "b" * 40, 600_000_000),
            _artifact(2, "ac-sales-xray-web-" + "c" * 40, 400_000_000),
            _artifact(3, "retained-evidence", 638_604_755),
        ]
    )
    result = harness.run(ADMIT)
    assert result.returncode == 0, result.stderr
    assert "projected repository pool is 1638604755 bytes (ceiling 2000000000)" in result.stdout
    assert len(harness.state()["artifacts"]) == 3
    assert not any("DELETE" in call for call in harness.state()["calls"])


@pytest.mark.parametrize(("retained", "allowed"), [(1_600_000_000, True), (1_600_000_001, False)])
def test_admission_enforces_exact_ceiling(harness: _Harness, retained: int, allowed: bool) -> None:
    harness.set_state([_artifact(1, "retained", retained), _artifact(2, CURRENT_NAME, 300_000_000)])
    result = harness.run(ADMIT)
    assert (result.returncode == 0) is allowed
    assert not any("DELETE" in call for call in harness.state()["calls"])


def test_non_reclaimable_pool_refuses_candidate(harness: _Harness) -> None:
    harness.set_state(
        [
            _artifact(1, "ac-application-" + "b" * 40, 700_000_000),
            _artifact(2, "ac-sales-xray-native-" + "c" * 40, 700_000_000),
            _artifact(3, CURRENT_NAME + "-evidence", 200_000_001),
            _artifact(4, "ac-sales-xray-web-" + "d" * 40, 400_000_000),
        ]
    )
    result = harness.run(ADMIT)
    assert result.returncode == 1
    assert "2000000001 bytes; refusing upload above 2000000000" in result.stderr
    assert len(harness.state()["artifacts"]) == 4


def test_candidate_has_its_own_ceiling(harness: _Harness) -> None:
    harness.environment["FIXTURE_CANDIDATE_BYTES"] = "450000001"
    result = harness.run(ADMIT)
    assert result.returncode == 1
    assert "refusing upload above 450000000" in result.stderr
    assert harness.state()["calls"] == []


def test_reclaim_proves_upload_and_preserves_current_and_other_artifacts(harness: _Harness) -> None:
    artifacts = [
        _artifact(99, CURRENT_NAME, 400_000_000),
        _artifact(1, "ac-sales-xray-web-" + "b" * 40, 400_000_000),
        _artifact(2, CURRENT_NAME, 350_000_000),
        _artifact(3, "ac-application-" + "c" * 40, 600_000_000),
        _artifact(4, "ac-sales-xray-native-" + "d" * 40, 400_000_000),
        _artifact(5, CURRENT_NAME + "-evidence", 10_000),
        _artifact(6, "ac-sales-xray-web-" + "B" * 40, 10_000),
    ]
    harness.set_state(artifacts)
    result = harness.run(RECLAIM)
    assert result.returncode == 0, result.stderr
    assert harness.state()["artifacts"] == [artifacts[i] for i in (0, 3, 4, 5, 6)]
    calls = harness.state()["calls"]
    assert calls[0][-1].endswith("/artifacts/99")
    assert [call[-1].rsplit("/", 1)[-1] for call in calls if "DELETE" in call] == ["1", "2"]
    assert "final repository pool is 1400020000 bytes" in result.stdout


@pytest.mark.parametrize("defect", ["missing", "name", "run", "expired", "empty", "id"])
def test_unproven_upload_never_reclaims(harness: _Harness, defect: str) -> None:
    current = _artifact(99, CURRENT_NAME, 400_000_000)
    if defect == "name":
        current["name"] = "ac-sales-xray-web-" + "b" * 40
    elif defect == "run":
        current["workflow_run"] = {"id": 102}
    elif defect == "expired":
        current["expired"] = True
    elif defect == "empty":
        current["size_in_bytes"] = 0
    elif defect == "id":
        harness.environment["UPLOADED_ARTIFACT_ID"] = "invalid"
    artifacts = [_artifact(1, "ac-sales-xray-web-" + "c" * 40, 400_000_000)]
    if defect != "missing":
        artifacts.append(current)
    harness.set_state(artifacts)
    result = harness.run(RECLAIM)
    assert result.returncode == 1
    assert harness.state()["artifacts"] == artifacts
    assert not any("DELETE" in call for call in harness.state()["calls"])


def test_cleanup_failure_does_not_claim_a_bounded_pool(harness: _Harness) -> None:
    harness.set_state(
        [_artifact(99, CURRENT_NAME, 400_000_000), _artifact(1, "retained", 1_600_000_001)]
    )
    result = harness.run(RECLAIM)
    assert result.returncode == 1
    assert "Final repository artifact pool is 2000000001 bytes" in result.stderr
    assert "Verified web artifact" not in result.stdout


@pytest.mark.parametrize("step", [ADMIT, RECLAIM])
def test_failed_inventory_is_not_treated_as_empty(harness: _Harness, step: str) -> None:
    artifacts = [_artifact(99, CURRENT_NAME, 400_000_000)]
    harness.set_state(artifacts, list_fails=True)
    result = harness.run(step)
    assert result.returncode != 0
    assert harness.state()["artifacts"] == artifacts
    assert not any("DELETE" in call for call in harness.state()["calls"])
    assert "Verified web artifact" not in result.stdout
    assert "projected repository pool is" not in result.stdout
    assert "attempt=3/3" in result.stderr


def test_failed_delete_keeps_replacement_and_fails_cleanup(harness: _Harness) -> None:
    artifacts = [
        _artifact(99, CURRENT_NAME, 400_000_000),
        _artifact(1, "ac-sales-xray-web-" + "b" * 40, 400_000_000),
    ]
    harness.set_state(artifacts, delete_fails=True)
    result = harness.run(RECLAIM)
    assert result.returncode != 0
    assert harness.state()["artifacts"] == artifacts
    assert "Verified web artifact" not in result.stdout


def test_workflow_keeps_retention_serialization_and_upload_order() -> None:
    assert JOB["permissions"] == {
        "actions": "write",
        "contents": "read",
        "pull-requests": "read",
    }
    assert JOB["concurrency"] == {
        "group": "application-release-packaging",
        "cancel-in-progress": False,
    }
    names = list(STEPS)
    assert names.index(ADMIT) < names.index(UPLOAD) < names.index(RECLAIM)
    assert STEPS[UPLOAD]["id"] == "upload_web"
    assert STEPS[UPLOAD]["with"]["retention-days"] == 1
    assert STEPS[RECLAIM]["env"]["UPLOADED_ARTIFACT_ID"] == (
        "${{ steps.upload_web.outputs.artifact-id }}"
    )
    assert not any(step.get("continue-on-error") for step in JOB["steps"])
    assert JOB["env"]["MAX_IMAGE_BYTES"] == "440000000"
    assert JOB["env"]["MAX_ARTIFACT_BYTES"] == "450000000"


def _pages(artifacts: list[dict]) -> list[dict]:
    return [
        {"total_count": len(artifacts), "artifacts": artifacts[start : start + 100]}
        for start in range(0, max(1, len(artifacts)), 100)
    ]


def test_multi_page_inventory_counts_every_artifact(harness: _Harness) -> None:
    artifacts = [_artifact(i, f"retained-{i}", 10_000_000) for i in range(1, 102)]
    harness.set_state(artifacts)
    result = harness.run(ADMIT)
    assert result.returncode == 0, result.stderr
    assert "pages=2 artifacts=101 bytes=1010000000" in result.stderr
    assert "projected repository pool is 1410000000" in result.stdout
    assert harness.state()["artifacts"] == artifacts


@pytest.mark.parametrize("step", [ADMIT, RECLAIM])
@pytest.mark.parametrize(
    "defect", ["gh_partial", "empty", "truncated", "missing_page", "schema", "identity", "size"]
)
def test_incomplete_inventory_fails_closed_after_bounded_retries(
    harness: _Harness, step: str, defect: str
) -> None:
    artifacts = [_artifact(99, CURRENT_NAME, 400_000_000)]
    if defect == "gh_partial":
        response = {"stdout": json.dumps(_pages(artifacts)), "returncode": 1}
    elif defect == "empty":
        response = {"stdout": ""}
    elif defect == "truncated":
        response = {"stdout": json.dumps(_pages(artifacts))[:-3]}
    elif defect == "missing_page":
        response = {"stdout": json.dumps([{"total_count": 101, "artifacts": artifacts}])}
    elif defect == "schema":
        response = {"stdout": json.dumps([{"total_count": 0, "artifacts": None}])}
    else:
        invalid = dict(artifacts[0])
        invalid["id" if defect == "identity" else "size_in_bytes"] = "invalid"
        response = {"stdout": json.dumps(_pages([invalid]))}
    response["stderr"] = "fixture-private-response-must-not-appear"
    harness.set_state(artifacts, list_results=[response] * 3)
    result = harness.run(step)
    assert result.returncode != 0
    state = harness.state()
    assert state["artifacts"] == artifacts
    assert len([call for call in state["calls"] if "--paginate" in call]) == 3
    assert not any("DELETE" in call for call in state["calls"])
    assert "Verified web artifact" not in result.stdout
    assert "projected repository pool is" not in result.stdout
    assert "attempt=3/3" in result.stderr
    assert "fixture-private-response-must-not-appear" not in result.stdout + result.stderr


@pytest.mark.parametrize("step", [ADMIT, RECLAIM])
def test_transient_inventory_failures_discard_partial_attempts(
    harness: _Harness, step: str
) -> None:
    artifacts = [_artifact(99, CURRENT_NAME, 400_000_000)]
    partial = _pages([_artifact(1, "ac-sales-xray-web-" + "b" * 40, 1_999_999_999)])
    harness.set_state(
        artifacts,
        list_results=[
            {"stdout": json.dumps(partial), "returncode": 1},
            {"stdout": json.dumps(partial)[:-2]},
        ],
    )
    result = harness.run(step)
    assert result.returncode == 0, result.stderr
    assert "attempt=3/3 complete" in result.stderr
    assert harness.state()["artifacts"] == artifacts
    assert not any("DELETE" in call for call in harness.state()["calls"])
    if step == RECLAIM:
        assert "final repository pool is 400000000" in result.stdout
    else:
        assert "projected repository pool is 400000000" in result.stdout


def test_failed_final_inventory_never_asserts_success(harness: _Harness) -> None:
    artifacts = [
        _artifact(99, CURRENT_NAME, 400_000_000),
        _artifact(1, "ac-sales-xray-web-" + "b" * 40, 400_000_000),
    ]
    harness.set_state(
        artifacts,
        list_results=[{"stdout": json.dumps(_pages(artifacts))}] + [{"stdout": "[]"}] * 3,
    )
    result = harness.run(RECLAIM)
    assert result.returncode != 0
    assert "operation=final attempt=3/3" in result.stderr
    assert "Verified web artifact" not in result.stdout
    assert harness.state()["artifacts"] == [artifacts[0]]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("id", True),
        ("id", 0),
        ("id", "99"),
        ("size_in_bytes", -1),
        ("size_in_bytes", True),
        ("size_in_bytes", 1.5),
        ("size_in_bytes", "400000000"),
        ("name", None),
        ("name", ""),
        ("expired", "false"),
    ],
)
def test_reader_rejects_invalid_artifact_schema(field: str, value: object) -> None:
    artifact = _artifact(99, CURRENT_NAME, 400_000_000)
    artifact[field] = value
    with pytest.raises(ValueError, match="invalid artifact schema"):
        INVENTORY["validate_inventory"](json.dumps(_pages([artifact])))


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "[]",
        "{}",
        '[{"artifacts": []}]',
        '[{"total_count": true, "artifacts": []}]',
        '[{"total_count": 0, "total_count": 0, "artifacts": []}]',
        '[{"total_count": 0, "artifacts": []}, {"total_count": 0, "artifacts": []}]',
        '[{"total_count": 1, "artifacts": []}]',
    ],
)
def test_reader_rejects_invalid_or_incomplete_pages(raw: str) -> None:
    with pytest.raises(ValueError):
        INVENTORY["validate_inventory"](raw)


def test_reader_rejects_missing_duplicate_and_changing_pages() -> None:
    artifacts = [_artifact(i, f"retained-{i}", 1) for i in range(1, 102)]
    pages = _pages(artifacts)
    with pytest.raises(ValueError, match="incomplete inventory"):
        INVENTORY["validate_inventory"](json.dumps(pages[:1]))
    pages[1]["total_count"] = 102
    with pytest.raises(ValueError, match="count changed"):
        INVENTORY["validate_inventory"](json.dumps(pages))
    pages = _pages([*artifacts[:100], artifacts[0]])
    with pytest.raises(ValueError, match="duplicate identity"):
        INVENTORY["validate_inventory"](json.dumps(pages))


def test_reader_accepts_proven_empty_inventory() -> None:
    assert INVENTORY["validate_inventory"](json.dumps(_pages([]))) == ([], 1)


def test_reader_timeout_is_bounded_and_discards_partial_output(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    calls = []
    sleeps = []

    def timeout(command, **options):
        calls.append((command, options))
        raise subprocess.TimeoutExpired(
            command, options["timeout"], output="partial-private-response"
        )

    monkeypatch.setattr(INVENTORY["subprocess"], "run", timeout)
    monkeypatch.setattr(INVENTORY["time"], "sleep", sleeps.append)
    with pytest.raises(ValueError, match="exhausted 3 attempts"):
        INVENTORY["read_inventory"]("/fixture/gh", "fixture/repository", "admission")
    assert len(calls) == 3
    assert all(options["timeout"] == 120 for _, options in calls)
    assert sleeps == [2, 4]
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "attempt=3/3 rejected: timeout=120s" in captured.err
    assert "partial-private-response" not in captured.err
