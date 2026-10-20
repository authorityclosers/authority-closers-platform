#!/usr/bin/env python3
"""Workbench checks on GitHub-hosted runners (owner, 20 Oct 2026: tests and emulations run on GitHub, not on ac).

`wb-ci` on ac pushes a request commit to `refs/heads/wb-ci/<sha>-<rand>`. The commit carries `.wb-ci/request.json`:

    {"schema": "wb-ci/1", "source_sha": "<workbench commit>", "checks": ["web", "py", "visual"],
     "changed_files": null | ["apps/...", ...], "routes": [], "py_tests": [], "requested_by": "..."}

`changed_files: null` means the full checks; a list scopes format, lint and tests to those files.

Subcommands (run from the repository root on the runner):
  plan       write job switches to $GITHUB_OUTPUT
  web        prettier, eslint, tsc and vitest; full or scoped to the changed files
  py-static  ruff format, ruff check (scoped when asked) and mypy
  summary    one table of every job's result plus artifact links in the run summary
Each check's outcome goes to the step summary; the command exits 1 when any check failed. No secrets are read.
"""
from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

REQUEST = Path(".wb-ci/request.json")
WEB_EXT = (".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs")
FORMAT_EXT = WEB_EXT + (".css", ".json", ".md", ".yml", ".yaml")


def request() -> dict:
    data = json.loads(REQUEST.read_text()) if REQUEST.exists() else {}
    data.setdefault("checks", ["web", "py", "visual"])
    data.setdefault("changed_files", None)
    data.setdefault("routes", [])
    data.setdefault("py_tests", [])
    return data


def out(**values: str) -> None:
    with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as handle:
        for key, value in values.items():
            handle.write(f"{key}={value}\n")


def summary(text: str) -> None:
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if path:
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(text + "\n")
    print(text)


class Checks:
    """Run named commands, keep going after a failure, report a table at the end."""

    def __init__(self, title: str) -> None:
        self.title = title
        self.rows: list[tuple[str, str, float, str]] = []

    def run(self, name: str, argv: list[str], cwd: str | None = None) -> None:
        print(f"::group::{name}: {shlex.join(argv)}", flush=True)
        started = time.monotonic()
        code = subprocess.run(argv, cwd=cwd).returncode
        elapsed = time.monotonic() - started
        print("::endgroup::", flush=True)
        if code:
            print(f"::error title={name}::{name} failed (exit {code})")
        self.rows.append((name, "pass" if code == 0 else "FAIL", elapsed, shlex.join(argv)[:120]))

    def skip(self, name: str, why: str) -> None:
        self.rows.append((name, "skip", 0.0, why))

    def finish(self) -> int:
        lines = [f"### {self.title}", "", "| check | result | seconds | command |", "|---|---|---|---|"]
        lines += [f"| {n} | {r} | {s:.0f} | `{c}` |" for n, r, s, c in self.rows]
        summary("\n".join(lines))
        failed = [n for n, r, _, _ in self.rows if r == "FAIL"]
        Path(os.environ.get("RUNNER_TEMP", "/tmp"), f"wb-{self.title.split()[0].lower()}.json").write_text(
            json.dumps([{"check": n, "result": r, "seconds": round(s)} for n, r, s, _ in self.rows]))
        return 1 if failed else 0


def existing(paths: list[str]) -> list[str]:
    return [p for p in paths if Path(p).is_file()]


def package_of(path: str) -> str | None:
    parts = path.split("/")
    if len(parts) > 2 and parts[0] == "apps":
        return "/".join(parts[:2])
    if len(parts) > 3 and parts[:2] == ["packages", "typescript"]:
        return "/".join(parts[:3])
    return None


def cmd_plan() -> int:
    req = request()
    checks = set(req["checks"])
    py_tests = [p for p in req["py_tests"] if p]
    out(web=str("web" in checks).lower(), py=str("py" in checks).lower(), visual=str("visual" in checks).lower(),
        shards=json.dumps(["targeted"] if py_tests else [0, 1, 2, 3]),
        scope="changed" if req["changed_files"] is not None else "full",
        source_sha=str(req.get("source_sha") or os.environ.get("GITHUB_SHA", "")))
    summary(f"### Workbench request\n\n- source `{req.get('source_sha', '?')}` by {req.get('requested_by', '?')}\n"
            f"- checks: {', '.join(sorted(checks))}; scope: "
            f"{'changed files (' + str(len(req['changed_files'])) + ')' if req['changed_files'] is not None else 'full'}"
            + (f"\n- routes: {', '.join(req['routes'])}" if req["routes"] else "")
            + (f"\n- python tests: {', '.join(py_tests)}" if py_tests else ""))
    return 0


def cmd_web() -> int:
    req = request()
    checks = Checks("Web checks")
    changed = req["changed_files"]
    if changed is None:
        checks.run("prettier", ["pnpm", "exec", "prettier", "--check", "apps", "packages/typescript", "package.json",
                                "pnpm-workspace.yaml"])
        checks.run("eslint", ["pnpm", "-r", "--if-present", "lint"])
        checks.run("tsc", ["pnpm", "-r", "--if-present", "typecheck"])
        checks.run("vitest", ["pnpm", "-r", "--if-present", "test"])
        return checks.finish()
    files = [p for p in existing(changed) if p.startswith(("apps/", "packages/typescript/"))]
    fmt = [p for p in files if p.endswith(FORMAT_EXT)]
    if fmt:
        checks.run("prettier", ["pnpm", "exec", "prettier", "--check", *fmt])
    else:
        checks.skip("prettier", "no changed web files")
    packages: dict[str, list[str]] = {}
    for path in files:
        pkg = package_of(path)
        if pkg and Path(pkg, "package.json").exists():
            packages.setdefault(pkg, []).append(path)
    if not packages:
        for name in ("eslint", "tsc", "vitest"):
            checks.skip(name, "no changed web package")
        return checks.finish()
    for pkg, paths in sorted(packages.items()):
        rel = [str(Path(p).relative_to(pkg)) for p in paths]
        manifest = json.loads(Path(pkg, "package.json").read_text())
        scripts, deps = manifest.get("scripts", {}), {**manifest.get("devDependencies", {}), **manifest.get("dependencies", {})}
        code = [r for r in rel if r.endswith(WEB_EXT)]
        if "lint" in scripts and code:
            checks.run(f"eslint {pkg}", ["pnpm", "exec", "eslint", "--max-warnings", "0", *code], cwd=pkg)
        if "typecheck" in scripts:
            checks.run(f"tsc {pkg}", ["pnpm", "run", "typecheck"], cwd=pkg)
        if "vitest" in deps and code:
            checks.run(f"vitest {pkg}", ["pnpm", "exec", "vitest", "related", "--run", "--passWithNoTests", *code], cwd=pkg)
        elif "test" in scripts:
            checks.run(f"test {pkg}", ["pnpm", "run", "test"], cwd=pkg)
    return checks.finish()


def cmd_py_static() -> int:
    req = request()
    checks = Checks("Python static checks")
    changed = req["changed_files"]
    if changed is None:
        targets = ["packages/python", "tests"]
    else:
        targets = [p for p in existing(changed) if p.endswith(".py") and p.startswith(("packages/python/", "tests/"))]
    if targets:
        checks.run("ruff format", ["uv", "run", "ruff", "format", "--check", *targets])
        checks.run("ruff check", ["uv", "run", "ruff", "check", *targets])
    else:
        checks.skip("ruff", "no changed Python files")
    checks.run("mypy", ["uv", "run", "mypy", "packages/python"])
    return checks.finish()


def cmd_summary() -> int:
    needs = json.loads(os.environ.get("NEEDS_JSON", "{}"))
    repo, run_id = os.environ["GITHUB_REPOSITORY"], os.environ["GITHUB_RUN_ID"]
    run_url = f"{os.environ.get('GITHUB_SERVER_URL', 'https://github.com')}/{repo}/actions/runs/{run_id}"
    lines = ["## Workbench checks", "", "| job | result |", "|---|---|"]
    for job, data in needs.items():
        if job != "plan":
            lines.append(f"| {job} | {data.get('result', '?')} |")
    artifacts = []
    try:
        req = urllib.request.Request(f"https://api.github.com/repos/{repo}/actions/runs/{run_id}/artifacts",
                                     headers={"Authorization": f"Bearer {os.environ['GH_TOKEN']}",
                                              "Accept": "application/vnd.github+json"})
        with urllib.request.urlopen(req, timeout=30) as response:
            artifacts = json.loads(response.read()).get("artifacts", [])
    except Exception as error:  # an unreadable list never fails the summary
        lines.append(f"\n(artifact list unavailable: {type(error).__name__})")
    if artifacts:
        lines += ["", "Artifacts:"] + [f"- [{a['name']}]({run_url}/artifacts/{a['id']})" for a in artifacts]
    summary("\n".join(lines))
    bad = [job for job, data in needs.items() if data.get("result") in ("failure", "cancelled")]
    return 1 if bad else 0


if __name__ == "__main__":
    commands = {"plan": cmd_plan, "web": cmd_web, "py-static": cmd_py_static, "summary": cmd_summary}
    if len(sys.argv) != 2 or sys.argv[1] not in commands:
        sys.exit(f"usage: {sys.argv[0]} {{{'|'.join(commands)}}}")
    sys.exit(commands[sys.argv[1]]())
