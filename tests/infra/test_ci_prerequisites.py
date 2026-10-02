"""Bounded CI prerequisite helper: fake apt/Playwright runners plus workflow guards."""

from __future__ import annotations

import importlib.util
import shlex
import sys
import time
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "ci_prerequisites", ROOT / "scripts/ci/ci_prerequisites.py"
)
assert SPEC and SPEC.loader
prereq = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = prereq
SPEC.loader.exec_module(prereq)

BROWSER_LIBS = ["libnss3", "libgbm1", "fonts-liberation"]
DRY_RUN = (
    'sudo -- sh -c "apt-get update&& apt-get install -y --no-install-recommends '
    + " ".join(BROWSER_LIBS)
    + '"\n'
)


class FakeHost:
    """Answers each command from a table; records argv, limits and env."""

    def __init__(self, installed=(), failures=None, dry_run=DRY_RUN, probe_ok=True):
        self.installed = set(installed)
        self.failures = dict(failures or {})
        self.dry_run = dry_run
        self.probe_ok = probe_ok
        self.calls: list[tuple[list[str], float, dict | None]] = []
        self.now = 0.0
        self.sleeps: list[float] = []

    def clock(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds

    def which(self, name: str) -> str | None:
        return f"/usr/bin/{name}"

    def kind(self, argv: list[str]) -> str:
        if argv[0] == "dpkg-query":
            return "query"
        if argv[0] == "sudo":
            tool = argv[argv.index("DEBIAN_FRONTEND=noninteractive") + 1]
            if tool == "dpkg":
                return "repair"
            return "update" if "update" in argv else "install"
        if argv[1:3] == ["-m", "playwright"]:
            return "dry-run" if "--dry-run" in argv else "download"
        if argv[1] == "-c":
            return "probe"
        return "version"

    def __call__(self, argv, seconds, env):
        argv = list(argv)
        self.calls.append((argv, seconds, env))
        kind = self.kind(argv)
        if kind == "query":
            ok = argv[-1] in self.installed
            return prereq.Result(0 if ok else 1, "installed" if ok else "")
        if kind == "dry-run":
            return prereq.Result(0, self.dry_run)
        if kind == "probe":
            return prereq.Result(
                0 if self.probe_ok else 1, "chromium 145.0" if self.probe_ok else ""
            )
        queue = self.failures.get(kind, [])
        outcome = queue.pop(0) if queue else "ok"
        if outcome == "timeout":
            self.now += seconds
            return prereq.Result(124, "Ign:1 mirror+file:/etc/apt/apt-mirrors.txt", timed_out=True)
        if outcome == "fail":
            self.now += 1
            return prereq.Result(100, "E: Unable to fetch some archives")
        self.now += 1
        if kind == "install":
            self.installed.update(argv[argv.index("--no-install-recommends") + 1 :])
        return prereq.Result(0, "ffmpeg version 6.1" if kind == "version" else "")

    def of(self, kind: str) -> list[list[str]]:
        return [argv for argv, _, _ in self.calls if self.kind(argv) == kind]


def helper(host: FakeHost, deadline: float = prereq.DEADLINE_SECONDS):
    lines: list[str] = []
    tool = prereq.Prerequisites(
        runner=host,
        which=host.which,
        sleep=host.sleep,
        clock=host.clock,
        python="/venv/bin/python",
        deadline_seconds=deadline,
        log=lines.append,
    )
    return tool, lines


ALL_PACKAGES = {"ffmpeg", "e2fsprogs", "util-linux", *BROWSER_LIBS}


def test_present_prerequisites_skip_apt_and_still_prove_tools_and_browser() -> None:
    host = FakeHost(installed=ALL_PACKAGES)
    tool, lines = helper(host)
    tool.require(["codec", "filesystem", "browser"])
    assert host.of("update") == host.of("install") == []
    assert "apt: all 6 required packages already installed" in lines
    assert host.of("version") == [["ffmpeg", "-version"], ["ffprobe", "-version"]]
    assert host.of("download") == [["/venv/bin/python", "-m", "playwright", "install", "chromium"]]
    download_env = next(env for argv, _, env in host.calls if host.kind(argv) == "download")
    assert download_env == {"PLAYWRIGHT_DOWNLOAD_CONNECTION_TIMEOUT": "30000"}
    assert len(host.of("probe")) == 1


def test_missing_packages_install_once_with_bounded_root_timeout() -> None:
    host = FakeHost(installed={"e2fsprogs", "util-linux", "libnss3"})
    tool, _ = helper(host)
    tool.require(["codec", "filesystem", "browser"])
    (update,) = host.of("update")
    (install,) = host.of("install")
    bounded = ["sudo", "--non-interactive", "timeout", "--kill-after=10s"]
    assert update[:4] == install[:4] == bounded
    assert update[4] == f"{prereq.UPDATE_SECONDS}s"
    assert install[4] == f"{prereq.INSTALL_SECONDS}s"
    for argv in (update, install):
        options = argv[argv.index("apt-get") + 1 :]
        assert "Acquire::http::Timeout=20" in options
        assert "Acquire::https::Timeout=20" in options
        assert "DPkg::Lock::Timeout=60" in options
    assert install[install.index("--no-install-recommends") + 1 :] == [
        "ffmpeg",
        "libgbm1",
        "fonts-liberation",
    ]
    assert host.of("repair") == []


def test_apt_stall_fails_closed_after_bounded_attempts_without_install() -> None:
    host = FakeHost(failures={"update": ["timeout"] * 3})
    tool, lines = helper(host)
    with pytest.raises(prereq.PrerequisiteError, match="apt-get update: failed after 3"):
        tool.require(["codec"])
    assert len(host.of("update")) == prereq.ATTEMPTS
    assert host.of("install") == host.of("version") == []
    assert host.sleeps == list(prereq.BACKOFF_SECONDS)
    assert any("attempt 3/3 timed out" in line for line in lines)
    assert any("apt-mirrors.txt" in line for line in lines)


def test_failed_install_repairs_dpkg_before_retrying() -> None:
    host = FakeHost(installed=ALL_PACKAGES - {"ffmpeg"}, failures={"install": ["timeout"]})
    tool, lines = helper(host)
    tool.require(["codec"])
    assert len(host.of("install")) == 2
    (repair,) = host.of("repair")
    assert repair[-3:] == ["dpkg", "--configure", "-a"]
    order = [host.kind(argv) for argv, _, _ in host.calls]
    assert order.index("repair") < len(order) - 1 - order[::-1].index("install")
    assert "apt-get install: ok on attempt 2 in 1s" in lines


def test_overall_deadline_caps_every_attempt_and_fails_closed() -> None:
    host = FakeHost(failures={"update": ["timeout"] * 3})
    tool, _ = helper(host, deadline=150)
    with pytest.raises(prereq.PrerequisiteError, match="budget spent"):
        tool.require(["codec"])
    limits = [seconds for argv, seconds, _ in host.calls if host.kind(argv) == "update"]
    assert limits[0] == prereq.UPDATE_SECONDS + 20
    assert all(limit <= 150 + 20 for limit in limits)
    assert host.now <= 150 + 20


def test_browser_download_retries_then_fails_closed() -> None:
    host = FakeHost(installed=ALL_PACKAGES, failures={"download": ["fail"] * 3})
    tool, _ = helper(host)
    with pytest.raises(prereq.PrerequisiteError, match="playwright install: failed after 3"):
        tool.require(["browser"])
    assert host.of("probe") == []


@pytest.mark.parametrize(
    "dry_run",
    ["", "nothing to install\n", 'apt-get install -y --no-install-recommends lib$(boom)"'],
)
def test_unreadable_playwright_dependency_list_fails_closed(dry_run: str) -> None:
    host = FakeHost(dry_run=dry_run)
    tool, _ = helper(host)
    with pytest.raises(prereq.PrerequisiteError, match="Chromium system packages"):
        tool.require(["browser"])
    assert host.of("update") == host.of("download") == []


def test_browser_that_cannot_launch_fails_closed() -> None:
    host = FakeHost(installed=ALL_PACKAGES, probe_ok=False)
    tool, _ = helper(host)
    with pytest.raises(prereq.PrerequisiteError, match="did not launch"):
        tool.require(["browser"])


def test_missing_command_after_install_fails_closed() -> None:
    host = FakeHost(installed=ALL_PACKAGES)
    tool, _ = helper(host)
    tool.which = lambda name: None if name == "findmnt" else f"/usr/bin/{name}"
    with pytest.raises(prereq.PrerequisiteError, match="findmnt"):
        tool.require(["filesystem"])


def test_main_reports_a_github_error_and_nonzero(monkeypatch, capsys) -> None:
    def refuse(self, components):
        raise prereq.PrerequisiteError("apt-get update: failed after 3 bounded attempts")

    monkeypatch.setattr(prereq.Prerequisites, "require", refuse)
    assert prereq.main(["codec"]) == 1
    assert "::error::CI prerequisites: apt-get update" in capsys.readouterr().out


def test_run_bounded_kills_the_whole_process_group_on_timeout(tmp_path) -> None:
    marker = tmp_path / "child-survived"
    started = time.monotonic()
    result = prereq.run_bounded(
        ["sh", "-c", f"(sleep 3; touch {shlex.quote(str(marker))}) & sleep 30"], 1
    )
    assert result.timed_out and result.returncode == 124
    assert time.monotonic() - started < 10
    time.sleep(3.5)
    assert not marker.exists()


def test_locked_playwright_reports_parseable_chromium_packages() -> None:
    tool = prereq.Prerequisites(python=sys.executable)
    packages = tool.browser_packages()
    assert "libnss3" in packages
    assert all(prereq.PACKAGE_NAME.fullmatch(name) for name in packages)


def _jobs() -> dict:
    workflow = (ROOT / ".github/workflows/application.yml").read_text(encoding="utf-8")
    assert "apt-get" not in workflow
    assert "--with-deps" not in workflow
    return yaml.safe_load(workflow)["jobs"]


@pytest.mark.parametrize(
    ("job_id", "step_name", "components", "first_use"),
    [
        (
            "validate-sales-xray-acquisition-browser",
            "Require codec and locked acquisition browser",
            ["codec", "browser"],
            "Build verified AudioAtlas for acquisition browser",
        ),
        (
            "validate-python-tests",
            "Require codec, filesystem and locked browser prerequisites",
            ["codec", "filesystem", "browser"],
            "Build verified AudioAtlas for conversation regressions",
        ),
        (
            "validate-python-gates",
            "Require codec, filesystem and locked browser prerequisites",
            ["codec", "filesystem", "browser"],
            "Build verified AudioAtlas for conversation regressions",
        ),
    ],
)
def test_each_job_runs_one_bounded_locked_prerequisite_step(
    job_id, step_name, components, first_use
) -> None:
    job = _jobs()[job_id]
    names = [step.get("name") for step in job["steps"]]
    assert names.count(step_name) == 1
    step = job["steps"][names.index(step_name)]
    assert "if" not in step and not step.get("continue-on-error", False)
    assert step["timeout-minutes"] * 60 > prereq.DEADLINE_SECONDS
    assert step["timeout-minutes"] < job["timeout-minutes"]
    assert shlex.split(step["run"]) == [
        "uv",
        "run",
        "--frozen",
        "python",
        "scripts/ci/ci_prerequisites.py",
        *components,
    ]
    locked = next(i for i, name in enumerate(names) if name and name.startswith("Install locked"))
    assert locked < names.index(step_name) < names.index(first_use)


def test_python_shards_coverage_and_evidence_are_unchanged() -> None:
    jobs = _jobs()
    shards = jobs["validate-python-tests"]
    assert shards["strategy"]["matrix"]["shard"] == [0, 1, 2, 3]
    assert shards["strategy"]["fail-fast"] is False
    assert shards["timeout-minutes"] == 30
    names = [step.get("name") for step in shards["steps"]]
    run = shards["steps"][names.index("Run deterministic Python test shard")]
    assert "--shard-count 4" in run["run"]
    evidence = shards["steps"][names.index("Retain Python shard evidence")]
    assert evidence["if"] == "always()"
    assert evidence["with"]["if-no-files-found"] == "error"
    aggregate = [step.get("name") for step in jobs["validate"]["steps"]]
    assert "Verify complete Python shard coverage" in aggregate
