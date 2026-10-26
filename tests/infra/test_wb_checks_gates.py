"""wb-ci runs the migration and control-plane gates at commit time (v0.86 root cause 4)."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("wb_checks_gates", ROOT / "scripts/ci/wb_checks.py")
assert SPEC and SPEC.loader
checks = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(checks)


def request(changed: list[str], named: tuple[str, ...] = ()) -> dict:
    return {"full": False, "checks": list(named), "changed_files": changed, "py_tests": []}


@pytest.mark.parametrize(
    ("changed", "expected"),
    [
        (["db/migrations/versions/20261024_0128_example.py"], {"migrations", "py"}),
        (["scripts/ci/migration_schema_gate.py"], {"migrations"}),
        (["tests/infra/test_released_migrations.py"], {"migrations", "py"}),
        (["infra/application/scripts/example.sh"], {"control"}),
        (["infra/application/systemd/ac-example.service"], {"control"}),
        (["scripts/validate-powershell.ps1"], {"control"}),
        (["apps/sales-xray-web/app/page.tsx"], {"web", "visual"}),
    ],
)
def test_changed_paths_route_to_their_gates(changed: list[str], expected: set[str]) -> None:
    assert checks.families(request(changed)) == (expected, False)


def test_an_extensionless_shell_script_is_found_by_its_shebang(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    script = tmp_path / "scripts/ops/example-tool"
    script.parent.mkdir(parents=True)
    script.write_text("#!/usr/bin/env bash\nset -eu\n", encoding="utf-8")
    (tmp_path / "scripts/ops/notes").write_text("plain text\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    assert checks.families(request(["scripts/ops/example-tool"])) == ({"control"}, False)
    assert checks.families(request(["scripts/ops/notes"])) == (set(), False)


def test_named_families_keep_the_gates_their_paths_need() -> None:
    changed = ["db/migrations/versions/20261024_0128_example.py", "infra/example.sh"]
    assert checks.families(request(changed, ("py",))) == ({"py", "migrations", "control"}, False)


def test_a_full_run_runs_every_gate() -> None:
    families, full = checks.families({"full": True, "checks": [], "changed_files": None})
    assert full and {"migrations", "control"} <= families


def test_the_plan_publishes_the_gate_switches(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / ".wb-ci").mkdir()
    (tmp_path / ".wb-ci/request.json").write_text(
        json.dumps({"changed_files": ["infra/application/scripts/example.sh"]}), encoding="utf-8"
    )
    output = tmp_path / "github-output"
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    assert checks.cmd_plan() == 0
    published = dict(line.split("=", 1) for line in output.read_text().splitlines())
    assert published["control"] == "true" and published["migrations"] == "false"


def test_the_workflow_runs_both_gates_and_reports_them() -> None:
    jobs = yaml.safe_load((ROOT / ".github/workflows/workbench-checks.yml").read_text())["jobs"]
    assert jobs["plan"]["outputs"]["migrations"] == "${{ steps.plan.outputs.migrations }}"
    assert jobs["plan"]["outputs"]["control"] == "${{ steps.plan.outputs.control }}"
    assert jobs["migrations"]["if"] == "needs.plan.outputs.migrations == 'true'"
    assert jobs["control-plane"]["if"] == "needs.plan.outputs.control == 'true'"
    migration_runs = "\n".join(step.get("run", "") for step in jobs["migrations"]["steps"])
    assert "scripts/ci/released_migrations.py --base origin/main" in migration_runs
    assert "--baseline-from-migrations" in migration_runs
    assert "forward_only_recovery_policy" in migration_runs
    fixtures = next(s for s in jobs["migrations"]["steps"] if "gate fixtures" in s.get("name", ""))
    assert fixtures["env"] == {"AC_REQUIRE_SCHEMA_GATE_DOCKER_TEST": "1"}
    control_runs = "\n".join(step.get("run", "") for step in jobs["control-plane"]["steps"])
    assert "bash scripts/validate-control-plane.sh" in control_runs
    assert "sha256sum --check --strict" in control_runs
    assert {"migrations", "control-plane"} <= set(jobs["summary"]["needs"])


def test_the_matrix_is_opt_in_and_never_part_of_a_full_run() -> None:
    full, _ = checks.families({"full": True, "checks": [], "changed_files": None})
    assert "matrix" not in full and "e2e" not in full
    assert "matrix" not in checks.families(request(["apps/sales-xray-web/app/page.tsx"]))[0]
    asked = {**request([], ("matrix",)), "routes": ["leads-table"]}
    assert checks.families(asked) == ({"matrix"}, False)


def test_the_plan_publishes_the_matrix_switch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / ".wb-ci").mkdir()
    (tmp_path / ".wb-ci/request.json").write_text(
        json.dumps({"changed_files": [], "checks": ["matrix"], "routes": ["leads-table"]}),
        encoding="utf-8",
    )
    output = tmp_path / "github-output"
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    assert checks.cmd_plan() == 0
    published = dict(line.split("=", 1) for line in output.read_text().splitlines())
    assert published["matrix"] == "true" and published["web"] == "false"


def test_the_workflow_runs_the_matrix_with_one_small_artifact() -> None:
    jobs = yaml.safe_load((ROOT / ".github/workflows/workbench-checks.yml").read_text())["jobs"]
    assert jobs["plan"]["outputs"]["matrix"] == "${{ steps.plan.outputs.matrix }}"
    assert jobs["matrix"]["if"] == "needs.plan.outputs.matrix == 'true'"
    assert "needs.plan.outputs.matrix == 'true'" in jobs["ci-prerequisites"]["if"]
    runs = "\n".join(step.get("run", "") for step in jobs["matrix"]["steps"])
    assert "node --test scripts/ci/wb_matrix_lib.test.mjs" in runs
    assert "node scripts/ci/wb_matrix.mjs" in runs
    [upload] = [s for s in jobs["matrix"]["steps"] if "upload-artifact" in s.get("uses", "")]
    assert upload["with"]["name"] == "wb-matrix" and upload["with"]["retention-days"] == 1
    assert "matrix" in jobs["summary"]["needs"]
    shipped = (ROOT / "scripts/ci/wb-ci").read_text()
    assert "--matrix) checks+=(matrix)" in shipped
    assert "scripts/ci/wb_matrix.mjs scripts/ci/wb_matrix_lib.mjs" in shipped


def test_the_radar_is_opt_in_and_never_part_of_a_full_run() -> None:
    full, _ = checks.families({"full": True, "checks": [], "changed_files": None})
    assert "radar" not in full
    assert "radar" not in checks.families(request(["apps/sales-xray-web/app/page.tsx"]))[0]
    asked = {**request([], ("radar",)), "routes": ["hub-reviewer"]}
    assert checks.families(asked) == ({"radar"}, False)
    # The nightly asks for the radar alone over the whole tree.
    alone = {"full": True, "checks": ["radar"], "changed_files": None}
    assert checks.families(alone) == ({"radar"}, True)


@pytest.mark.parametrize(
    ("routes", "shards"),
    [([], [0, 1, 2, 3, 4]), (["hub-reviewer", "leads-all"], [0, 1])],
)
def test_the_plan_shards_the_radar_by_page(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, routes: list[str], shards: list[int]
) -> None:
    (tmp_path / ".wb-ci").mkdir()
    (tmp_path / ".wb-ci/request.json").write_text(
        json.dumps({"full": True, "changed_files": None, "checks": ["radar"], "routes": routes}),
        encoding="utf-8",
    )
    output = tmp_path / "github-output"
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    assert checks.cmd_plan() == 0
    published = dict(line.split("=", 1) for line in output.read_text().splitlines())
    assert published["radar"] == "true" and json.loads(published["radar_shards"]) == shards
    assert published["radar_count"] == str(len(shards)) and published["py"] == "false"


def test_the_workflow_shards_the_radar_and_merges_one_report() -> None:
    jobs = yaml.safe_load((ROOT / ".github/workflows/workbench-checks.yml").read_text())["jobs"]
    assert jobs["plan"]["outputs"]["radar"] == "${{ steps.plan.outputs.radar }}"
    assert jobs["radar"]["if"] == "needs.plan.outputs.radar == 'true'"
    assert "needs.plan.outputs.radar == 'true'" in jobs["ci-prerequisites"]["if"]
    shards = jobs["radar"]["strategy"]["matrix"]["shard"]
    assert shards == "${{ fromJSON(needs.plan.outputs.radar_shards) }}"
    runs = "\n".join(step.get("run", "") for step in jobs["radar"]["steps"])
    assert "node --test scripts/ci/wb_radar_lib.test.mjs" in runs
    assert "--shard ${{ matrix.shard }}/${{ needs.plan.outputs.radar_count }}" in runs
    report = jobs["radar-report"]
    assert report["needs"] == ["plan", "radar"] and report["if"].startswith("always()")
    # Only when shards ran: a cancelled prerequisite must not turn into a failed report.
    assert "needs.radar.result == 'success' || needs.radar.result == 'failure'" in report["if"]
    merge = "\n".join(step.get("run", "") for step in report["steps"])
    # Merging needs plain Node: no install, no browser.
    assert "node scripts/ci/wb_radar.mjs merge" in merge and "pnpm install" not in merge
    fold = report["steps"][-1]
    assert fold["uses"].startswith("actions/upload-artifact/merge@")
    assert fold["with"]["name"] == "wb-radar" and fold["with"]["retention-days"] == 1
    assert {"radar", "radar-report"} <= set(jobs["summary"]["needs"])
    shipped = (ROOT / "scripts/ci/wb-ci").read_text()
    assert "--radar) checks+=(radar)" in shipped
    assert "scripts/ci/wb_radar.mjs scripts/ci/wb_radar_lib.mjs" in shipped


def test_the_speed_check_is_opt_in_and_builds_its_own_production_screens() -> None:
    full, _ = checks.families({"full": True, "checks": [], "changed_files": None})
    assert "speed" not in full
    nightly = {"full": True, "checks": ["radar", "speed"], "changed_files": None}
    assert checks.families(nightly) == ({"radar", "speed"}, True)
    jobs = yaml.safe_load((ROOT / ".github/workflows/workbench-checks.yml").read_text())["jobs"]
    assert jobs["plan"]["outputs"]["speed"] == "${{ steps.plan.outputs.speed }}"
    assert jobs["speed"]["if"] == "needs.plan.outputs.speed == 'true'"
    assert "needs.plan.outputs.speed == 'true'" in jobs["ci-prerequisites"]["if"]
    [build] = [s for s in jobs["speed"]["steps"] if "build" in s.get("run", "")]
    # The fixture screens exist only in this build (next.config.ts pageExtensions).
    assert build["env"]["AC_SALES_XRAY_PERF_FIXTURES"] == "1"
    runs = "\n".join(step.get("run", "") for step in jobs["speed"]["steps"])
    assert "node --test scripts/ci/wb_speed_lib.test.mjs" in runs
    assert "node scripts/ci/wb_speed.mjs" in runs
    [upload] = [s for s in jobs["speed"]["steps"] if "upload-artifact" in s.get("uses", "")]
    assert upload["with"]["name"] == "wb-speed" and upload["with"]["retention-days"] == 1
    assert "speed" in jobs["summary"]["needs"]
    shipped = (ROOT / "scripts/ci/wb-ci").read_text()
    assert "--speed) checks+=(speed)" in shipped
    assert "scripts/ci/wb_speed.mjs scripts/ci/wb_speed_lib.mjs" in shipped
