from __future__ import annotations

import json
import os
import runpy
import shlex
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest
import yaml

from scripts.ci import ac_fast_check as FAST


def vitest_evidence(
    *,
    passed: int = 0,
    skipped: int = 0,
    todo: int = 0,
    failed: int = 0,
    failed_suites: int = 0,
    success: bool = True,
) -> str:
    return json.dumps(
        {
            "numPassedTests": passed,
            "numPendingTests": skipped,
            "numTodoTests": todo,
            "numFailedTests": failed,
            "numFailedTestSuites": failed_suites,
            "numTotalTests": passed + skipped + todo + failed,
            "success": success,
            "testResults": [{"message": "fixture-private-output"}],
        }
    )


@pytest.mark.parametrize(
    ("evidence", "related", "exit_code", "expected_status"),
    [
        (vitest_evidence(passed=1), False, 0, "passed"),
        (vitest_evidence(skipped=1), False, 0, "partial"),
        (vitest_evidence(passed=1, skipped=1), False, 0, "partial"),
        (vitest_evidence(todo=1), False, 0, "partial"),
        (vitest_evidence(), False, 0, "failed"),
        (vitest_evidence(), True, 0, "partial"),
        (vitest_evidence(failed=1), False, 0, "failed"),
        (vitest_evidence(passed=1, failed_suites=1), False, 0, "failed"),
        (vitest_evidence(passed=1, success=False), False, 0, "failed"),
        (vitest_evidence(passed=1), False, 1, "failed"),
    ],
)
def test_vitest_receipts_distinguish_executed_from_missing_coverage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    evidence: str,
    related: bool,
    exit_code: int,
    expected_status: str,
) -> None:
    reports = []
    original_summary = FAST.vitest_summary

    def summary(path):
        reports.append(path)
        return original_summary(path)

    monkeypatch.setattr(FAST, "vitest_summary", summary)
    script = (
        "import pathlib, sys\n"
        "report = next(value for value in sys.argv if value.startswith('--outputFile='))\n"
        "assert '--reporter=json' in sys.argv[:sys.argv.index('--')]\n"
        "assert sys.argv.index(report) < sys.argv.index('--')\n"
        f"pathlib.Path(report.split('=', 1)[1]).write_text({evidence!r})\n"
        "print('fixture-private-output')\n"
        f"sys.exit({exit_code})\n"
    )
    check = FAST.Check(
        "vitest-related:fixture" if related else "vitest:fixture",
        (sys.executable, "-c", script, "--", "fixture.test.ts"),
        tmp_path,
        ("fixture.test.ts",),
    )
    result = FAST.run_check(check, 30, 5)
    assert result["status"] == expected_status
    assert result["returncode"] == exit_code
    document = json.loads(evidence)
    assert result["vitest_summary"] == {
        "passed": document["numPassedTests"],
        "skipped": document["numPendingTests"],
        "todo": document["numTodoTests"],
        "failed": document["numFailedTests"],
        "failed_suites": document["numFailedTestSuites"],
    }
    assert reports and all(not report.parent.exists() for report in reports)
    assert "fixture-private-output" not in json.dumps(result) + capsys.readouterr().out


@pytest.mark.parametrize("malformed_suites", (False, True))
def test_failed_vitest_receipt_keeps_only_committed_suite_paths(
    tmp_path: Path, malformed_suites: bool
) -> None:
    write(tmp_path, "fixture.test.ts", "// committed test fixture\n")
    document = json.loads(vitest_evidence(failed=1))
    document["testResults"] = (
        None
        if malformed_suites
        else [
            {
                "name": str(tmp_path / "fixture.test.ts"),
                "status": "failed",
                "message": "fixture-private-output",
                "assertionResults": [
                    {
                        "title": "fixture-private-output",
                        "failureMessages": ["fixture-private-output"],
                    }
                ],
            },
            {"name": "../external.test.ts", "status": "failed"},
        ]
    )
    script = (
        "import pathlib, sys\n"
        "report = next(value for value in sys.argv if value.startswith('--outputFile='))\n"
        f"pathlib.Path(report.split('=', 1)[1]).write_text({json.dumps(document)!r})\n"
        "print('fixture-private-output'); sys.exit(1)\n"
    )
    check = FAST.Check(
        "vitest:fixture", (sys.executable, "-c", script), tmp_path, ("fixture.test.ts",)
    )
    result = FAST.run_check(check, 30, 5)
    assert result["status"] == "failed"
    assert result["diagnostics"] == (
        [] if malformed_suites else ["fixture.test.ts: Vitest suite failed"]
    )
    assert "fixture-private-output" not in json.dumps(result)


@pytest.mark.parametrize(
    "evidence",
    [
        None,
        "not json",
        "[]",
        "{}",
        vitest_evidence(passed=1).replace('"numTotalTests": 1', '"numTotalTests": 2'),
        vitest_evidence(passed=1).replace('"numPassedTests": 1', '"numPassedTests": true'),
        vitest_evidence(passed=-1),
        vitest_evidence(passed=1).replace('"success": true', '"success": 1'),
    ],
)
def test_success_without_valid_vitest_evidence_is_refused(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    evidence: str | None,
) -> None:
    reports = []
    original_summary = FAST.vitest_summary

    def summary(path):
        reports.append(path)
        return original_summary(path)

    monkeypatch.setattr(FAST, "vitest_summary", summary)
    script = (
        "import pathlib, sys\n"
        "report = next(value.split('=', 1)[1] for value in sys.argv "
        "if value.startswith('--outputFile='))\n"
        f"evidence = {evidence!r}\n"
        "if evidence is not None: pathlib.Path(report).write_text(evidence)\n"
    )
    check = FAST.Check("vitest:fixture", (sys.executable, "-c", script), tmp_path, ())
    result = FAST.run_check(check, 30, 5)
    assert result["status"] == "failed" and result["returncode"] == 0
    assert result["reason"] == "Vitest did not produce valid test evidence"
    assert "vitest_summary" not in result
    assert reports and all(not report.parent.exists() for report in reports)
    assert "fixture-private-output" not in json.dumps(result)


@pytest.mark.parametrize(
    ("evidence", "expected_status", "expected_summary"),
    [
        (vitest_evidence(passed=1), "passed", None),
        (vitest_evidence(passed=1, todo=1), "partial", "1 selected Vitest cases skipped or todo"),
        (vitest_evidence(), "partial", "1 Vitest checks collected no tests"),
    ],
)
def test_main_reports_unexecuted_vitest_coverage(
    repository: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    evidence: str,
    expected_status: str,
    expected_summary: str | None,
) -> None:
    original_plan = FAST.plan

    def vitest_plan(root, changed, cap):
        _, metadata = original_plan(root, changed, cap)
        return (FAST.Check("vitest-related:fixture", ("fixture",), root, ()),), metadata

    def execute(check, seconds, cpu_remaining):
        report = next(
            value.split("=", 1)[1] for value in check.argv if value.startswith("--outputFile=")
        )
        Path(report).write_text(evidence)
        return {"name": check.name, "status": "passed", "returncode": 0}

    monkeypatch.setattr(FAST, "plan", vitest_plan)
    monkeypatch.setattr(FAST, "_run_check", execute)
    receipt = tmp_path.parent / (tmp_path.name + "-vitest-coverage.json")
    assert FAST.main(["--root", str(repository), "--base", "HEAD", "--receipt", str(receipt)]) == 0
    data = json.loads(receipt.read_text())
    assert data["status"] == data["checks"][0]["status"] == expected_status
    assert data["commit"] == git(repository, "rev-parse", "HEAD")
    output = capsys.readouterr().out
    if expected_summary is not None:
        assert expected_summary in output
    assert "fixture-private-output" not in json.dumps(data) + output


@pytest.fixture(autouse=True)
def shared_slot_adapter(
    tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Unit subprocess checks do not depend on the server's installed launcher."""
    directory = tmp_path_factory.mktemp("shared-slot-adapter")
    launcher = directory / "ac-heavy"
    launcher.write_text(
        f"#!{sys.executable}\nimport os, sys\nos.execv(sys.argv[1], sys.argv[1:])\n"
    )
    launcher.chmod(0o700)
    monkeypatch.setenv("PATH", str(directory) + os.pathsep + os.environ.get("PATH", ""))


def write(root: Path, relative: str, content: str) -> None:
    target = root / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content)


def test_static_graph_follows_absolute_relative_and_transitive_imports(tmp_path: Path) -> None:
    write(tmp_path, "packages/python/ac_platform/__init__.py", "")
    write(tmp_path, "packages/python/ac_platform/policy.py", "VALUE = 1\n")
    write(tmp_path, "packages/python/ac_platform/service.py", "from .policy import VALUE\n")
    write(tmp_path, "tests/helpers.py", "from ac_platform.service import VALUE\n")
    write(tmp_path, "tests/test_related.py", "from .helpers import VALUE\n")
    write(tmp_path, "tests/test_unrelated.py", "import json\n")
    selected, errors = FAST.affected_tests(tmp_path, ("packages/python/ac_platform/policy.py",))
    assert selected == ("tests/test_related.py",)
    assert errors == ()


def test_deleted_module_still_selects_its_importers(tmp_path: Path) -> None:
    write(tmp_path, "tests/test_deleted.py", "from ac_platform.gone import VALUE\n")
    selected, errors = FAST.affected_tests(tmp_path, ("packages/python/ac_platform/gone.py",))
    assert selected == ("tests/test_deleted.py",)
    assert errors == ()


def test_package_initializer_changes_select_submodule_importers(tmp_path: Path) -> None:
    write(tmp_path, "packages/python/ac_platform/__init__.py", "")
    write(tmp_path, "packages/python/ac_platform/policy.py", "")
    write(tmp_path, "tests/test_package.py", "import ac_platform.policy\n")
    selected, _ = FAST.affected_tests(tmp_path, ("packages/python/ac_platform/__init__.py",))
    assert selected == ("tests/test_package.py",)


def test_conftest_dependency_changes_select_every_test_in_its_scope(tmp_path: Path) -> None:
    source = "packages/python/ac_platform/policy.py"
    write(tmp_path, source, "VALUE = 1\n")
    write(tmp_path, "tests/database/conftest.py", "from ac_platform.policy import VALUE\n")
    write(tmp_path, "tests/database/test_a.py", "def test_a(): pass\n")
    write(tmp_path, "tests/database/test_b.py", "def test_b(): pass\n")
    write(tmp_path, "tests/unit/test_other.py", "def test_other(): pass\n")
    selected, _ = FAST.affected_tests(tmp_path, (source,))
    assert selected == ("tests/database/test_a.py", "tests/database/test_b.py")


def test_syntax_errors_are_reported_instead_of_silently_claiming_coverage(tmp_path: Path) -> None:
    write(tmp_path, "tests/test_changed.py", "def broken(\n")
    selected, errors = FAST.affected_tests(tmp_path, ("tests/test_changed.py",))
    assert selected == ("tests/test_changed.py",)
    assert errors == ("tests/test_changed.py",)


def test_cap_prioritises_changed_tests_and_reports_every_omission() -> None:
    selected, omitted = FAST.capped_tests(
        ("tests/test_a.py", "tests/test_b.py", "tests/test_c.py"), ("tests/test_c.py",), 2
    )
    assert selected == ("tests/test_c.py", "tests/test_a.py")
    assert omitted == ("tests/test_b.py",)
    with pytest.raises(FAST.FastCheckError):
        FAST.capped_tests(selected, (), 0)


def test_symlink_cannot_select_code_outside_checkout(tmp_path: Path) -> None:
    outside = tmp_path / "outside.py"
    outside.write_text("pass\n")
    root = tmp_path / "checkout"
    root.mkdir()
    (root / "escape.py").symlink_to(outside)
    with pytest.raises(FAST.FastCheckError, match="inside the checkout"):
        FAST.safe_path(root, "escape.py")


def test_frontend_plan_uses_installed_tools_and_persistent_caches(tmp_path: Path) -> None:
    app = "apps/sales-xray-web"
    source = f"{app}/app/sample.ts"
    test = f"{app}/app/sample.test.ts"
    for path in (source, test):
        write(tmp_path, path, "export {};\n")
    for tool in ("prettier", "eslint", "tsc", "vitest"):
        binary = tmp_path / f"{app}/node_modules/.bin/{tool}"
        write(tmp_path, binary.relative_to(tmp_path).as_posix(), "#!/bin/sh\nexit 0\n")
        binary.chmod(0o700)
    checks, metadata = FAST.plan(tmp_path, (source, test), 12)
    names = [check.name.split(":")[0] for check in checks]
    assert names == ["prettier", "eslint", "vitest", "vitest-related", "tsc"]
    for check in checks[:2]:
        assert "--cache" in check.argv
        assert "--cache-location" in check.argv
    assert "--incremental" in checks[4].argv
    assert checks[2].argv[1] == "run"
    assert checks[3].argv[1:3] == ("related", "--run")
    assert all("install" not in check.argv for check in checks)
    assert all("--maxWorkers=1" in check.argv for check in checks[2:4])
    assert metadata["omitted_pytest"] == []


def test_missing_frontend_tool_refuses_to_install(tmp_path: Path) -> None:
    path = "apps/sales-xray-web/app/sample.ts"
    write(tmp_path, path, "export {};\n")
    with pytest.raises(FAST.FastCheckError, match="Installed frontend tool unavailable"):
        FAST.plan(tmp_path, (path,), 12)


def test_shared_package_change_selects_transitive_workspace_consumers(tmp_path: Path) -> None:
    write(tmp_path, "packages/typescript/ui/package.json", '{"name":"@ac/ui"}')
    write(
        tmp_path,
        "packages/typescript/review/package.json",
        '{"name":"@ac/review", "dependencies":{"@ac/ui":"workspace:*"}}',
    )
    write(
        tmp_path,
        "apps/sales-xray-web/package.json",
        '{"dependencies":{"@ac/review":"workspace:*"}}',
    )
    write(tmp_path, "apps/unrelated-web/package.json", "{}")
    path = "packages/typescript/ui/src/button.tsx"
    assert FAST.app_groups(tmp_path, (path,)) == {"apps/sales-xray-web": (path,)}


def test_python_plan_checks_changed_module_and_related_tests(tmp_path: Path) -> None:
    (tmp_path / ".venv/bin").mkdir(parents=True)
    (tmp_path / ".venv/bin/python").symlink_to(sys.executable)
    source = "packages/python/ac_platform/policy.py"
    write(tmp_path, source, "VALUE = 1\n")
    write(tmp_path, "tests/test_related.py", "from ac_platform.policy import VALUE\n")
    checks, _ = FAST.plan(tmp_path, (source,), 12)
    assert [check.name for check in checks] == ["ruff", "mypy", "pytest"]
    assert checks[0].scope == (source,)
    assert checks[1].scope == ("packages/python",)
    assert checks[1].argv[-1] == "packages/python"
    assert "--follow-imports=silent" not in checks[1].argv
    assert checks[2].scope == ("tests/test_related.py",)
    assert all("-m" in check.argv for check in checks)


def test_frontend_config_only_change_still_typechecks_the_app(tmp_path: Path) -> None:
    app = "apps/sales-xray-web"
    source = f"{app}/tsconfig.json"
    write(tmp_path, source, "{}\n")
    for tool in ("prettier", "tsc"):
        binary = tmp_path / f"{app}/node_modules/.bin/{tool}"
        write(tmp_path, binary.relative_to(tmp_path).as_posix(), "#!/bin/sh\nexit 0\n")
        binary.chmod(0o700)
    checks, _ = FAST.plan(tmp_path, (source,), 12)
    assert [check.name.split(":")[0] for check in checks] == ["prettier", "tsc"]


@pytest.mark.parametrize(
    ("changed", "required"),
    [
        (".github/workflows/application.yml", "tests/infra/test_recovery_ci_gates.py"),
        (".github/workflows/control-plane.yml", "tests/infra/test_recovery_ci_gates.py"),
        ("scripts/ci/python-test-exclusions.txt", "tests/infra/test_recovery_ci_gates.py"),
        ("scripts/ci/python-test-durations.json", "tests/unit/ci/test_measured_shards.py"),
    ],
)
def test_non_python_ci_inputs_run_guards_and_report_capped_coverage(
    tmp_path: Path, changed: str, required: str
) -> None:
    (tmp_path / ".venv/bin").mkdir(parents=True)
    (tmp_path / ".venv/bin/python").symlink_to(sys.executable)
    for test in (
        "tests/infra/test_recovery_ci_gates.py",
        "tests/unit/ci/test_python_test_shard.py",
        "tests/unit/ci/test_measured_shards.py",
        "tests/unit/ci/test_refresh_python_durations.py",
    ):
        write(tmp_path, test, "def test_fixture(): pass\n")
    checks, metadata = FAST.plan(tmp_path, (changed,), 12)
    assert [check.name for check in checks] == ["pytest"]
    assert required in checks[0].scope
    assert metadata["unmapped_ci_inputs"] == []
    capped, limited = FAST.plan(tmp_path, (changed,), 1)
    assert set(capped[0].scope) | set(limited["omitted_pytest"]) == set(checks[0].scope)


def test_workflow_input_routes_the_existing_static_browser_contract(tmp_path: Path) -> None:
    root = Path(FAST.__file__).resolve().parents[2]
    guard_path = "tests/infra/test_recovery_ci_gates.py"
    (tmp_path / ".venv/bin").mkdir(parents=True)
    (tmp_path / ".venv/bin/python").symlink_to(sys.executable)
    for path in (
        guard_path,
        "tests/unit/ci/test_python_test_shard.py",
        "tests/unit/ci/test_measured_shards.py",
    ):
        write(tmp_path, path, (root / path).read_text())
    changed = ".github/workflows/application.yml"
    write(tmp_path, changed, (root / changed).read_text())
    checks, _ = FAST.plan(tmp_path, (changed,), 12)
    assert guard_path in checks[0].scope
    namespace = runpy.run_path(str(tmp_path / guard_path))
    contract = namespace["test_sales_xray_static_preview_is_built_before_application_validation"]
    contract()
    workflow = yaml.safe_load((tmp_path / changed).read_text())
    steps = workflow["jobs"]["validate-python-gates"]["steps"]
    steps[:] = [
        step
        for step in steps
        if step.get("name") != "PRE-VALIDATION: Build Sales Xray static preview"
    ]
    (tmp_path / changed).write_text(yaml.safe_dump(workflow))
    with pytest.raises(AssertionError, match="Missing or duplicated required step"):
        contract()


def test_missing_ci_guard_cannot_be_silently_omitted(tmp_path: Path) -> None:
    with pytest.raises(FAST.FastCheckError, match="required CI input regression"):
        FAST.plan(tmp_path, (".github/workflows/application.yml",), 12)


def workspace_fixture(root: Path) -> tuple[str, str, str]:
    package = "packages/typescript/shared"
    source = f"{package}/src/index.ts"
    test = f"{package}/src/index.test.ts"
    write(root, f"{package}/package.json", '{"name":"@ac/shared"}')
    write(root, source, "export const value = 1;\n")
    write(root, test, "import { value } from './index';\n")
    for app in ("apps/first-web", "apps/second-web"):
        write(root, f"{app}/package.json", '{"dependencies":{"@ac/shared":"workspace:*"}}')
        write(root, f"{app}/eslint.config.mjs", "export default [];\n")
        for tool in ("prettier", "eslint", "tsc", "vitest"):
            binary = root / f"{app}/node_modules/.bin/{tool}"
            write(root, binary.relative_to(root).as_posix(), "#!/bin/sh\nexit 0\n")
            binary.chmod(0o700)
    return package, source, test


def test_shared_lint_uses_the_consumer_config_from_the_repository_base(tmp_path: Path) -> None:
    _, source, _ = workspace_fixture(tmp_path)
    checks, _ = FAST.plan(tmp_path, (source,), 12)
    lint = [check for check in checks if check.name.startswith("eslint-shared:")]
    assert len(lint) == 2
    for check in lint:
        app = check.name.split(":", 1)[1]
        assert check.cwd == tmp_path
        assert check.argv[check.argv.index("--config") + 1] == str(
            tmp_path / app / "eslint.config.mjs"
        )
        assert check.argv[-1] == source
        assert check.scope == (source,)


def test_shared_tests_run_once_from_their_own_package_using_installed_tools(tmp_path: Path) -> None:
    package, _, test = workspace_fixture(tmp_path)
    checks, _ = FAST.plan(tmp_path, (test,), 12)
    direct = [check for check in checks if check.name.startswith("vitest:")]
    assert len(direct) == 1
    check = direct[0]
    assert check.cwd == tmp_path / package
    assert check.argv[0] == str(tmp_path / "apps/first-web/node_modules/.bin/vitest")
    assert check.argv[-1] == "src/index.test.ts"
    assert "--passWithNoTests" not in check.argv
    assert check.scope == (test,)


def test_shared_source_also_checks_related_package_tests(tmp_path: Path) -> None:
    package, source, _ = workspace_fixture(tmp_path)
    checks, _ = FAST.plan(tmp_path, (source,), 12)
    package_checks = [check for check in checks if check.name == f"vitest-related:{package}"]
    assert len(package_checks) == 1
    check = package_checks[0]
    assert check.cwd == tmp_path / package
    assert check.argv[1:3] == ("related", "--run")
    assert check.argv[-1] == "src/index.ts"


def test_direct_app_tests_cannot_pass_when_nothing_is_collected(tmp_path: Path) -> None:
    app = "apps/sales-xray-web"
    test = f"{app}/app/sample.test.ts"
    write(tmp_path, test, "export {};\n")
    for tool in ("prettier", "eslint", "tsc", "vitest"):
        binary = tmp_path / f"{app}/node_modules/.bin/{tool}"
        write(tmp_path, binary.relative_to(tmp_path).as_posix(), "#!/bin/sh\nexit 0\n")
        binary.chmod(0o700)
    checks, _ = FAST.plan(tmp_path, (test,), 12)
    check = next(check for check in checks if check.name == f"vitest:{app}")
    assert "--passWithNoTests" not in check.argv


@pytest.mark.parametrize("other_fails", (False, True))
def test_installed_vitest_deduplicates_direct_files_but_keeps_other_importers(
    tmp_path: Path, other_fails: bool
) -> None:
    installed = Path(FAST.__file__).resolve().parents[2] / "apps/sales-xray-web/node_modules"
    if not (installed / ".bin/vitest").is_file():
        pytest.skip("Installed frontend tools are required for this integration proof")
    app = "apps/sales-xray-web"
    direct = f"{app}/app/[call]/direct.test.ts"
    source = f"{app}/app/value.ts"
    write(tmp_path, source, "export const value = 1;\n")
    write(
        tmp_path,
        direct,
        "import {test,expect} from 'vitest'; import {value} from '../value';\n"
        "test('direct',()=>expect(value).toBe(1));\n",
    )
    write(
        tmp_path,
        f"{app}/app/other.test.ts",
        "import {test,expect} from 'vitest'; import {value} from './value';\n"
        f"test('other',()=>expect(value).toBe({2 if other_fails else 1}));\n",
    )
    write(
        tmp_path,
        f"{app}/vitest.config.mjs",
        "export default {test:{include:['app/**/*.test.ts']}};\n",
    )
    modules = tmp_path / app / "node_modules"
    (modules / ".bin").mkdir(parents=True)
    for tool in ("prettier", "eslint", "tsc"):
        binary = FAST.node_tool(installed.parents[2], installed.parent, tool)
        (modules / ".bin" / tool).symlink_to(Path(binary).resolve())
    # pnpm's app wrapper refers to its original relative store layout. Point
    # this isolated fixture directly at the same installed Vitest entrypoint.
    wrapper = modules / ".bin/vitest"
    node = shutil.which("node")
    assert node is not None
    entry = (installed / "vitest/vitest.mjs").resolve()
    wrapper.write_text(f'#!/bin/sh\nexec {shlex.quote(node)} {shlex.quote(str(entry))} "$@"\n')
    wrapper.chmod(0o755)
    (modules / "vitest").symlink_to((installed / "vitest").resolve(), target_is_directory=True)
    checks, metadata = FAST.plan(tmp_path, (direct, source), 12)
    direct_check = next(check for check in checks if check.name == f"vitest:{app}")
    related_check = next(check for check in checks if check.name == f"vitest-related:{app}")
    assert metadata["deduplicated_vitest_files"] == {app: [direct]}
    first = FAST.run_check(direct_check, 30, 15)
    second = FAST.run_check(related_check, 30, 15)
    assert first["status"] == "passed", first
    assert first["vitest_summary"]["passed"] == 1
    assert second["status"] == ("failed" if other_fails else "passed")
    assert second["vitest_summary"]["passed"] == (0 if other_fails else 1)
    assert second["vitest_summary"]["failed"] == int(other_fails)


def test_shared_package_related_check_deduplicates_its_direct_tests(tmp_path: Path) -> None:
    package, source, test = workspace_fixture(tmp_path)
    checks, metadata = FAST.plan(tmp_path, (source, test), 12)
    related = next(check for check in checks if check.name == f"vitest-related:{package}")
    assert related.argv[related.argv.index("--exclude") + 1] == "src/index.test.ts"
    assert related.argv[-1] == "src/index.ts"
    assert metadata["deduplicated_vitest_files"] == {package: [test]}


@pytest.mark.parametrize("defer", (False, True))
def test_explicit_related_deferral_preserves_required_direct_checks_and_partial_receipt(
    repository: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, defer: bool
) -> None:
    app = "apps/sales-xray-web"
    direct = f"{app}/app/direct.test.ts"
    source = f"{app}/app/source.ts"
    write(repository, direct, "export {};\n")
    write(repository, source, "export const value = 1;\n")
    git(repository, "add", "apps")
    git(repository, "commit", "-m", "explicit frontend deferral fixture")
    for tool in ("prettier", "eslint", "tsc", "vitest"):
        binary = repository / app / "node_modules/.bin" / tool
        write(repository, binary.relative_to(repository).as_posix(), "#!/bin/sh\nexit 0\n")
        binary.chmod(0o755)
    executed = []

    def synthetic_check(check, _wall, _cpu):
        executed.append(check.name)
        return {
            "name": check.name,
            "status": "failed" if check.name.startswith("vitest-related:") else "passed",
        }

    monkeypatch.setattr(FAST, "run_check", synthetic_check)
    receipt = tmp_path.parent / (tmp_path.name + "-related-deferral.json")
    argv = ["--root", str(repository), "--base", "HEAD~1", "--receipt", str(receipt)]
    if defer:
        argv.append("--defer-related-vitest")
    assert FAST.main(argv) == (0 if defer else 1)
    data = json.loads(receipt.read_text())
    assert data["status"] == ("partial" if defer else "failed")
    assert f"vitest:{app}" in executed and f"tsc:{app}" in executed
    assert (f"vitest-related:{app}" in executed) is not defer
    assert data["deferred_related_vitest"] == (
        [{"name": f"vitest-related:{app}", "scope": [source]}] if defer else []
    )


def test_changed_infrastructure_module_is_linted_with_partial_graph(
    tmp_path: Path,
) -> None:
    (tmp_path / ".venv/bin").mkdir(parents=True)
    (tmp_path / ".venv/bin/python").symlink_to(sys.executable)
    source = "infra/release/reader.py"
    write(tmp_path, source, "VALUE = 1\n")
    checks, metadata = FAST.plan(tmp_path, (source,), 12)
    assert [check.name for check in checks] == ["ruff"]
    assert metadata["unmapped_python_sources"] == [source]


def test_infrastructure_changes_keep_mypy_at_the_hosted_packages_scope(tmp_path: Path) -> None:
    (tmp_path / ".venv/bin").mkdir(parents=True)
    (tmp_path / ".venv/bin/python").symlink_to(sys.executable)
    write(tmp_path, "packages/python/ac_platform/value.py", "VALUE = 1\n")
    source = "infra/release/legacy.py"
    write(tmp_path, source, "def legacy(): return 'untyped'\n")
    checks, _ = FAST.plan(tmp_path, (source,), 12)
    assert [check.name for check in checks] == ["ruff", "mypy"]
    assert checks[0].scope == (source,)
    assert checks[1].scope == ("packages/python",)
    assert checks[1].argv[-1] == "packages/python"
    assert source not in checks[1].argv


def git(root: Path, *args: str) -> str:
    executable = shutil.which("git")
    assert executable is not None
    result = subprocess.run(  # noqa: S603 - synthetic fixture repository, fixed argument arrays
        [executable, "-C", str(root), "-c", "core.hooksPath=/dev/null", *args],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


@pytest.fixture
def repository(tmp_path: Path) -> Path:
    git(tmp_path, "init", "--initial-branch=main")
    git(tmp_path, "config", "user.name", "Synthetic Fast Check")
    git(tmp_path, "config", "user.email", "fast-check@example.invalid")
    write(tmp_path, "README.md", "synthetic fixture\n")
    git(tmp_path, "add", "README.md")
    git(tmp_path, "commit", "-m", "fixture base")
    return tmp_path


def test_noop_receipt_attests_exact_clean_commit(repository: Path, tmp_path: Path) -> None:
    receipt = tmp_path.parent / (tmp_path.name + "-receipt.json")
    sha = git(repository, "rev-parse", "HEAD")
    assert (
        FAST.main(
            [
                "--root",
                str(repository),
                "--commit",
                sha,
                "--base",
                "HEAD",
                "--receipt",
                str(receipt),
            ]
        )
        == 0
    )
    data = json.loads(receipt.read_text())
    assert data["status"] == "passed"
    assert data["commit"] == sha
    assert data["changed_files"] == data["checks"] == []


def test_unknown_workflow_receipt_reports_partial_coverage(
    repository: Path, tmp_path: Path
) -> None:
    changed = ".github/workflows/new-gate.yml"
    write(repository, changed, "jobs: {}\n")
    git(repository, "add", changed)
    git(repository, "commit", "-m", "unknown synthetic workflow")
    receipt = tmp_path.parent / (tmp_path.name + "-unknown-ci.json")
    assert (
        FAST.main(["--root", str(repository), "--base", "HEAD~1", "--receipt", str(receipt)]) == 0
    )
    data = json.loads(receipt.read_text())
    assert data["status"] == "partial"
    assert data["unmapped_ci_inputs"] == [changed]
    assert data["checks"] == []


@pytest.mark.parametrize("dirty", [False, True])
def test_workbench_default_head_exports_committed_source_despite_live_edits(
    repository: Path,
    tmp_path: Path,
    dirty: bool,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sha = git(repository, "rev-parse", "HEAD")
    original_plan = FAST.plan

    def inspect(root, changed, cap):
        assert root != repository
        assert (root / "README.md").read_text() == "synthetic fixture\n"
        return original_plan(root, changed, cap)

    monkeypatch.setattr(FAST, "plan", inspect)
    if dirty:
        write(repository, "README.md", "builder has uncommitted edits\n")
    receipt = tmp_path.parent / (tmp_path.name + "-workbench.json")
    exit_code = FAST.main(["--root", str(repository), "--base", "HEAD", "--receipt", str(receipt)])
    data = json.loads(receipt.read_text())
    assert data["commit"] == sha
    assert data["checks"] == []
    assert exit_code == 0 and data["status"] == "passed"
    assert data["changed_files"] == []
    assert data["source_mode"] == "committed-snapshot"
    assert len(data["source_sha256"]) == 64
    assert (repository / "README.md").read_text() == (
        "builder has uncommitted edits\n" if dirty else "synthetic fixture\n"
    )


@pytest.mark.parametrize("target", ["new", "tracked", "symlink"])
def test_receipt_cannot_write_into_checked_source(repository: Path, target: str) -> None:
    original = (repository / "README.md").read_bytes()
    if target == "symlink":
        receipt = repository.parent / (repository.name + "-symlink.json")
        receipt.symlink_to(repository / "README.md")
    else:
        receipt = repository / ("README.md" if target == "tracked" else "receipt.json")
    assert (
        FAST.main(
            [
                "--root",
                str(repository),
                "--commit",
                "HEAD",
                "--base",
                "HEAD",
                "--receipt",
                str(receipt),
            ]
        )
        != 0
    )
    assert (repository / "README.md").read_bytes() == original
    assert not (repository / "receipt.json").exists()


def test_source_mutation_during_a_check_invalidates_the_receipt(
    repository: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sha = git(repository, "rev-parse", "HEAD")
    receipt = tmp_path.parent / (tmp_path.name + "-changed-receipt.json")
    original_plan = FAST.plan

    def plan(root, changed, cap):
        _, metadata = original_plan(root, changed, cap)
        return (FAST.Check("synthetic", (), root, ()),), metadata

    def mutate(check, *args):
        write(check.cwd, "README.md", "changed while checking\n")
        return {"name": check.name, "status": "passed"}

    monkeypatch.setattr(FAST, "plan", plan)
    monkeypatch.setattr(FAST, "run_check", mutate)
    assert (
        FAST.main(
            [
                "--root",
                str(repository),
                "--commit",
                sha,
                "--base",
                "HEAD",
                "--receipt",
                str(receipt),
            ]
        )
        == 1
    )
    assert json.loads(receipt.read_text())["status"] == "unavailable"
    assert (repository / "README.md").read_text() == "synthetic fixture\n"


@pytest.mark.parametrize("failure", ["dirty", "wrong_commit"])
def test_pinned_source_excludes_dirty_files_and_newer_commits(
    repository: Path,
    tmp_path: Path,
    failure: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sha = git(repository, "rev-parse", "HEAD")
    write(repository, "README.md", "changed fixture\n")
    if failure == "wrong_commit":
        git(repository, "add", "README.md")
        git(repository, "commit", "-m", "different fixture head")
    receipt = tmp_path.parent / (tmp_path.name + "-unavailable.json")
    original_plan = FAST.plan

    def inspect(root, changed, cap):
        assert (root / "README.md").read_text() == "synthetic fixture\n"
        return original_plan(root, changed, cap)

    monkeypatch.setattr(FAST, "plan", inspect)
    assert (
        FAST.main(
            [
                "--root",
                str(repository),
                "--commit",
                sha,
                "--base",
                "main",
                "--receipt",
                str(receipt),
            ]
        )
        == 0
    )
    data = json.loads(receipt.read_text())
    assert data["status"] == "passed" and not data["checks"]
    assert data["commit"] == sha
    assert (repository / "README.md").read_text() == "changed fixture\n"


def test_runner_does_not_echo_child_output_or_environment(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FIXTURE_PRIVATE_VALUE", "fixture-private-output")
    check = FAST.Check(
        "synthetic",
        (sys.executable, "-c", "print('fixture-private-output')"),
        tmp_path,
        ("fixture",),
    )
    result = FAST.run_check(check, 30, 5)
    assert result["status"] == "passed"
    assert "fixture-private-output" not in json.dumps(result)
    assert "fixture-private-output" not in capsys.readouterr().out


@pytest.mark.parametrize(
    ("name", "output", "expected"),
    (
        (
            "mypy",
            'module.py:12: error: Secret "fixture-private-output" [assignment]',
            "module.py:12: mypy error [assignment]",
        ),
        (
            "tsc:fixture",
            "module.py(2,3): error TS2345: fixture-private-output",
            "module.py:2:3: TypeScript error TS2345",
        ),
        ("prettier:fixture", "[warn] module.py", "module.py: formatting differs"),
        (
            "ruff",
            "F401 fixture-private-output\n --> module.py:5:2",
            "module.py:5:2: Ruff error F401",
        ),
        (
            "eslint:fixture",
            "module.py\n 5:2 error fixture-private-output no-unused-vars",
            "module.py:5:2: ESLint error no-unused-vars",
        ),
        (
            "pytest",
            "FAILED module.py::test_value[fixture-private-output] - AssertionError",
            "module.py::test_value: failed",
        ),
    ),
)
def test_failure_details_keep_locations_and_codes_without_payloads(
    tmp_path: Path, name: str, output: str, expected: str
) -> None:
    write(tmp_path, "module.py", "VALUE = 1\n")
    check = FAST.Check(name, (), tmp_path, ("module.py",))
    assert FAST.failure_diagnostics(check, output + "\nfixture-private-output") == [expected]


def test_failure_details_refuse_external_paths_and_bound_repeated_errors(tmp_path: Path) -> None:
    write(tmp_path, "module.py", "VALUE = 1\n")
    outside = tmp_path.parent / (tmp_path.name + "-private.py")
    outside.write_text("VALUE = 'fixture-private-output'\n")
    check = FAST.Check("mypy", (), tmp_path, ("module.py",))
    output = f"{outside}:1: error: fixture-private-output [assignment]\n"
    output += "\n".join(
        f"module.py:{line}: error: fixture-private-output [assignment]" for line in range(50)
    )
    details = FAST.failure_diagnostics(check, output)
    assert len(details) == 40
    assert details[0] == "module.py:0: mypy error [assignment]"
    assert "fixture-private-output" not in json.dumps(details)
    assert str(outside) not in json.dumps(details)


def test_failed_runner_drains_verbose_output_and_keeps_only_safe_details(tmp_path: Path) -> None:
    write(tmp_path, "module.py", "VALUE = 1\n")
    check = FAST.Check(
        "mypy",
        (
            sys.executable,
            "-c",
            "import sys; print('module.py:9: error: fixture-private-output [assignment]'); "
            "print('fixture-private-output' * 60000); sys.exit(1)",
        ),
        tmp_path,
        ("module.py",),
    )
    result = FAST.run_check(check, 30, 5)
    assert result["status"] == "failed"
    assert result["diagnostics"] == ["module.py:9: mypy error [assignment]"]
    assert "fixture-private-output" not in json.dumps(result)


def test_runner_requires_explicit_lane_database_for_pytest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("AC_TEST_DATABASE_URL", raising=False)
    check = FAST.Check("pytest", (sys.executable, "-m", "pytest"), tmp_path, ())
    assert FAST.run_check(check, 30, 5)["status"] == "unavailable"


@pytest.mark.parametrize(
    ("body", "expected_status", "expected_counts"),
    [
        ("def test_pass(): pass\n", "passed", (1, 0, 0, 0)),
        (
            "def test_skip(): pytest.skip('fixture-private-output')\n",
            "partial",
            (0, 1, 0, 0),
        ),
        (
            "def test_pass(): pass\ndef test_skip(): pytest.skip('fixture-private-output')\n",
            "partial",
            (1, 1, 0, 0),
        ),
        (
            "@pytest.mark.xfail(reason='fixture-private-output')\n"
            "def test_expected_failure(): assert False\n",
            "partial",
            (0, 1, 0, 0),
        ),
        (
            "def test_fail(): assert False, 'fixture-private-output'\n"
            "def test_skip(): pytest.skip('fixture-private-output')\n",
            "failed",
            (0, 1, 1, 0),
        ),
        (
            "@pytest.fixture\ndef broken(): raise RuntimeError('fixture-private-output')\n"
            "def test_error(broken): pass\n",
            "failed",
            (0, 0, 0, 1),
        ),
    ],
)
def test_pytest_receipt_records_execution_and_never_echoes_skip_reasons(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    body: str,
    expected_status: str,
    expected_counts: tuple[int, int, int, int],
) -> None:
    write(tmp_path, "test_fixture.py", "import pytest\n" + body)
    monkeypatch.setenv("AC_TEST_DATABASE_URL", "fixture-only")
    monkeypatch.setenv("PYTEST_ADDOPTS", "")
    monkeypatch.setenv("PYTEST_DISABLE_PLUGIN_AUTOLOAD", "1")
    reports = []
    original_summary = FAST.pytest_summary

    def summary(path):
        reports.append(path)
        return original_summary(path)

    monkeypatch.setattr(FAST, "pytest_summary", summary)
    check = FAST.Check(
        "pytest",
        (sys.executable, "-m", "pytest", "-q", "--", "test_fixture.py"),
        tmp_path,
        ("test_fixture.py",),
    )
    result = FAST.run_check(check, 30, 10)
    assert result["status"] == expected_status
    counts = result["pytest_summary"]
    assert (
        tuple(counts[key] for key in ("passed", "skipped", "failed", "errors")) == expected_counts
    )
    assert reports and all(not report.parent.exists() for report in reports)
    assert "fixture-private-output" not in json.dumps(result)
    assert "fixture-private-output" not in capsys.readouterr().out


@pytest.mark.parametrize(
    ("evidence", "valid"),
    [
        (None, False),
        ("not xml", False),
        ("<testsuites />", False),
        (
            '<testsuite><testcase><failure message="fixture-private-output" />'
            "</testcase></testsuite>",
            True,
        ),
        (
            '<testsuite><testcase><error message="fixture-private-output" />'
            "</testcase></testsuite>",
            True,
        ),
    ],
)
def test_success_without_passing_pytest_evidence_is_refused(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    evidence: str | None,
    valid: bool,
) -> None:
    monkeypatch.setenv("AC_TEST_DATABASE_URL", "fixture-only")
    script = (
        "import pathlib, sys\n"
        "report = next((value.split('=', 1)[1] for value in sys.argv "
        "if value.startswith('--junitxml=')), None)\n"
        f"evidence = {evidence!r}\n"
        "if report is not None and evidence is not None:\n"
        "    pathlib.Path(report).write_text(evidence)\n"
    )
    check = FAST.Check("pytest", (sys.executable, "-c", script), tmp_path, ())
    result = FAST.run_check(check, 30, 5)
    assert result["status"] == "failed"
    assert result["returncode"] == 0
    if valid:
        counts = result["pytest_summary"]
        assert counts["failed"] + counts["errors"] == 1
    else:
        assert result["reason"] == "Pytest did not produce valid test evidence"
    assert "fixture-private-output" not in json.dumps(result)


@pytest.mark.parametrize("skip", [False, True])
def test_main_receipt_distinguishes_passing_from_unexecuted_pytest_coverage(
    repository: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    skip: bool,
) -> None:
    body = "import pytest\ndef test_fixture(): " + (
        "pytest.skip('fixture-private-output')\n" if skip else "pass\n"
    )
    write(repository, "tests/test_fixture.py", body)
    git(repository, "add", "tests/test_fixture.py")
    git(repository, "commit", "-m", "synthetic optional test")
    monkeypatch.setenv("AC_TEST_DATABASE_URL", "fixture-only")
    monkeypatch.setenv("PYTEST_ADDOPTS", "")
    monkeypatch.setenv("PYTEST_DISABLE_PLUGIN_AUTOLOAD", "1")
    original_plan = FAST.plan

    def pytest_plan(root, changed, cap):
        # Use real coverage metadata, without requiring unrelated installed linters.
        (root / ".venv/bin").mkdir(parents=True)
        (root / ".venv/bin/python").symlink_to(sys.executable)
        _, metadata = original_plan(root, changed, cap)
        return (
            FAST.Check(
                "pytest",
                (sys.executable, "-m", "pytest", "-q", "--", "tests/test_fixture.py"),
                root,
                ("tests/test_fixture.py",),
            ),
        ), metadata

    # The installed interpreter link is fixture setup, not a source mutation.
    write(repository, ".gitignore", ".venv/\n.pytest_cache/\n__pycache__/\n")
    git(repository, "add", ".gitignore")
    git(repository, "commit", "-m", "ignore synthetic interpreter")
    monkeypatch.setattr(FAST, "plan", pytest_plan)
    receipt = tmp_path.parent / (tmp_path.name + "-pytest-coverage.json")
    assert (
        FAST.main(["--root", str(repository), "--base", "HEAD~2", "--receipt", str(receipt)]) == 0
    )
    data = json.loads(receipt.read_text())
    assert data["status"] == ("partial" if skip else "passed")
    assert data["checks"][0]["pytest_summary"]["skipped"] == int(skip)
    output = capsys.readouterr().out
    if skip:
        assert "1 selected pytest cases skipped" in output
    assert "fixture-private-output" not in output + json.dumps(data)


def test_runner_requires_installed_shared_slot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = FAST.shutil.which
    monkeypatch.setattr(
        FAST.shutil, "which", lambda name: None if name == "ac-heavy" else original(name)
    )
    check = FAST.Check("synthetic", (sys.executable, "-c", "raise AssertionError"), tmp_path, ())
    result = FAST.run_check(check, 30, 5)
    assert result["status"] == "unavailable"
    assert result["reason"] == "The shared heavy slot is required"


def test_exported_python_imports_take_precedence_over_live_editable_source(
    repository: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    write(repository, "packages/python/snapshot_fixture.py", "VALUE = 'committed'\n")
    git(repository, "add", "packages")
    git(repository, "commit", "-m", "python source fixture")
    write(repository, "packages/python/snapshot_fixture.py", "VALUE = 'uncommitted'\n")
    monkeypatch.setenv("PYTHONPATH", str(repository / "packages/python"))
    with FAST.SNAPSHOT.committed_snapshot(repository, "HEAD") as exported:
        check = FAST.Check(
            "synthetic",
            (
                sys.executable,
                "-c",
                "import snapshot_fixture; assert snapshot_fixture.VALUE == 'committed'",
            ),
            exported.root,
            ("packages/python/snapshot_fixture.py",),
            source_root=exported.root,
        )
        assert FAST.run_check(check, 30, 5)["status"] == "passed"
        assert exported.unchanged()
        assert not (exported.root / "packages/python/__pycache__").exists()
    assert (
        repository / "packages/python/snapshot_fixture.py"
    ).read_text() == "VALUE = 'uncommitted'\n"


@pytest.mark.skipif(
    shutil.which("node") is None, reason="Node is required for workspace resolution"
)
def test_installed_node_tool_imports_exported_nested_workspace_source(
    repository: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    write(repository, "packages/typescript/ui/index.js", "module.exports = 'committed';\n")
    git(repository, "add", "packages")
    git(repository, "commit", "-m", "node source fixture")
    write(repository, "packages/typescript/ui/index.js", "module.exports = 'uncommitted';\n")
    installed = repository / "node_modules/.pnpm/tool@1/node_modules"
    write(
        repository,
        "node_modules/.pnpm/tool@1/node_modules/tool/index.js",
        "require('node:assert/strict').equal(require('@ac/ui'), 'committed');\n",
    )
    (installed / "@ac").mkdir()
    (installed / "@ac/ui").symlink_to(
        repository / "packages/typescript/ui", target_is_directory=True
    )
    monkeypatch.setenv("NODE_OPTIONS", "--require /missing/live-builder-hook.js")
    with FAST.SNAPSHOT.committed_snapshot(repository, "HEAD") as exported:
        script = exported.root / "node_modules/.pnpm/tool@1/node_modules/tool/index.js"
        node = shutil.which("node")
        assert node is not None
        check = FAST.Check(
            "synthetic", (node, str(script)), exported.root, (), source_root=exported.root
        )
        assert FAST.run_check(check, 30, 5)["status"] == "passed"
        assert exported.unchanged()
    assert (
        repository / "packages/typescript/ui/index.js"
    ).read_text() == "module.exports = 'uncommitted';\n"


@pytest.mark.skipif(
    shutil.which("node") is None, reason="Node is required for workspace resolution"
)
def test_export_keeps_shared_dependency_identity_for_a_workspace_consumer(repository: Path) -> None:
    write(
        repository, "packages/typescript/ui/index.js", "exports.singleton = require('singleton');\n"
    )
    git(repository, "add", "packages")
    git(repository, "commit", "-m", "workspace dependency identity fixture")
    installed = repository / "node_modules/.pnpm/tool@1/node_modules"
    singleton = repository / "node_modules/.pnpm/singleton@1/node_modules/singleton"
    write(
        repository,
        "node_modules/.pnpm/singleton@1/node_modules/singleton/index.js",
        "module.exports = {};\n",
    )
    write(
        repository,
        "node_modules/.pnpm/tool@1/node_modules/tool/index.js",
        "require('node:assert/strict').equal(require('singleton'), require('@ac/ui').singleton);\n",
    )
    (installed / "@ac").mkdir()
    (installed / "@ac/ui").symlink_to(
        repository / "packages/typescript/ui", target_is_directory=True
    )
    (installed / "singleton").symlink_to(singleton, target_is_directory=True)
    modules = repository / "packages/typescript/ui/node_modules"
    modules.mkdir()
    (modules / "singleton").symlink_to(singleton, target_is_directory=True)
    node = shutil.which("node")
    assert node is not None
    with FAST.SNAPSHOT.committed_snapshot(repository, "HEAD") as exported:
        script = exported.root / "node_modules/.pnpm/tool@1/node_modules/tool/index.js"
        check = FAST.Check(
            "synthetic", (node, str(script)), exported.root, (), source_root=exported.root
        )
        assert FAST.run_check(check, 30, 5)["status"] == "passed"
        assert exported.unchanged()


@pytest.mark.skipif(
    shutil.which("node") is None, reason="Node is required for workspace resolution"
)
def test_node_resolution_uses_committed_workspace_manifest(repository: Path) -> None:
    write(repository, "packages/typescript/ui/index.js", "module.exports = 'committed';\n")
    write(repository, "packages/typescript/ui/package.json", '{"name": "@ac/ui"}\n')
    git(repository, "add", "packages")
    git(repository, "commit", "-m", "workspace manifest fixture")
    write(repository, "packages/typescript/ui/package.json", "invalid builder draft\n")
    installed = repository / "node_modules/.pnpm/tool@1/node_modules"
    write(
        repository,
        "node_modules/.pnpm/tool@1/node_modules/tool/index.js",
        "require('node:assert/strict').equal(require('@ac/ui'), 'committed');\n",
    )
    (installed / "@ac").mkdir()
    (installed / "@ac/ui").symlink_to(
        repository / "packages/typescript/ui", target_is_directory=True
    )
    node = shutil.which("node")
    assert node is not None
    with FAST.SNAPSHOT.committed_snapshot(repository, "HEAD") as exported:
        script = exported.root / "node_modules/.pnpm/tool@1/node_modules/tool/index.js"
        check = FAST.Check(
            "synthetic", (node, str(script)), exported.root, (), source_root=exported.root
        )
        assert FAST.run_check(check, 30, 5)["status"] == "passed"
        assert exported.unchanged()
    assert (
        repository / "packages/typescript/ui/package.json"
    ).read_text() == "invalid builder draft\n"


def test_builder_commit_during_checks_keeps_the_original_snapshot(
    repository: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sha = git(repository, "rev-parse", "HEAD")
    original_plan = FAST.plan
    exported_paths = []

    def plan(root, changed, cap):
        _, metadata = original_plan(root, changed, cap)
        exported_paths.append(root)
        return (FAST.Check("synthetic", (), root, ()),), metadata

    def commit_during_check(check, *args):
        write(repository, "README.md", "new committed work\n")
        git(repository, "add", "README.md")
        git(repository, "commit", "-m", "builder finishes work")
        assert (check.cwd / "README.md").read_text() == "synthetic fixture\n"
        return {"name": check.name, "status": "passed"}

    monkeypatch.setattr(FAST, "plan", plan)
    monkeypatch.setattr(FAST, "run_check", commit_during_check)
    receipt = tmp_path.parent / (tmp_path.name + "-pinned-check.json")
    assert FAST.main(["--root", str(repository), "--base", "HEAD", "--receipt", str(receipt)]) == 0
    data = json.loads(receipt.read_text())
    assert data["status"] == "passed" and data["commit"] == sha
    assert git(repository, "rev-parse", "HEAD") != sha
    assert exported_paths and not exported_paths[0].parent.exists()


def test_nested_checks_respect_an_inherited_cpu_hard_limit(tmp_path: Path) -> None:
    root = Path(FAST.__file__).resolve().parents[2]
    script = (
        "import pathlib, resource, sys\n"
        f"sys.path.insert(0, {str(root)!r})\n"
        "from scripts.ci import ac_fast_check as fast\n"
        "resource.setrlimit(resource.RLIMIT_CPU, (3, 3))\n"
        f"directory = pathlib.Path({str(tmp_path)!r})\n"
        "check = fast.Check('nested', (sys.executable, '-c', 'pass'), directory, ())\n"
        "assert fast.run_check(check, 10, 30)['status'] == 'passed'\n"
        "assert resource.getrlimit(resource.RLIMIT_CPU) == (3, 3)\n"
    )
    check = FAST.Check("synthetic", (sys.executable, "-c", script), tmp_path, ())
    assert FAST.run_check(check, 30, 5)["status"] == "passed"


def test_timeout_stops_a_child_without_claiming_success(tmp_path: Path) -> None:
    check = FAST.Check(
        "synthetic",
        (sys.executable, "-c", "import time; time.sleep(60)"),
        tmp_path,
        (),
    )
    result = FAST.run_check(check, 0.2, 5)
    assert result["status"] == "timed_out" and result["returncode"] == 124
    assert result["wall_seconds"] < 5


def test_cpu_budget_stops_busy_work_before_wall_timeout(tmp_path: Path) -> None:
    check = FAST.Check(
        "synthetic",
        (sys.executable, "-c", "while True: pass"),
        tmp_path,
        (),
    )
    result = FAST.run_check(check, 10, 0.05)
    assert result["status"] == "budget_exhausted"
    assert result["wall_seconds"] < 5


@pytest.mark.parametrize(
    ("parent_sleep", "budget", "expected"), [(60, 2, "timed_out"), (1.2, 5, "passed")]
)
def test_exit_also_stops_descendants_in_separate_process_groups(
    tmp_path: Path, parent_sleep: float, budget: float, expected: str
) -> None:
    script = tmp_path / "parent.py"
    script.write_text(
        "import pathlib, subprocess, sys, time\n"
        "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'], "
        "start_new_session=True)\n"
        "pathlib.Path('child.pid').write_text(str(child.pid))\n"
        f"time.sleep({parent_sleep})\n"
    )
    check = FAST.Check("synthetic", (sys.executable, str(script)), tmp_path, ())
    result = FAST.run_check(check, budget, 5)
    assert result["status"] == expected
    identity = int((tmp_path / "child.pid").read_text())
    stat = Path(f"/proc/{identity}/stat")
    deadline = time.monotonic() + 1
    while stat.exists() and stat.read_text().rsplit(")", 1)[1].split()[0] != "Z":
        assert time.monotonic() < deadline, "check left a live descendant"
        time.sleep(0.01)
