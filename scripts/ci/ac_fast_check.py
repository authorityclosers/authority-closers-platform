#!/usr/bin/env python3
"""Run bounded checks for a clean, locally available PR commit, without installs."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import math
import os
import resource
import shutil
import signal
import subprocess
import time
from collections import defaultdict, deque
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SCHEMA = "ac.ci.fast-check/1"
PYTHON_ROOTS = ("packages/python", "tests", "scripts")
SOURCE_SUFFIXES = {".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs"}
FORMAT_SUFFIXES = SOURCE_SUFFIXES | {".css", ".json", ".md", ".mdx", ".yaml", ".yml"}


class FastCheckError(RuntimeError):
    """A bounded diagnostic that does not contain command output or credentials."""


@dataclass(frozen=True)
class Check:
    name: str
    argv: tuple[str, ...]
    cwd: Path
    scope: tuple[str, ...]


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
        safe_path(root, path)
    return paths


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


def plan(
    root: Path, changed: tuple[str, ...], test_cap: int
) -> tuple[tuple[Check, ...], dict[str, Any]]:
    checks = []
    python = root / ".venv/bin/python"
    pyfiles = tuple(path for path in changed if path.endswith(".py") and (root / path).is_file())
    if pyfiles:
        if not python.is_file():
            raise FastCheckError(
                "The locked Python environment is unavailable; installs are forbidden"
            )
        checks.append(
            Check("ruff", (str(python), "-m", "ruff", "check", "--", *pyfiles), root, pyfiles)
        )
        modules = tuple(path for path in pyfiles if not path.startswith("tests/"))
        if modules:
            checks.append(
                Check(
                    "mypy",
                    (
                        str(python),
                        "-m",
                        "mypy",
                        "--incremental",
                        "--follow-imports=silent",
                        *modules,
                    ),
                    root,
                    modules,
                )
            )
    tests, graph_errors = affected_tests(root, changed)
    selected, omitted = capped_tests(tests, changed, test_cap)
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
                checks.append(
                    Check(
                        f"vitest-related:{app}",
                        (
                            node_tool(root, directory, "vitest"),
                            "related",
                            "--run",
                            *vitest_flags,
                            "--passWithNoTests",
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
                    "--tsBuildInfoFile",
                    str(cache / "tsconfig.tsbuildinfo"),
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
        for values, kind in ((direct, "vitest"), (related, "vitest-related")):
            if not values:
                continue
            mode = ("run",) if kind == "vitest" else ("related", "--run")
            flags = vitest_flags if kind == "vitest" else (*vitest_flags, "--passWithNoTests")
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
    metadata = {
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


def run_check(check: Check, seconds: float, cpu_remaining: float) -> dict[str, Any]:
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
        resource.setrlimit(resource.RLIMIT_CPU, (limit, limit + 1))

    process = subprocess.Popen(  # noqa: S603 - selected local tool argument arrays, no shell
        command,
        cwd=check.cwd,
        env=environment,
        start_new_session=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        preexec_fn=limit_cpu,
    )
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
    return {
        "name": check.name,
        "status": status,
        "returncode": returncode,
        "wall_seconds": round(time.monotonic() - started, 3),
        "cpu_seconds": round(cpu_seconds() - cpu_start, 3),
        "scope": list(check.scope),
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--commit", required=True)
    parser.add_argument("--base", default="origin/main")
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--test-file-cap", type=int, default=12)
    parser.add_argument("--wall-seconds", type=float, default=300)
    parser.add_argument("--cpu-seconds", type=float, default=180)
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
        "checks": [],
    }
    try:
        if not all(
            math.isfinite(value) and value > 0 for value in (args.wall_seconds, args.cpu_seconds)
        ):
            raise FastCheckError("Wall and CPU budgets must be positive")
        commit = commit_sha(root, args.commit)
        receipt["commit"] = commit
        if commit_sha(root, "HEAD") != commit:
            raise FastCheckError("Check out the requested commit before running the fast check")
        if git(root, "status", "--porcelain", "--untracked-files=normal").strip():
            raise FastCheckError("The requested commit needs a clean checkout")
        base = git(root, "merge-base", commit_sha(root, args.base), commit).strip()
        changed = changed_files(root, base, commit)
        receipt.update({"base": base, "changed_files": list(changed)})
        checks, metadata = plan(root, changed, args.test_file_cap)
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
            commit_sha(root, "HEAD") != commit
            or git(root, "status", "--porcelain", "--untracked-files=normal").strip()
            or hashlib.sha256(Path(__file__).read_bytes()).hexdigest() != receipt["runner_sha256"]
        ):
            raise FastCheckError("Source changed during the checks; the receipt is unusable")
        if statuses - {"passed", "planned"}:
            receipt["status"] = "failed"
        elif (
            metadata["omitted_pytest"]
            or metadata["import_graph_errors"]
            or metadata["deleted_files"]
            or metadata["unmapped_python_sources"]
            or metadata["unmapped_frontend_sources"]
        ):
            receipt["status"] = "partial"
        else:
            receipt["status"] = "planned" if args.plan else "passed"
    except FastCheckError as error:
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
    for result in receipt["checks"]:
        print(f"  {result['status']:16} {result['name']}")
    if receipt.get("omitted_pytest"):
        print(
            f"  cap: {len(receipt['omitted_pytest'])} related files deferred to required GitHub CI"
        )
    print(f"  receipt: {args.receipt}")
    return 0 if receipt["status"] in {"passed", "planned", "partial"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
