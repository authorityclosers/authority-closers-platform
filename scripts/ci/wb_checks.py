#!/usr/bin/env python3
"""Workbench checks on GitHub-hosted runners (owner, 20 Oct 2026: tests run on GitHub, not on ac; full run < 5 min).

`wb-ci` on ac pushes a request commit to `refs/heads/wb-ci/<slot>`. The commit carries `.wb-ci/request.json`:

    {"schema": "wb-ci/2", "source_sha": "<workbench commit>", "full": false,
     "checks": [] | ["web", "py", "visual"], "changed_files": ["apps/...", ...], "routes": [], "py_tests": [],
     "py_shards": 16, "requested_by": "..."}

Full runs every job. Otherwise only the families the changed paths touch run (explicit `checks` force families), and
lint, tsc, vitest and ruff are scoped to the changed files. Python tests always run every shard when Python changed
(or the given `py_tests` only).

Subcommands (from the repository root on the runner):
  plan                 job switches and matrices to $GITHUB_OUTPUT
  web --task T         T = lint (prettier + eslint + ruff + mypy), tsc, vitest
  py-needs --shard I   does shard I need the codec/browser prerequisites? (true/false to $GITHUB_OUTPUT)
  summary              table of every job's result plus artifact links in the run summary
Every check's outcome goes to the step summary; a command exits 1 when any of its checks failed. No secrets are read.
"""
from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

REQUEST = Path(".wb-ci/request.json")
DURATIONS = Path("scripts/ci/wb-python-durations.json")
WEB_EXT = (".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs")
FORMAT_EXT = WEB_EXT + (".css", ".json", ".md", ".yml", ".yaml")
# Changes here re-run everything: the CI itself, lockfiles and toolchain configuration.
EVERYTHING = re.compile(r"^(\.github/workflows/workbench-checks\.yml|scripts/ci/(wb[-_]|python_test_shard|ci_prerequisites"
                        r"|python-test-exclusions)|package\.json|pnpm-lock\.yaml|pnpm-workspace\.yaml|pyproject\.toml"
                        r"|uv\.lock|tsconfig[^/]*\.json)")
WEB = re.compile(r"^(apps/|packages/typescript/)")
VISUAL = re.compile(r"^(apps/sales-xray-web/|packages/typescript/(ui|sales-xray-review-ui)/)")
PY = re.compile(r"^(packages/python/|tests/|alembic|migrations/|infra/local/postgres/|scripts/[^/]+\.py$)")
# Test files whose source mentions these may need ffmpeg, Playwright Chromium or the native build. A miss is not silent:
# python_test_shard.py fails a shard (exit 3) when a required runtime is skipped.
NEEDS_PREREQ = re.compile(r"playwright|chromium|ffmpeg|ffprobe|audioatlas|build_native|_native_executable|codec",
                          re.IGNORECASE)


def request() -> dict:
    data = json.loads(REQUEST.read_text()) if REQUEST.exists() else {}
    data.setdefault("full", data.get("changed_files") is None)
    data.setdefault("checks", [])
    data.setdefault("changed_files", None)
    data.setdefault("routes", [])
    data.setdefault("py_tests", [])
    data.setdefault("py_shards", 16)
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
        print(f"::group::{name}: {shlex.join(argv)[:300]}", flush=True)
        started = time.monotonic()
        code = subprocess.run(argv, cwd=cwd).returncode
        elapsed = time.monotonic() - started
        print("::endgroup::", flush=True)
        if code:
            print(f"::error title={name}::{name} failed (exit {code})")
        self.rows.append((name, "pass" if code == 0 else "FAIL", elapsed, shlex.join(argv)[:110]))

    def skip(self, name: str, why: str) -> None:
        self.rows.append((name, "skip", 0.0, why))

    def finish(self) -> int:
        lines = [f"### {self.title}", "", "| check | result | seconds | command |", "|---|---|---|---|"]
        lines += [f"| {n} | {r} | {s:.0f} | `{c}` |" for n, r, s, c in self.rows]
        summary("\n".join(lines))
        return 1 if any(r == "FAIL" for _, r, _, _ in self.rows) else 0


def existing(paths: list[str]) -> list[str]:
    return [p for p in paths if Path(p).is_file()]


def package_of(path: str) -> str | None:
    parts = path.split("/")
    if len(parts) > 2 and parts[0] == "apps":
        return "/".join(parts[:2])
    if len(parts) > 3 and parts[:2] == ["packages", "typescript"]:
        return "/".join(parts[:3])
    return None


def changed_packages(files: list[str]) -> dict[str, list[str]]:
    packages: dict[str, list[str]] = {}
    for path in files:
        pkg = package_of(path)
        if pkg and Path(pkg, "package.json").exists():
            packages.setdefault(pkg, []).append(path)
    return packages


def families(req: dict) -> tuple[set[str], bool]:
    """(families to run, full scope)."""
    if req["full"]:
        return set(req["checks"] or ["web", "py", "visual"]), True
    files = req["changed_files"] or []
    if any(EVERYTHING.match(p) for p in files):
        return set(req["checks"] or ["web", "py", "visual"]), True
    found = set()
    if any(WEB.match(p) for p in files):
        found.add("web")
    if any(VISUAL.match(p) and not re.search(r"\.(test|spec)\.[cm]?[jt]sx?$", p) for p in files):
        found.add("visual")
    if any(PY.match(p) for p in files) or req["py_tests"]:
        found.add("py")
    if req["checks"]:
        found = set(req["checks"])
    return found, False


def cmd_plan() -> int:
    req = request()
    fams, full = families(req)
    shards = int(req["py_shards"])
    py_matrix = ["targeted"] if req["py_tests"] else list(range(shards))
    out(web=str("web" in fams).lower(), py=str("py" in fams).lower(), visual=str("visual" in fams).lower(),
        lint=str(bool(fams & {"web", "py"})).lower(),
        py_matrix=json.dumps(py_matrix if "py" in fams else []), py_shards=str(shards),
        scope="full" if full else "changed")
    n = len(req["changed_files"] or [])
    summary(f"### Workbench request\n\n- source `{req.get('source_sha', '?')}` by {req.get('requested_by', '?')}\n"
            f"- scope: {'full' if full else f'changed files ({n})'}; jobs: {', '.join(sorted(fams)) or 'none needed'}"
            + (f"\n- routes: {', '.join(req['routes'])}" if req["routes"] else "")
            + (f"\n- python tests: {', '.join(req['py_tests'])}" if req["py_tests"] else ""))
    return 0


def cmd_web(task: str) -> int:
    req = request()
    fams, full = families(req)
    files = existing(req["changed_files"] or [])
    web_files = [p for p in files if WEB.match(p)]
    packages = changed_packages(web_files)
    checks = Checks(f"{task} checks ({'full' if full else 'changed files'})")
    if task == "lint":
        if "web" in fams:
            fmt = ["apps", "packages/typescript", "package.json", "pnpm-workspace.yaml"] if full else \
                [p for p in web_files if p.endswith(FORMAT_EXT)]
            if fmt:
                checks.run("prettier", ["pnpm", "exec", "prettier", "--check", *fmt])
            if full:
                checks.run("eslint", ["pnpm", "-r", "--if-present", "lint"])
            for pkg, paths in sorted(packages.items()) if not full else []:
                code = [str(Path(p).relative_to(pkg)) for p in paths if p.endswith(WEB_EXT)]
                if code and "lint" in json.loads(Path(pkg, "package.json").read_text()).get("scripts", {}):
                    checks.run(f"eslint {pkg}", ["pnpm", "exec", "eslint", "--max-warnings", "0", "--cache",
                                                 "--cache-location", "node_modules/.cache/eslint/", *code], cwd=pkg)
        if "py" in fams:
            targets = ["packages/python", "tests"] if full else \
                [p for p in files if p.endswith(".py") and p.startswith(("packages/python/", "tests/"))]
            if targets:
                checks.run("ruff format", ["uv", "run", "ruff", "format", "--check", *targets])
                checks.run("ruff check", ["uv", "run", "ruff", "check", *targets])
            checks.run("mypy", ["uv", "run", "mypy", "packages/python"])
    elif task == "tsc":
        if full:
            checks.run("tsc", ["pnpm", "-r", "--if-present", "typecheck"])
        for pkg in sorted(packages) if not full else []:
            if "typecheck" in json.loads(Path(pkg, "package.json").read_text()).get("scripts", {}):
                checks.run(f"tsc {pkg}", ["pnpm", "run", "typecheck"], cwd=pkg)
    elif task == "vitest":
        if full:
            checks.run("vitest", ["pnpm", "-r", "--if-present", "test"])
        for pkg, paths in sorted(packages.items()) if not full else []:
            code = [str(Path(p).relative_to(pkg)) for p in paths if p.endswith(WEB_EXT)]
            manifest = json.loads(Path(pkg, "package.json").read_text())
            if code and "vitest" in json.dumps(manifest.get("scripts", {})):
                checks.run(f"vitest {pkg}", ["pnpm", "exec", "vitest", "related", "--run", "--passWithNoTests", *code],
                           cwd=pkg)
    else:
        sys.exit(f"unknown web task {task}")
    if not checks.rows:
        checks.skip(task, "nothing changed for this check")
    return checks.finish()


def cmd_py_needs(shard: str) -> int:
    if shard == "targeted":
        files = request()["py_tests"]
    else:
        sys.path.insert(0, "scripts/ci")
        import python_test_shard as pts  # noqa: PLC0415 - the repository's own shard logic

        root = Path.cwd()
        discovered = pts.discover_test_files(root)
        exclusions = pts.read_exclusions(Path("scripts/ci/python-test-exclusions.txt"), discovered)
        included = tuple(p for p in discovered if p not in set(exclusions))
        measured, _ = pts.duration_evidence(DURATIONS)
        files = pts.assign_shards(included, int(request()["py_shards"]), measured)[int(shard)]
    hits = [p for p in files if Path(p).is_file() and NEEDS_PREREQ.search(Path(p).read_text(errors="ignore"))]
    out(needed=str(bool(hits)).lower())
    print(f"shard {shard}: {len(files)} files; codec/browser prerequisites {'needed by ' + ', '.join(hits[:5]) if hits else 'not needed'}")
    return 0


def cmd_summary() -> int:
    needs = json.loads(os.environ.get("NEEDS_JSON", "{}"))
    repo, run_id = os.environ["GITHUB_REPOSITORY"], os.environ["GITHUB_RUN_ID"]
    run_url = f"{os.environ.get('GITHUB_SERVER_URL', 'https://github.com')}/{repo}/actions/runs/{run_id}"
    verify = os.environ.get("VERIFY_OUTCOME", "skipped")
    lines = ["## Workbench checks", "", "| job | result |", "|---|---|"]
    lines += [f"| {job} | {data.get('result', '?')} |" for job, data in needs.items() if job != "plan"]
    lines.append(f"| python shard coverage | {verify} |")
    artifacts = []
    try:
        req = urllib.request.Request(f"https://api.github.com/repos/{repo}/actions/runs/{run_id}/artifacts?per_page=100",
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
    return 1 if bad or verify == "failure" else 0


if __name__ == "__main__":
    args = sys.argv[1:]
    if args[:1] == ["plan"]:
        sys.exit(cmd_plan())
    if args[:2] == ["web", "--task"] and len(args) == 3:
        sys.exit(cmd_web(args[2]))
    if args[:2] == ["py-needs", "--shard"] and len(args) == 3:
        sys.exit(cmd_py_needs(args[2]))
    if args[:1] == ["summary"]:
        sys.exit(cmd_summary())
    sys.exit(f"usage: {sys.argv[0]} plan | web --task lint|tsc|vitest | py-needs --shard I | summary")
