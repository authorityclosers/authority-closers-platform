#!/usr/bin/env python3
"""Run bounded checks on an exported local commit while the workbench stays live."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import math
import os
import re
import resource
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import xml.etree.ElementTree as element_tree
from collections import defaultdict, deque
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.ci import committed_snapshot as SNAPSHOT  # noqa: E402

SCHEMA = "ac.ci.fast-check/1"
NATIVE_IMAGE_WORKFLOW = ".github/workflows/sales-xray-native-image.yml"
PYTHON_ROOTS = ("packages/python", "tests", "scripts")
SOURCE_SUFFIXES = {".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs"}
FORMAT_SUFFIXES = SOURCE_SUFFIXES | {".css", ".json", ".md", ".mdx", ".yaml", ".yml"}
CI_INPUT_TESTS = {
    ".github/workflows/application.yml": (
        "tests/infra/test_recovery_ci_gates.py",
        "tests/unit/ci/test_python_test_shard.py",
        "tests/unit/ci/test_measured_shards.py",
    ),
    ".github/workflows/control-plane.yml": ("tests/infra/test_recovery_ci_gates.py",),
    "scripts/ci/python-test-exclusions.txt": (
        "tests/infra/test_recovery_ci_gates.py",
        "tests/unit/ci/test_python_test_shard.py",
    ),
    "scripts/ci/python-test-durations.json": (
        "tests/unit/ci/test_python_test_shard.py",
        "tests/unit/ci/test_measured_shards.py",
        "tests/unit/ci/test_refresh_python_durations.py",
    ),
}


class FastCheckError(RuntimeError):
    """A bounded diagnostic that does not contain command output or credentials."""


@dataclass(frozen=True)
class Check:
    name: str
    argv: tuple[str, ...]
    cwd: Path
    scope: tuple[str, ...]
    source_root: Path | None = None


def git(root: Path, *args: str) -> str:
    executable = shutil.which("git")
    if executable is None:
        raise FastCheckError("Git is unavailable; installs are forbidden")
    result = subprocess.run(  # noqa: S603 - fixed local git argument arrays, no shell
        [executable, "-C", str(root), *args],
        capture_output=True,
        text=True,
        check=False,
        timeout=15,
    )
    if result.returncode:
        raise FastCheckError("Local Git metadata could not be read")
    return result.stdout


def commit_sha(root: Path, value: str) -> str:
    return git(root, "rev-parse", "--verify", "--end-of-options", value + "^{commit}").strip()


def safe_path(root: Path, relative: str) -> Path:
    path = root / relative
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        raise FastCheckError("Changed files must remain inside the checkout") from None
    if Path(relative).is_absolute() or ".." in Path(relative).parts:
        raise FastCheckError("Changed file identity is not relative to the checkout")
    return path


def changed_files(root: Path, base: str, commit: str) -> tuple[str, ...]:
    values = git(root, "diff", "--name-only", "-z", base + "..." + commit, "--").split("\0")
    paths = tuple(sorted({value for value in values if value}))
    for path in paths:
        if Path(path).is_absolute() or ".." in Path(path).parts:
            raise FastCheckError("Changed file identity is not relative to the checkout")
    return paths


def native_inputs_changed(root: Path, changed: Sequence[str]) -> tuple[str, ...]:
    """Read the checked workflow's exact paths and recursive directory inputs."""
    try:
        import yaml  # type: ignore[import-untyped]  # installed with the locked environment
    except ImportError:
        raise FastCheckError(
            "Native workflow reader is unavailable; installs are forbidden"
        ) from None
    try:
        value = yaml.safe_load(safe_path(root, NATIVE_IMAGE_WORKFLOW).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError):
        raise FastCheckError("Committed native workflow could not be read") from None
    if isinstance(value, dict):
        # SafeLoader can parse GitHub's unquoted `on` key as a YAML 1.1 boolean.
        value = value.get("on", value.get(True))
    for key in ("push", "paths"):
        if not isinstance(value, dict):
            raise FastCheckError("Committed native workflow paths are unavailable")
        value = value.get(key)
    if not isinstance(value, list) or not value:
        raise FastCheckError("Committed native workflow paths are unavailable")
    for pattern in value:
        if not isinstance(pattern, str) or not re.fullmatch(
            r"[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*(?:/\*\*)?", pattern
        ):
            raise FastCheckError("Native workflow paths must be exact paths or directory /** globs")
        safe_path(root, pattern[:-3] if pattern.endswith("/**") else pattern)
    return tuple(
        sorted(
            {
                path
                for path in changed
                if any(
                    path == pattern or (pattern.endswith("/**") and path.startswith(pattern[:-2]))
                    for pattern in value
                )
            }
        )
    )


def module_name(relative: str) -> str | None:
    path = Path(relative)
    if path.suffix != ".py":
        return None
    for prefix in PYTHON_ROOTS:
        if relative.startswith(prefix + "/"):
            parts = path.with_suffix("").parts
            if prefix == "packages/python":
                parts = parts[2:]
            if parts[-1] == "__init__":
                parts = parts[:-1]
            return ".".join(parts)
    return None


def imported_modules(tree: ast.AST, module: str, package_file: bool) -> set[str]:
    package = module.split(".") if package_file else module.split(".")[:-1]
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                if node.level > len(package):
                    continue
                prefix = package[: len(package) - node.level + 1]
                name = ".".join([*prefix, *([node.module] if node.module else [])])
            else:
                name = node.module or ""
            if name:
                imports.add(name)
                imports.update(name + "." + alias.name for alias in node.names if alias.name != "*")
    return imports


def import_graph(
    root: Path, changed: Sequence[str]
) -> tuple[dict[str, set[str]], dict[str, str], tuple[str, ...]]:
    files = {}
    for prefix in PYTHON_ROOTS:
        for path in sorted((root / prefix).rglob("*.py")):
            relative = path.relative_to(root).as_posix()
            module = module_name(relative)
            if module is not None:
                safe_path(root, relative)
                files[module] = relative
    known = set(files) | {name for path in changed if (name := module_name(path)) is not None}
    graph: dict[str, set[str]] = {}
    errors = []
    for module, relative in files.items():
        try:
            tree = ast.parse((root / relative).read_text(encoding="utf-8"))
        except (OSError, UnicodeError, SyntaxError):
            errors.append(relative)
            graph[module] = set()
            continue
        imports = imported_modules(tree, module, Path(relative).name == "__init__.py")
        dependencies = set()
        for imported in imports:
            parts = imported.split(".")
            for length in range(1, len(parts) + 1):
                candidate = ".".join(parts[:length])
                if candidate in known and candidate != module:
                    dependencies.add(candidate)
        graph[module] = dependencies
    return graph, files, tuple(sorted(errors))


def affected_tests(root: Path, changed: Sequence[str]) -> tuple[tuple[str, ...], tuple[str, ...]]:
    if not any(path.endswith(".py") for path in changed):
        return (), ()
    graph, files, errors = import_graph(root, changed)
    reverse: dict[str, set[str]] = defaultdict(set)
    for module, dependencies in graph.items():
        for dependency in dependencies:
            reverse[dependency].add(module)
    seen = {name for path in changed if (name := module_name(path)) is not None}
    queue = deque(sorted(seen))
    while queue:
        for dependent in sorted(reverse[queue.popleft()]):
            if dependent not in seen:
                seen.add(dependent)
                queue.append(dependent)
    tests = {
        files[module]
        for module in seen & files.keys()
        if files[module].startswith("tests/")
        and (
            Path(files[module]).name.startswith("test_")
            or Path(files[module]).name.endswith("_test.py")
        )
    }
    conftests = [
        files[module] for module in seen & files.keys() if Path(files[module]).name == "conftest.py"
    ]
    conftests.extend(path for path in changed if Path(path).name == "conftest.py")
    for conftest in conftests:
        prefix = Path(conftest).parent.as_posix()
        for relative in files.values():
            if (
                relative.startswith("tests/")
                and (prefix == "." or relative.startswith(prefix + "/"))
                and (
                    Path(relative).name.startswith("test_")
                    or Path(relative).name.endswith("_test.py")
                )
            ):
                tests.add(relative)
    # A modified test is still relevant when no production module imports it.
    tests.update(
        path
        for path in changed
        if path.startswith("tests/")
        and path.endswith(".py")
        and Path(path).name.startswith("test_")
        and (root / path).is_file()
    )
    return tuple(sorted(tests)), errors


def capped_tests(
    tests: Sequence[str], changed: Sequence[str], cap: int
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    if cap < 1:
        raise FastCheckError("The test-file cap must be positive")
    direct = set(changed)
    ordered = sorted(set(tests), key=lambda path: (path not in direct, path))
    return tuple(ordered[:cap]), tuple(ordered[cap:])


def app_groups(root: Path, changed: Iterable[str]) -> dict[str, tuple[str, ...]]:
    paths = tuple(changed)
    grouped: dict[str, list[str]] = defaultdict(list)
    for path in paths:
        parts = Path(path).parts
        if len(parts) > 2 and parts[0] == "apps" and parts[1].endswith("-web"):
            grouped["/".join(parts[:2])].append(path)
    shared = tuple(path for path in paths if path.startswith("packages/typescript/"))
    if shared:
        manifests = {}
        try:
            for manifest in sorted((root / "packages/typescript").glob("*/package.json")):
                safe_path(root, manifest.relative_to(root).as_posix())
                document = json.loads(manifest.read_text())
                manifests[manifest.parent.relative_to(root).as_posix()] = document
            affected = {
                document["name"]
                for directory, document in manifests.items()
                if any(path.startswith(directory + "/") for path in shared)
            }
            while True:
                updated = affected | {
                    document["name"]
                    for document in manifests.values()
                    if affected.intersection(
                        set(document.get("dependencies", {}))
                        | set(document.get("peerDependencies", {}))
                    )
                }
                if updated == affected:
                    break
                affected = updated
            shared_config = any(path.startswith("packages/typescript/config/") for path in shared)
            for manifest in sorted((root / "apps").glob("*-web/package.json")):
                safe_path(root, manifest.relative_to(root).as_posix())
                document = json.loads(manifest.read_text())
                if shared_config or affected.intersection(
                    set(document.get("dependencies", {})) | set(document.get("devDependencies", {}))
                ):
                    grouped[manifest.parent.relative_to(root).as_posix()].extend(shared)
        except (KeyError, TypeError, ValueError, OSError):
            raise FastCheckError("Workspace dependency metadata could not be read") from None
    return {app: tuple(sorted(set(values))) for app, values in sorted(grouped.items())}


def node_tool(root: Path, app: Path, name: str, *, fallbacks: Sequence[Path] = ()) -> str:
    for directory in (app, root, *fallbacks):
        binary = directory / "node_modules/.bin" / name
        if binary.is_file() and os.access(binary, os.X_OK):
            return str(binary)
    raise FastCheckError(f"Installed frontend tool unavailable: {name}")


def exclude_test_flags(paths: Iterable[str]) -> tuple[str, ...]:
    """Use literal file globs so route brackets cannot exclude unrelated tests."""
    return tuple(
        argument
        for path in paths
        for argument in (
            "--exclude",
            "".join("\\" + value if value in r"\*?[]{}()!+@" else value for value in path),
        )
    )


def plan(
    root: Path, changed: tuple[str, ...], test_cap: int, *, defer_related_vitest: bool = False
) -> tuple[tuple[Check, ...], dict[str, Any]]:
    checks = []
    deduplicated: dict[str, list[str]] = {}
    python = root / ".venv/bin/python"
    pyfiles = tuple(path for path in changed if path.endswith(".py") and (root / path).is_file())
    tests, graph_errors = affected_tests(root, changed)
    ci_tests = {test for path in changed for test in CI_INPUT_TESTS.get(path, ())}
    for test in sorted(ci_tests):
        if not safe_path(root, test).is_file():
            raise FastCheckError("A required CI input regression is unavailable")
    selected, omitted = capped_tests((*tests, *ci_tests), changed, test_cap)
    if (pyfiles or selected) and not python.is_file():
        raise FastCheckError("The locked Python environment is unavailable; installs are forbidden")
    if pyfiles:
        checks.append(
            Check("ruff", (str(python), "-m", "ruff", "check", "--", *pyfiles), root, pyfiles)
        )
        # Match the hosted static gate; infrastructure scripts and migrations
        # are linted/tested here but are not in CI's mypy contract.
        if (root / "packages/python").is_dir():
            checks.append(
                Check(
                    "mypy",
                    (
                        str(python),
                        "-m",
                        "mypy",
                        "--incremental",
                        "packages/python",
                    ),
                    root,
                    ("packages/python",),
                )
            )
    if selected:
        checks.append(
            Check(
                "pytest",
                (str(python), "-m", "pytest", "-q", "-x", "--", *selected),
                root,
                selected,
            )
        )
    groups = app_groups(root, changed)
    vitest_flags = ("--maxWorkers=1", "--no-file-parallelism")
    for app, paths in groups.items():
        directory = root / app
        existing = tuple(path for path in paths if (root / path).is_file())
        formatting = tuple(path for path in existing if Path(path).suffix in FORMAT_SUFFIXES)
        source = tuple(path for path in existing if Path(path).suffix in SOURCE_SUFFIXES)

        def relative(values: Iterable[str], app_path: str = app) -> tuple[str, ...]:
            return tuple(Path(os.path.relpath(path, app_path)).as_posix() for path in values)

        cache = directory / "node_modules/.cache/ac-fast-check"
        if formatting:
            checks.append(
                Check(
                    f"prettier:{app}",
                    (
                        node_tool(root, directory, "prettier"),
                        "--check",
                        "--cache",
                        "--cache-location",
                        str(cache / "prettier"),
                        "--",
                        *relative(formatting),
                    ),
                    directory,
                    formatting,
                )
            )
        if source:
            app_source = tuple(path for path in source if path.startswith(app + "/"))
            shared_source = tuple(path for path in source if path not in app_source)
            eslint = node_tool(root, directory, "eslint")
            if app_source:
                checks.append(
                    Check(
                        f"eslint:{app}",
                        (
                            eslint,
                            "--cache",
                            "--cache-location",
                            str(cache / "eslint"),
                            "--max-warnings",
                            "0",
                            "--",
                            *relative(app_source),
                        ),
                        directory,
                        app_source,
                    )
                )
            if shared_source:
                config = next(
                    (
                        directory / f"eslint.config.{extension}"
                        for extension in ("mjs", "js", "cjs", "ts", "mts", "cts")
                        if (directory / f"eslint.config.{extension}").is_file()
                    ),
                    None,
                )
                if config is None:
                    raise FastCheckError("The consumer ESLint config is unavailable")
                # Explicit config plus repository cwd makes shared files fall
                # inside ESLint's base path while retaining the consumer rules.
                checks.append(
                    Check(
                        f"eslint-shared:{app}",
                        (
                            eslint,
                            "--config",
                            str(config),
                            "--cache",
                            "--cache-location",
                            str(cache / "eslint-shared"),
                            "--max-warnings",
                            "0",
                            "--",
                            *shared_source,
                        ),
                        root,
                        shared_source,
                    )
                )
            direct_tests = tuple(
                path for path in app_source if ".test." in path or ".spec." in path
            )
            related = tuple(
                path for path in source if ".test." not in path and ".spec." not in path
            )
            if direct_tests:
                checks.append(
                    Check(
                        f"vitest:{app}",
                        (
                            node_tool(root, directory, "vitest"),
                            "run",
                            *vitest_flags,
                            *relative(direct_tests),
                        ),
                        directory,
                        direct_tests,
                    )
                )
            if related:
                if direct_tests:
                    deduplicated[app] = list(direct_tests)
                checks.append(
                    Check(
                        f"vitest-related:{app}",
                        (
                            node_tool(root, directory, "vitest"),
                            "related",
                            "--run",
                            *vitest_flags,
                            "--passWithNoTests",
                            # These exact files already have a direct check.
                            # Keep other importers selected by Vitest's graph.
                            *exclude_test_flags(relative(direct_tests)),
                            *relative(related),
                        ),
                        directory,
                        related,
                    )
                )
        checks.append(
            Check(
                f"tsc:{app}",
                (
                    node_tool(root, directory, "tsc"),
                    "--noEmit",
                    "--incremental",
                    "--project",
                    "tsconfig.json",
                ),
                directory,
                (app,),
            )
        )
    shared_packages: dict[str, list[str]] = defaultdict(list)
    for path in changed:
        parts = Path(path).parts
        if (
            len(parts) > 3
            and parts[:2] == ("packages", "typescript")
            and Path(path).suffix in SOURCE_SUFFIXES
            and (root / path).is_file()
        ):
            shared_packages["/".join(parts[:3])].append(path)
    for package, package_paths in sorted(shared_packages.items()):
        directory = root / package
        # Packages need their own root for test discovery. Reuse an installed
        # consumer binary when necessary; never install or execute a package
        # test repeatedly from every consumer app.
        vitest = node_tool(
            root, directory, "vitest", fallbacks=tuple(sorted((root / "apps").glob("*-web")))
        )
        direct = tuple(path for path in package_paths if ".test." in path or ".spec." in path)
        related = tuple(path for path in package_paths if path not in direct)
        if direct and related:
            deduplicated[package] = list(direct)
        for values, kind in ((direct, "vitest"), (related, "vitest-related")):
            if not values:
                continue
            mode = ("run",) if kind == "vitest" else ("related", "--run")
            flags = (
                vitest_flags
                if kind == "vitest"
                else (
                    *vitest_flags,
                    "--passWithNoTests",
                    *exclude_test_flags(
                        Path(path).relative_to(package).as_posix() for path in direct
                    ),
                )
            )
            checks.append(
                Check(
                    f"{kind}:{package}",
                    (
                        vitest,
                        *mode,
                        *flags,
                        *(Path(path).relative_to(package).as_posix() for path in values),
                    ),
                    directory,
                    tuple(values),
                )
            )
    deferred_related = [
        {"name": check.name, "scope": list(check.scope)}
        for check in checks
        if defer_related_vitest and check.name.startswith("vitest-related:")
    ]
    if defer_related_vitest:
        checks = [check for check in checks if not check.name.startswith("vitest-related:")]
    metadata = {
        "deferred_related_vitest": deferred_related,
        "deduplicated_vitest_files": deduplicated,
        "selected_pytest": list(selected),
        "omitted_pytest": list(omitted),
        "import_graph_errors": list(graph_errors),
        "test_file_cap": test_cap,
        "deleted_files": [path for path in changed if not (root / path).exists()],
        "unmapped_python_sources": [
            path for path in changed if path.endswith(".py") and module_name(path) is None
        ],
        "unmapped_frontend_sources": [
            path
            for path in changed
            if Path(path).suffix in SOURCE_SUFFIXES
            and not any(path in check.scope for check in checks)
        ],
        "unmapped_ci_inputs": [
            path
            for path in changed
            if (
                path.startswith(".github/workflows/")
                or (
                    path.startswith("scripts/ci/")
                    and Path(path).suffix not in {".py", *SOURCE_SUFFIXES}
                )
            )
            and path not in CI_INPUT_TESTS
        ],
    }
    return tuple(checks), metadata


def cpu_seconds() -> float:
    own = resource.getrusage(resource.RUSAGE_SELF)
    children = resource.getrusage(resource.RUSAGE_CHILDREN)
    return own.ru_utime + own.ru_stime + children.ru_utime + children.ru_stime


def process_family(pid: int) -> dict[int, tuple[int, float]]:
    """Read only Linux PID/start-time/CPU counters, never arguments or environment."""
    records = {}
    children: dict[int, list[int]] = defaultdict(list)
    ticks = os.sysconf("SC_CLK_TCK")
    for path in Path("/proc").iterdir():
        if not path.name.isdecimal():
            continue
        try:
            values = (path / "stat").read_text().rsplit(")", 1)[1].split()
            identity, parent = int(path.name), int(values[1])
            start = int(values[19])
            seconds = sum(int(values[index]) for index in (11, 12, 13, 14)) / ticks
        except (OSError, ValueError, IndexError):
            continue
        records[identity] = (start, seconds)
        children[parent].append(identity)
    family = {}
    pending = [pid]
    while pending:
        identity = pending.pop()
        if identity not in records or identity in family:
            continue
        family[identity] = records[identity]
        pending.extend(children[identity])
    return family


def signal_owned(owned: dict[int, int], signum: int) -> None:
    for identity, start in owned.items():
        try:
            current = Path(f"/proc/{identity}/stat").read_text().rsplit(")", 1)[1].split()
            if int(current[19]) == start and current[0] != "Z":
                os.kill(identity, signum)
        except (ProcessLookupError, PermissionError, FileNotFoundError, ValueError, IndexError):
            continue


def stop_process(process: subprocess.Popen[bytes], owned: dict[int, int]) -> None:
    # Capture descendants before stopping their parent. Some browser/server
    # fixtures create separate process groups; the parent's group alone misses them.
    owned.update({identity: record[0] for identity, record in process_family(process.pid).items()})
    # Pytest handles SIGINT by unwinding fixture finalizers, including owned DB
    # cleanup. Use that grace period before killing any surviving descendants.
    signal_owned(owned, signal.SIGINT)
    try:
        process.wait(timeout=3)
    except subprocess.TimeoutExpired:
        signal_owned(owned, signal.SIGTERM)
        try:
            process.wait(timeout=1)
        except subprocess.TimeoutExpired:
            signal_owned(owned, signal.SIGKILL)
            process.wait(timeout=1)
    finally:
        signal_owned(owned, signal.SIGKILL)


def pytest_summary(path: Path) -> dict[str, int]:
    """Read only execution counts; never retain test messages or captured output."""
    try:
        root = element_tree.parse(path).getroot()  # noqa: S314 - pytest's own disposable XML receipt
    except (OSError, element_tree.ParseError):
        raise FastCheckError("Pytest did not produce valid test evidence") from None
    cases = tuple(root.iter("testcase"))
    if root.tag not in {"testsuite", "testsuites"} or not cases:
        raise FastCheckError("Pytest did not produce valid test evidence")
    counts = dict.fromkeys(("passed", "skipped", "failed", "errors"), 0)
    for case in cases:
        if case.find("error") is not None:
            counts["errors"] += 1
        elif case.find("failure") is not None:
            counts["failed"] += 1
        elif case.find("skipped") is not None:
            counts["skipped"] += 1
        else:
            counts["passed"] += 1
    return counts


def vitest_summary(path: Path) -> tuple[dict[str, int], bool]:
    """Read only the installed JSON reporter's counts and success flag."""
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError):
        raise FastCheckError("Vitest did not produce valid test evidence") from None
    fields = {
        "passed": "numPassedTests",
        "skipped": "numPendingTests",
        "todo": "numTodoTests",
        "failed": "numFailedTests",
        "failed_suites": "numFailedTestSuites",
    }
    if not isinstance(document, dict):
        raise FastCheckError("Vitest did not produce valid test evidence")
    values = {key: document.get(field) for key, field in fields.items()}
    total = document.get("numTotalTests")
    success = document.get("success")
    if (
        any(type(value) is not int or value < 0 for value in (*values.values(), total))
        or type(success) is not bool
    ):
        raise FastCheckError("Vitest did not produce valid test evidence")
    counts = {key: int(document[field]) for key, field in fields.items()}
    if total != sum(counts[key] for key in ("passed", "skipped", "todo", "failed")):
        raise FastCheckError("Vitest did not produce valid test evidence")
    return counts, success


def run_vitest_check(check: Check, seconds: float, cpu_remaining: float) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="ac-fast-vitest-", dir="/tmp") as directory:
        report = Path(directory) / "results.json"
        separator = check.argv.index("--") if "--" in check.argv else len(check.argv)
        argv = (
            *check.argv[:separator],
            "--reporter=json",
            f"--outputFile={report}",
            *check.argv[separator:],
        )
        result = _run_check(replace(check, argv=argv), seconds, cpu_remaining)
        if result["status"] not in {"passed", "failed"}:
            return result
        try:
            counts, success = vitest_summary(report)
        except FastCheckError as error:
            result.update({"status": "failed", "reason": str(error)})
            return result
        result["vitest_summary"] = counts
        if not success or counts["failed"] or counts["failed_suites"]:
            result["status"] = "failed"
            document = json.loads(report.read_text(encoding="utf-8"))
            details = result.setdefault("diagnostics", [])
            suites = document.get("testResults", [])
            for suite in suites if isinstance(suites, list) else []:
                if not isinstance(suite, dict) or suite.get("status") != "failed":
                    continue
                name = suite.get("name")
                if isinstance(name, str) and (path := diagnostic_path(check, name)):
                    detail = f"{path}: Vitest suite failed"
                    if detail not in details and len(details) < 40:
                        details.append(detail)
            result["diagnostics_policy"] = (
                "First 40 recognized locations/codes; runtime payload suppressed"
            )
        elif result["status"] == "passed":
            if not any(counts.values()) and check.name.startswith("vitest:"):
                result.update({"status": "failed", "reason": "No selected Vitest tests collected"})
            elif not counts["passed"] or counts["skipped"] or counts["todo"]:
                result["status"] = "partial"
        return result


def run_check(check: Check, seconds: float, cpu_remaining: float) -> dict[str, Any]:
    if check.name.startswith(("vitest:", "vitest-related:")):
        return run_vitest_check(check, seconds, cpu_remaining)
    if check.name != "pytest":
        return _run_check(check, seconds, cpu_remaining)
    # Keep raw JUnit outside the source and remove it on every outcome. Only
    # sanitized counts enter the durable receipt. Insert before pytest's --.
    with tempfile.TemporaryDirectory(prefix="ac-fast-pytest-", dir="/tmp") as directory:
        report = Path(directory) / "results.xml"
        separator = check.argv.index("--") if "--" in check.argv else len(check.argv)
        argv = (*check.argv[:separator], f"--junitxml={report}", *check.argv[separator:])
        result = _run_check(replace(check, argv=argv), seconds, cpu_remaining)
        if result["status"] not in {"passed", "failed"}:
            return result
        try:
            counts = pytest_summary(report)
        except FastCheckError as error:
            result.update({"status": "failed", "reason": str(error)})
            return result
        result["pytest_summary"] = counts
        if counts["failed"] or counts["errors"]:
            result["status"] = "failed"
        elif result["status"] == "passed" and counts["skipped"]:
            result["status"] = "partial"
        return result


def diagnostic_path(check: Check, value: str) -> str | None:
    """Accept committed file identities, never arbitrary strings from tool output."""
    root = check.source_root or check.cwd
    path = Path(value)
    candidate = path if path.is_absolute() else check.cwd / path
    try:
        relative = candidate.resolve().relative_to(root.resolve()).as_posix()
    except (OSError, ValueError):
        return None
    if not re.fullmatch(r"[A-Za-z0-9_./@()\[\]-]+", relative) or not candidate.is_file():
        return None
    return relative


def failure_diagnostics(check: Check, output: str) -> list[str]:
    """Keep up to 40 locations/codes; suppress payloads, quotes and runtime output."""
    lines: list[str] = []
    current: str | None = None
    rule: str | None = None
    for raw in output.splitlines():
        line = re.sub(r"\x1b\[[0-9;]*m", "", raw).strip()
        detail: str | None = None
        if check.name == "mypy":
            match = re.fullmatch(r"(.+?):(\d+)(?::(\d+))?: error: .*\[([a-z-]+)\]", line)
            if match and (path := diagnostic_path(check, match[1])):
                detail = f"{path}:{match[2]}: mypy error [{match[4]}]"
        elif check.name.startswith("tsc:"):
            match = re.match(r"(.+?)\((\d+),(\d+)\): error (TS\d+):", line)
            if match and (path := diagnostic_path(check, match[1])):
                detail = f"{path}:{match[2]}:{match[3]}: TypeScript error {match[4]}"
        elif check.name.startswith("prettier:"):
            if line.startswith("[warn] ") and (path := diagnostic_path(check, line[7:])):
                detail = f"{path}: formatting differs"
        elif check.name == "ruff":
            code = re.match(r"([A-Z]+\d+)\b", line)
            if code:
                rule = code[1]
            match = re.match(r"(?:--> )?(.+?):(\d+):(\d+):?", line)
            if match and rule and (path := diagnostic_path(check, match[1])):
                detail = f"{path}:{match[2]}:{match[3]}: Ruff error {rule}"
                rule = None
        elif check.name.startswith(("eslint:", "eslint-shared:")):
            if path := diagnostic_path(check, line):
                current = path
            match = re.fullmatch(r"(\d+):(\d+)\s+(error|warning)\s+.*\s+([A-Za-z0-9_@/-]+)", line)
            if current and match:
                detail = f"{current}:{match[1]}:{match[2]}: ESLint {match[3]} {match[4]}"
        elif check.name == "pytest":
            match = re.match(r"(FAILED|ERROR) (.+?\.py)::(test_[A-Za-z0-9_]+)(?:\[|\s|$)", line)
            if match and (path := diagnostic_path(check, match[2])):
                detail = f"{path}::{match[3]}: {match[1].lower()}"
        if detail and detail not in lines:
            lines.append(detail)
            if len(lines) == 40:
                break
    return lines


def _run_check(check: Check, seconds: float, cpu_remaining: float) -> dict[str, Any]:
    environment = {
        **os.environ,
        "UV_OFFLINE": "1",
        "npm_config_offline": "true",
        "COREPACK_ENABLE_NETWORK": "0",
        "NEXT_TELEMETRY_DISABLED": "1",
        "CI": "1",
        "AC_ENVIRONMENT": "test",
        "AC_EXTERNAL_SIDE_EFFECTS_HOLD": "true",
        "AC_EMAIL_PROVIDER": "fake",
    }
    if check.source_root is not None:
        environment.update(
            {
                "PYTHONPATH": os.pathsep.join(
                    (str(check.source_root / "packages/python"), str(check.source_root))
                ),
                "PYTHONDONTWRITEBYTECODE": "1",
                "VIRTUAL_ENV": str(check.source_root / ".venv"),
                "NODE_PATH": str(check.source_root / "node_modules/.pnpm/node_modules"),
                "NODE_OPTIONS": "--require=" + str(check.source_root / ".ac-fast-node-source.cjs"),
                "XDG_CACHE_HOME": str(check.source_root / ".ac-fast-cache"),
            }
        )
    if check.name == "pytest" and not environment.get("AC_TEST_DATABASE_URL"):
        return {
            "name": check.name,
            "status": "unavailable",
            "reason": "Lane test database URL is required",
        }
    # Each command runs through the installed shared slot. The outer caller
    # may already hold it; ac-heavy recognizes its live ancestor and nests safely.
    guard = shutil.which("ac-heavy")
    if guard is None:
        return {
            "name": check.name,
            "status": "unavailable",
            "reason": "The shared heavy slot is required",
        }
    command = [guard, *check.argv]
    started, cpu_start = time.monotonic(), cpu_seconds()

    def limit_cpu() -> None:
        limit = max(1, math.ceil(cpu_remaining))
        inherited = resource.getrlimit(resource.RLIMIT_CPU)[1]
        hard = limit + 1 if inherited == resource.RLIM_INFINITY else min(limit + 1, inherited)
        resource.setrlimit(resource.RLIMIT_CPU, (min(limit, hard), hard))

    process = subprocess.Popen(  # noqa: S603 - selected local tool argument arrays, no shell
        command,
        cwd=check.cwd,
        env=environment,
        start_new_session=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        preexec_fn=limit_cpu,
    )
    captured = bytearray()

    def drain_output() -> None:
        assert process.stdout is not None
        while chunk := process.stdout.read(8192):
            # Drain beyond the bound so verbose failures cannot block the child.
            captured.extend(chunk[: max(0, 262144 - len(captured))])

    reader = threading.Thread(target=drain_output, daemon=True)
    reader.start()
    owned: dict[int, int] = {}
    while True:
        family = process_family(process.pid)
        owned.update({identity: record[0] for identity, record in family.items()})
        used = cpu_seconds() - cpu_start + sum(record[1] for record in family.values())
        remaining = seconds - (time.monotonic() - started)
        if remaining <= 0 or used >= cpu_remaining:
            stop_process(process, owned)
            returncode = 124
            status = "timed_out" if remaining <= 0 else "budget_exhausted"
            break
        try:
            returncode = process.wait(timeout=min(0.5, remaining))
            status = "passed" if returncode == 0 else "failed"
            break
        except subprocess.TimeoutExpired:
            continue
    # A successful tool can still leave a server or browser descendant behind.
    # Reclaim observed children on every exit, with the same PID/start-time guard.
    signal_owned(owned, signal.SIGKILL)
    reader.join(timeout=2)
    result: dict[str, Any] = {
        "name": check.name,
        "status": status,
        "returncode": returncode,
        "wall_seconds": round(time.monotonic() - started, 3),
        "cpu_seconds": round(cpu_seconds() - cpu_start, 3),
        "scope": list(check.scope),
    }
    if status != "passed":
        result["diagnostics"] = failure_diagnostics(
            check, captured.decode("utf-8", errors="replace")
        )
        result["diagnostics_policy"] = (
            "First 40 recognized locations/codes; runtime payload suppressed"
        )
    return result


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--commit", default="HEAD", help="Local commit to check (default: HEAD)")
    parser.add_argument("--base", default="origin/main")
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--test-file-cap", type=int, default=12)
    parser.add_argument("--wall-seconds", type=float, default=300)
    parser.add_argument("--cpu-seconds", type=float, default=180)
    parser.add_argument(
        "--defer-related-vitest",
        action="store_true",
        help="Run direct frontend tests; explicitly defer related tests to required CI (partial)",
    )
    parser.add_argument("--plan", action="store_true")
    args = parser.parse_args(argv)
    root = args.root.resolve()
    args.receipt = args.receipt.resolve()
    if args.receipt.is_relative_to(root):
        print("ac-ci/fast unavailable | receipt must stay outside the checkout")
        return 2
    started, cpu_start = time.monotonic(), cpu_seconds()
    receipt: dict[str, Any] = {
        "schema": SCHEMA,
        "started_at": datetime.now(UTC).isoformat(),
        "runner_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "snapshot_runner_sha256": hashlib.sha256(Path(SNAPSHOT.__file__).read_bytes()).hexdigest(),
        "checks": [],
    }
    try:
        if not all(
            math.isfinite(value) and value > 0 for value in (args.wall_seconds, args.cpu_seconds)
        ):
            raise FastCheckError("Wall and CPU budgets must be positive")
        commit = commit_sha(root, args.commit)
        receipt["commit"] = commit
        base = git(root, "merge-base", commit_sha(root, args.base), commit).strip()
        changed = changed_files(root, base, commit)
        receipt.update(
            {"base": base, "changed_files": list(changed), "source_mode": "committed-snapshot"}
        )
        with SNAPSHOT.committed_snapshot(root, commit) as snapshot:
            receipt["source_sha256"] = snapshot.sha256
            # Include the removed source of a rename, even when Git presents it
            # as a single renamed destination in the ordinary check plan.
            native_changed = git(
                root, "diff", "--name-only", "--no-renames", "-z", base, commit, "--"
            ).split("\0")
            receipt["native_inputs_changed"] = list(
                native_inputs_changed(snapshot.root, tuple(path for path in native_changed if path))
            )
            if args.defer_related_vitest:
                checks, metadata = plan(
                    snapshot.root, changed, args.test_file_cap, defer_related_vitest=True
                )
            else:
                checks, metadata = plan(snapshot.root, changed, args.test_file_cap)
            checks = tuple(replace(check, source_root=snapshot.root) for check in checks)
            metadata["omitted_generated_frontend_types"] = [
                check.cwd.relative_to(snapshot.root).as_posix()
                for check in checks
                if check.name.startswith("tsc:")
                and (check.cwd / "next-env.d.ts").is_file()
                and ".next/" in (check.cwd / "next-env.d.ts").read_text()
            ]
            receipt.update(metadata)
            receipt["planned_checks"] = [
                {
                    "name": check.name,
                    "argv": list(check.argv),
                    "cwd": str(check.cwd),
                    "scope": list(check.scope),
                }
                for check in checks
            ]
            for check in checks:
                if args.plan:
                    receipt["checks"].append(
                        {"name": check.name, "status": "planned", "scope": list(check.scope)}
                    )
                    continue
                wall_remaining = args.wall_seconds - (time.monotonic() - started)
                cpu_remaining = args.cpu_seconds - (cpu_seconds() - cpu_start)
                if min(wall_remaining, cpu_remaining) <= 0:
                    receipt["checks"].append({"name": check.name, "status": "budget_exhausted"})
                    continue
                receipt["checks"].append(run_check(check, wall_remaining, cpu_remaining))
            statuses = {result["status"] for result in receipt["checks"]}
            if (
                not snapshot.unchanged()
                or hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
                != receipt["runner_sha256"]
                or hashlib.sha256(Path(SNAPSHOT.__file__).read_bytes()).hexdigest()
                != receipt["snapshot_runner_sha256"]
            ):
                raise FastCheckError(
                    "Exported source or runner changed during the checks; the receipt is unusable"
                )
            if statuses - {"passed", "planned", "partial"}:
                receipt["status"] = "failed"
            elif (
                "partial" in statuses
                or metadata["omitted_pytest"]
                or metadata["import_graph_errors"]
                or metadata["deleted_files"]
                or metadata["unmapped_python_sources"]
                or metadata["unmapped_frontend_sources"]
                or metadata["unmapped_ci_inputs"]
                or metadata["omitted_generated_frontend_types"]
                or metadata.get("deferred_related_vitest")
            ):
                receipt["status"] = "partial"
            else:
                receipt["status"] = "planned" if args.plan else "passed"
    except (FastCheckError, SNAPSHOT.SnapshotError) as error:
        receipt.update({"status": "unavailable", "reason": str(error)})
    except (OSError, subprocess.SubprocessError) as error:
        receipt.update(
            {"status": "failed", "reason": f"Local check could not run ({type(error).__name__})"}
        )
    receipt.update(
        {
            "wall_seconds": round(time.monotonic() - started, 3),
            "cpu_seconds": round(cpu_seconds() - cpu_start, 3),
            "finished_at": datetime.now(UTC).isoformat(),
        }
    )
    args.receipt.parent.mkdir(parents=True, exist_ok=True)
    args.receipt.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        f"ac-ci/fast {receipt['status']} | {len(receipt.get('changed_files', []))} changed files | "
        f"{receipt['wall_seconds']:.1f}s wall / {receipt['cpu_seconds']:.1f}s process CPU"
    )
    if receipt.get("native_inputs_changed"):
        print("needs Root prepare-native before staging")
    if receipt.get("reason"):
        print(f"  reason: {receipt['reason']}")
    for result in receipt["checks"]:
        print(f"  {result['status']:16} {result['name']}")
    skipped = sum(
        result.get("pytest_summary", {}).get("skipped", 0) for result in receipt["checks"]
    )
    if skipped:
        print(f"  coverage: {skipped} selected pytest cases skipped")
    vitest_counts = [
        result["vitest_summary"] for result in receipt["checks"] if "vitest_summary" in result
    ]
    pending = sum(counts["skipped"] + counts["todo"] for counts in vitest_counts)
    if pending:
        print(f"  coverage: {pending} selected Vitest cases skipped or todo")
    empty = sum(not any(counts.values()) for counts in vitest_counts)
    if empty:
        print(f"  coverage: {empty} Vitest checks collected no tests")
    if receipt.get("omitted_pytest"):
        print(
            f"  cap: {len(receipt['omitted_pytest'])} related files deferred to required GitHub CI"
        )
    if receipt.get("deferred_related_vitest"):
        print(
            f"  coverage: {len(receipt['deferred_related_vitest'])} related Vitest checks "
            "explicitly deferred to required GitHub CI"
        )
    if receipt.get("unmapped_ci_inputs"):
        print(
            f"  coverage: {len(receipt['unmapped_ci_inputs'])} CI inputs "
            "deferred to required GitHub CI"
        )
    print(f"  receipt: {args.receipt}")
    return 0 if receipt["status"] in {"passed", "planned", "partial"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
