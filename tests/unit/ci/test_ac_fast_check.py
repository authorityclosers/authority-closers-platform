from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

from scripts.ci import ac_fast_check as FAST


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
    assert checks[1].scope == (source,)
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


def test_changed_infrastructure_module_is_linted_and_typed_with_partial_graph(
    tmp_path: Path,
) -> None:
    (tmp_path / ".venv/bin").mkdir(parents=True)
    (tmp_path / ".venv/bin/python").symlink_to(sys.executable)
    source = "infra/release/reader.py"
    write(tmp_path, source, "VALUE = 1\n")
    checks, metadata = FAST.plan(tmp_path, (source,), 12)
    assert [check.name for check in checks] == ["ruff", "mypy"]
    assert metadata["unmapped_python_sources"] == [source]


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
        write(repository, "README.md", "changed while checking\n")
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


@pytest.mark.parametrize("failure", ["dirty", "wrong_commit"])
def test_mixed_source_cannot_receive_a_passing_receipt(
    repository: Path,
    tmp_path: Path,
    failure: str,
) -> None:
    sha = git(repository, "rev-parse", "HEAD")
    write(repository, "README.md", "changed fixture\n")
    if failure == "wrong_commit":
        git(repository, "add", "README.md")
        git(repository, "commit", "-m", "different fixture head")
    receipt = tmp_path.parent / (tmp_path.name + "-unavailable.json")
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
        == 1
    )
    data = json.loads(receipt.read_text())
    assert data["status"] == "unavailable" and not data["checks"]


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


def test_runner_requires_explicit_lane_database_for_pytest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("AC_TEST_DATABASE_URL", raising=False)
    check = FAST.Check("pytest", (sys.executable, "-m", "pytest"), tmp_path, ())
    assert FAST.run_check(check, 30, 5)["status"] == "unavailable"


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
